# -*- coding: utf-8 -*-
"""三个服务共用的模块。

- 页面服务 static_server.py（6021）：只提供前端静态文件；
- 接口服务 api_server.py（8080）：提供 /api/* 业务接口；
- 数据库服务 db_server.py（6060）：唯一直接连接数据库的进程。

本模块供前两者导入：负责读同一份 config.json、提供业务常量与权限校验，
并把所有 SQL 通过 HTTP 转发给 6060 数据库服务（见 db_cursor），
本进程不再持有任何数据库驱动与连接。

进程间的协作约定：
- 浏览器会话 Cookie 由页面服务签发，接口服务用同一个 secret_key 与同一个 SESSION_EPOCH 校验，因此能识别出同一个登录会话；
- SESSION_EPOCH 存在 data/.epoch 文件中，各进程读到的是同一个值，重启其中一个不会误判对方签发的会话失效。
"""

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from functools import wraps
from threading import Lock
from flask import abort, jsonify, redirect, request, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.request

# 后端目录（common.py 所在目录），存放 server.py / api_server.py / virtual_plc.py 等 Python 服务文件
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
# 项目根目录：backend/ 的上一级，config/ 和 data/ 都在这里
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
# 前端目录：与 backend/ 同级的 frontend/，存放 Templates（Jinja 模板）与 static（css/js）
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")
# 配置目录：config/config.json
CONFIG_DIR = os.path.join(PROJECT_DIR, "config")
# 数据目录：data/mes.db、data/.epoch 等运行时文件
DATA_DIR = os.path.join(PROJECT_DIR, "data")


def load_config():
    """读取并合并服务端配置。

    数据来源：项目根目录 config/config.json；文件不存在时全部使用内置默认值。
    database 与 plc 两个子字典按「默认值 + 配置文件字段覆盖」做二级合并，其余顶层键直接覆盖。
    返回：配置字典，含 host、frontend_port、backend_port、secret_key、
          database（type/host/user/password/name）、plc（ip/port）。
    副作用：读取磁盘上的 config.json；字段缺失或 json 内容不全时不报错，用默认值兜底。
    """
    path = os.path.join(CONFIG_DIR, "config.json")
    cfg = {
        "host": "0.0.0.0",
        "frontend_port": 6021,
        "backend_port": 8080,
        "secret_key": "mes_secret_key_2026",
        "database": {
            "type": "auto",
            "host": "localhost",
            "user": "root",
            "password": "123456",
            "name": "mes_db",
        },
        "plc": {"ip": "127.0.0.1", "port": 502},
    }
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        cfg.update({k: v for k, v in loaded.items() if k not in ("database", "plc")})
        cfg["database"].update(loaded.get("database") or {})
        cfg["plc"].update(loaded.get("plc") or {})
    return cfg


# 全局配置总入口：CONFIG 保存合并后的原始配置，下面几个变量是从 CONFIG 里抽出来的展开值，供业务代码直接使用
CONFIG = load_config()
# config.json 的绝对路径；后端服务修改 PLC 地址后会写回这个文件
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
# MySQL 连接参数字典（pymysql.connect 直接展开使用），database 对应 config.json 中 database.name 的值
# 使用方：6060 数据库服务负责用它建立连接；接口服务仅读取 host/name 用于页面展示，不拿它连库
DB_CONFIG = {
    "host": CONFIG["database"].get("host", "localhost"),
    "port": int(CONFIG["database"].get("port", 3306)),
    "user": CONFIG["database"].get("user", "root"),
    "password": CONFIG["database"].get("password", "123456"),
    "database": CONFIG["database"].get("name", "mes_db"),
    "charset": "utf8mb4",
}
# PLC（Modbus TCP）目标地址；port 强制转 int，避免 JSON 读到字符串导致连接报错
PLC_CONFIG = {
    "ip": CONFIG["plc"].get("ip", "127.0.0.1"),
    "port": int(CONFIG["plc"].get("port", 502)),
}
# 前端页面服务端口：页面渲染 + 表单提交，管理员与成员共用，按角色区分权限
FRONTEND_PORT = int(CONFIG.get("frontend_port") or 6021)
# 后端接口服务端口：所有 /api/* JSON 接口，以及 PLC 轮询与产线仿真线程
BACKEND_PORT = int(CONFIG.get("backend_port") or 8080)
# 内置的初始管理员账号名：由数据库服务首次建库时创建，是唯一有权删除其它管理员账号的账号
ROOT_ADMIN_USERNAME = "admin"
# 当前实际生效的数据库引擎："mysql" 或 "sqlite"，由 6060 数据库服务探测后经 init_db() 回写本进程，仅用于页面展示
DB_ENGINE = "mysql"
# 数据库服务地址：唯一直接访问数据库的进程，本进程通过 HTTP 调用它执行 SQL
DB_SERVICE_HOST = (CONFIG.get("db_service") or {}).get("host") or "127.0.0.1"
DB_SERVICE_PORT = int((CONFIG.get("db_service") or {}).get("port") or 6060)
DB_SERVICE_URL = f"http://{DB_SERVICE_HOST}:{DB_SERVICE_PORT}"
# 单次调用超时（秒）：数据库服务无响应时直接报错，避免请求线程被无限挂住
DB_SERVICE_TIMEOUT = 10


def _load_session_epoch():
    """读取进程间共享的会话代次（session 指纹的一部分）。

    返回：16 字节随机十六进制字符串；两个服务进程读到的是同一个值，因此互相能校验对方签发的会话。
    说明：值保存在 data/.epoch，文件不存在时自动生成；两个进程同时首次启动时以文件最终内容为准，
          避免各自生成一份导致会话互不认账。
    """
    path = os.path.join(DATA_DIR, ".epoch")
    try:
        with open(path, encoding="utf-8") as fh:
            value = fh.read().strip()
        if value:
            return value
    except OSError:
        pass
    value = secrets.token_hex(16)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(value)
        # 写入后回读一次：万一另一个进程抢先写入了不同的值，以磁盘上的为准
        with open(path, encoding="utf-8") as fh:
            back = fh.read().strip()
        return back or value
    except OSError:
        return value


# 会话代次：删除 data/.epoch 并重启两个服务即可让所有已登录会话立即失效
SESSION_EPOCH = _load_session_epoch()
# 用户短缓存：页面轮询会频繁走 login_required，避免每次请求都打一次 users 表
USER_CACHE_TTL = 3
_user_cache = {}
_user_cache_lock = Lock()

# 全局仿真运行倍速因子（1.0 / 2.0 / 5.0 / 10.0，供教学与调试加速）
SIMULATION_SPEED = 1.0
_speed_lock = Lock()


def get_sim_speed():
    with _speed_lock:
        return SIMULATION_SPEED


def set_sim_speed(speed):
    global SIMULATION_SPEED
    try:
        val = float(speed)
        if val in (1.0, 2.0, 5.0, 10.0) or (0.5 <= val <= 20.0):
            with _speed_lock:
                SIMULATION_SPEED = val
            return True, val
    except (ValueError, TypeError):
        pass
    return False, SIMULATION_SPEED

# 产线 7 个工位：与「无线充智能自动化产线」工艺流程图与工业现场技术标准一致
# 包含丰富工业参数、传感器信号映射、检测公差与质量判定标准
STATION_DEFS = [
    {
        "code": "ST01",
        "name": "自动上料",
        "full_name": "自动上料工作站 (OP10)",
        "step": "01",
        "tone": "navy",
        "cycle_sec": 3,
        "plc_address": 10,
        "role": "上料",
        "desc": "治具底座载具定位、外壳底座自动取料吸附、光电防呆识别",
        "sensors": [
            {"name": "载具定位到位光电", "pin": "DI0.0", "status": "ON"},
            {"name": "真空吸盘负压感应", "pin": "DI0.1", "status": "ON"},
            {"name": "料仓余料低位预警", "pin": "DI0.2", "status": "ON"}
        ],
        "params": [
            {"key": "吸盘真空度", "value": "-82.5 kPa", "standard": "<-75.0 kPa"},
            {"key": "载具定位重复精度", "value": "±0.03 mm", "standard": "±0.08 mm"},
            {"key": "上料节拍工时", "value": "2.8 s", "standard": "≤ 3.5 s"}
        ],
        "qc_criteria": "载具平整无倾斜、底座朝向正确、吸取无刮伤"
    },
    {
        "code": "ST02",
        "name": "主板安装",
        "full_name": "PCBA主板组装工作站 (OP20)",
        "step": "02",
        "tone": "teal",
        "cycle_sec": 4,
        "plc_address": 11,
        "role": "装配",
        "desc": "高精度CCD视觉对位引导、PCBA芯片拾取放置、卡扣预压入",
        "sensors": [
            {"name": "CCD视觉引导触发", "pin": "DI1.0", "status": "ON"},
            {"name": "精密气动夹爪闭合", "pin": "DI1.1", "status": "ON"},
            {"name": "主板卡扣到位感应", "pin": "DI1.2", "status": "ON"}
        ],
        "params": [
            {"key": "CCD对位偏差 X/Y", "value": "0.02 mm", "standard": "< 0.06 mm"},
            {"key": "卡扣锁紧深度", "value": "1.25 mm", "standard": "1.2±0.1 mm"},
            {"key": "气缸下压保持力", "value": "12.8 N", "standard": "12.0±2.0 N"}
        ],
        "qc_criteria": "主板平整无拱起、无虚焊压损、PIN脚无偏斜"
    },
    {
        "code": "ST03",
        "name": "后盖安装",
        "full_name": "线圈与后盖合装工作站 (OP30)",
        "step": "03",
        "tone": "sky",
        "cycle_sec": 4,
        "plc_address": 12,
        "role": "装配",
        "desc": "磁吸发射线圈预置、导热硅胶垫自动贴附、后盖压头保压扣合",
        "sensors": [
            {"name": "导热垫反射光电", "pin": "DI2.0", "status": "ON"},
            {"name": "压合滑台下限位", "pin": "DI2.1", "status": "ON"},
            {"name": "磁吸极性霍尔检测", "pin": "DI2.2", "status": "ON"}
        ],
        "params": [
            {"key": "外壳四周缝隙", "value": "0.12 mm", "standard": "< 0.20 mm"},
            {"key": "保压持续时间", "value": "1.5 s", "standard": "≥ 1.2 s"},
            {"key": "磁极垂直吸引力", "value": "11.2 N", "standard": "≥ 10.0 N"}
        ],
        "qc_criteria": "外壳扣合无缝隙、无溢胶松动、线圈居中对称"
    },
    {
        "code": "ST04",
        "name": "螺丝锁附",
        "full_name": "智能伺服螺丝锁附工作站 (OP40)",
        "step": "04",
        "tone": "slate",
        "cycle_sec": 4,
        "plc_address": 13,
        "role": "锁附",
        "desc": "伺服电批4点自动吹气送钉、实时扭矩与拧紧角度曲线监控",
        "sensors": [
            {"name": "自动吹钉管道光电", "pin": "DI3.0", "status": "ON"},
            {"name": "伺服到达目标扭矩", "pin": "DI3.1", "status": "ON"},
            {"name": "螺钉沉头深度传感器", "pin": "DI3.2", "status": "ON"}
        ],
        "params": [
            {"key": "终拧锁附扭矩", "value": "0.348 N·m", "standard": "0.35±0.03 N·m"},
            {"key": "拧紧旋转角度", "value": "722 °", "standard": "720±30 °"},
            {"key": "批头沉降高度", "value": "2.85 mm", "standard": "2.8±0.1 mm"}
        ],
        "qc_criteria": "无滑丝、无浮锁、无漏锁，扭矩严格在合格带内"
    },
    {
        "code": "ST05",
        "name": "激光打标",
        "full_name": "智能激光打标与赋码工作站 (OP50)",
        "step": "05",
        "tone": "peach",
        "cycle_sec": 4,
        "plc_address": 14,
        "role": "打标",
        "desc": "产品唯一SN追溯码与GS1 DataMatrix二维码高精激光镭雕",
        "sensors": [
            {"name": "打标防辐射安全光幕", "pin": "DI4.0", "status": "ON"},
            {"name": "烟尘抽吸负压传感器", "pin": "DI4.1", "status": "ON"},
            {"name": "激光发生器就绪", "pin": "DI4.2", "status": "ON"}
        ],
        "params": [
            {"key": "光纤激光功率", "value": "20.0 W", "standard": "20.0±1.0 W"},
            {"key": "标刻刻印深度", "value": "0.035 mm", "standard": "0.03±0.01 mm"},
            {"key": "二维码读取等级", "value": "A级 (4.0)", "standard": "≥ B级 (3.0)"}
        ],
        "qc_criteria": "字迹清晰无重影、二维码扫码读取率100%"
    },
    {
        "code": "ST06",
        "name": "成品检测",
        "full_name": "电性能与FOD无线充综合质检站 (OP60)",
        "step": "06",
        "tone": "orange",
        "cycle_sec": 5,
        "plc_address": 15,
        "role": "检测",
        "desc": "Qi2快充握手协议、异物FOD切断保护、谐振频率与温升监控",
        "sensors": [
            {"name": "测试气缸下压到位", "pin": "DI5.0", "status": "ON"},
            {"name": "快充协议芯片联通", "pin": "DI5.1", "status": "ON"},
            {"name": "红外测温热电偶", "pin": "DI5.2", "status": "ON"}
        ],
        "params": [
            {"key": "满载无线输出功率", "value": "15.12 W", "standard": "15.0±0.5 W"},
            {"key": "电磁谐振频率", "value": "127.8 kHz", "standard": "127.5±2.0 kHz"},
            {"key": "整机传输转换效率", "value": "84.6 %", "standard": "≥ 80.0 %"}
        ],
        "qc_criteria": "无线充协议握手正常，金属异物切断保护响应<0.5s"
    },
    {
        "code": "ST07",
        "name": "自动下料",
        "full_name": "协作机械臂分拣下料工作站 (OP70)",
        "step": "07",
        "tone": "ember",
        "cycle_sec": 3,
        "plc_address": 16,
        "role": "下料",
        "desc": "六轴协作机械臂智能分拣，良品托盘码垛，不良品剔除返工箱",
        "sensors": [
            {"name": "机械臂抓手到达取料位", "pin": "DI6.0", "status": "ON"},
            {"name": "良品料仓载盘就绪", "pin": "DI6.1", "status": "ON"},
            {"name": "不良品返工滑道通畅", "pin": "DI6.2", "status": "ON"}
        ],
        "params": [
            {"key": "机械臂末端速度", "value": "650 mm/s", "standard": "≤ 800 mm/s"},
            {"key": "吸盘气压保持力", "value": "24.5 N", "standard": "≥ 20.0 N"},
            {"key": "分拣下料周期", "value": "2.6 s", "standard": "≤ 3.2 s"}
        ],
        "qc_criteria": "良品码垛排列规整，不良品100%分流隔离"
    },
]
STATION_COUNT = len(STATION_DEFS)
LAST_STATION_NAME = STATION_DEFS[-1]["name"]

# 可生产的无线充电产品字典，工单页产品下拉框与新建工单的数据源
# 字段：code 产品编码 / name 产品名称 / model 型号说明 / cycle_time 整单理论生产节拍（秒）
PRODUCTS = [
    {"code": "WC-10W", "name": "10W桌面极简无线充电器", "model": "桌面极简款", "cycle_time": 27, "power": "10W", "coils": 1, "desc": "定频调压架构，高性价比桌面充"},
    {"code": "WC-15W", "name": "15W智能车载无线充电器", "model": "车载感应款", "cycle_time": 31, "power": "15W", "coils": 1, "desc": "红外感应开合夹臂，车载快速无线充"},
    {"code": "WC-MAG", "name": "15W磁吸超薄无线充模块", "model": "MagSafe磁吸款", "cycle_time": 25, "power": "15W", "coils": 1, "desc": "高导磁铁氧体，强磁对位便携模块"},
    {"code": "WC-PAD", "name": "20W三线圈无线充工作垫", "model": "多设备旗舰款", "cycle_time": 35, "power": "20W", "coils": 3, "desc": "多线圈无盲区自由摆放，支持多设备"},
]

# 课件节拍：客户 145 件/天，双班净可用 54000 秒 → 372 秒/件
PLAN = {
    "title": "智能无线充组装产线",
    "demand_per_day": 145,
    "shifts": 2,
    "shift_hours": 8.5,
    "lunch_min": 30,
    "rest_min": 30,
    "net_hours": 7.5,
    "net_sec_shift": 27000,
    "net_sec_day": 54000,
    "takt_sec": 372,
}

# 产品装配工艺（治具板上的 6 步，不含上下料机台）
PROCESS_STEPS = [
    {"no": "1", "name": "治具板准备"},
    {"no": "2", "name": "主板安装"},
    {"no": "3", "name": "后盖安装"},
    {"no": "4", "name": "螺丝锁附"},
    {"no": "5", "name": "激光打标"},
    {"no": "6", "name": "成品检测"},
]


def make_line_state():
    """产线运行状态的初始结构。

    返回：一条「未下发工单」的产线状态字典，字段：running 是否运行 / alarm+alarm_msg 故障标志与原因 /
          order_id|order_no 当前在制工单 / product_name 产品名 / quantity 计划数量 /
          completed_qty|ng_qty 合格与不良数 / station_index 当前工位下标（0 起）/
          piece_progress 当前工位单件完成百分比 / stations 各工位实时状态 /
          robot 机器人状态 / last_update 最近刷新时间 HH:MM:SS。
    说明：后端用它初始化真实产线与虚拟产线；前端在后端服务不可达时用它兜底渲染空页面。
    """
    return {
        "running": False,
        "alarm": False,
        "alarm_msg": "",
        "order_id": None,
        "order_no": "",
        "product_name": "",
        "quantity": 0,
        "completed_qty": 0,
        "ng_qty": 0,
        "station_index": 0,
        "piece_progress": 0,
        "stations": [
            {**s, "status": "空闲", "processed_qty": 0, "current_order_no": ""} for s in STATION_DEFS
        ],
        "robot": {"status": "待机", "position": "HOME", "task": "等待指令", "busy": False},
        "last_update": None,
    }


def _as_int(value):
    """把数据库聚合结果转成 int。SUM 在空表上是 None，MySQL 下还可能是 Decimal。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def json_safe(rows):
    """把数据库查询结果转成可被 jsonify 序列化的普通字典列表。

    参数 rows：由字典组成的查询结果集（dict_mode 游标返回的行），可为 None。
    返回：新的字典列表；Decimal 统一转 int，datetime/date 分别格式化为 "%Y-%m-%d %H:%M:%S" 与 "%Y-%m-%d"。
    说明：数据库服务已把结果值转成可 JSON 序列化的类型，这里做二次兜底，保证两种取值路径都能安全 jsonify。
    """
    safe = []
    for row in rows or []:
        item = {}
        for key, value in row.items():
            if isinstance(value, Decimal):
                # COUNT/SUM 在 MySQL 下会返回 Decimal，JSON 化时按整数处理
                item[key] = int(value)
            elif hasattr(value, "strftime"):
                # date 只有日期，datetime 需要带上时分秒，两者输出格式不同
                item[key] = value.strftime("%Y-%m-%d") if not isinstance(value, datetime) else value.strftime("%Y-%m-%d %H:%M:%S")
            else:
                item[key] = value
        safe.append(item)
    return safe


class DBServiceError(RuntimeError):
    """数据库服务调用失败（服务不可达或 SQL 执行报错）。"""


def _db_request(path, payload=None, method="POST", timeout=DB_SERVICE_TIMEOUT):
    """调用 6060 数据库服务的 HTTP 接口。

    参数 path：接口路径（如 /db/session/execute）；参数 payload：请求体字典，GET 时忽略；
    参数 method：HTTP 方法；参数 timeout：超时秒数。
    返回：响应体解析后的字典（已确认 ok 为真）。
    异常：服务不可达或响应 ok 为假时抛 DBServiceError，调用方按数据库报错处理。
    """
    data = None if method == "GET" else json.dumps(payload or {}, default=str).encode("utf-8")
    req = urllib.request.Request(
        DB_SERVICE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 服务已返回错误码：优先读响应体里的错误说明，读不到再用 HTTP 状态兜底
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {"ok": False, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        raise DBServiceError(f"数据库服务不可达（{DB_SERVICE_URL}）：{exc}") from exc
    if not body.get("ok"):
        raise DBServiceError(body.get("error") or "数据库服务返回失败")
    return body


def db_service_alive(timeout=1.0):
    """探测数据库服务是否就绪（启动时用）。返回：True/False。"""
    try:
        _db_request("/db/health", method="GET", timeout=timeout)
        return True
    except Exception:
        return False


class RemoteCursor:
    """远程游标：接口与本地数据库游标一致，实际把 SQL 转发给 6060 数据库服务执行。

    服务端一次性返回本次查询的全部结果行，本类在客户端按需 fetchone / fetchall；
    dict_cursor 为 True 时（对应 db_cursor(True)）结果行按列名转成字典，否则保持值序列。
    """

    def __init__(self, dict_mode=False):
        """参数 dict_mode：True 时 fetch 出来的行是 dict，否则是 tuple。"""
        self.dict_mode = dict_mode
        # 事务会话标识：首次 execute 时才向数据库服务申请，避免空会话往返
        self.session_id = None
        self.wrote = False
        self._columns = []
        self._rows = []

    def _ensure_session(self):
        """确保已开启事务会话。返回：session_id。"""
        if self.session_id is None:
            self.session_id = _db_request("/db/session/open", {})["session_id"]
        return self.session_id

    def execute(self, sql, args=None):
        """把一条 SQL 交给数据库服务执行。

        参数 sql：MySQL 风格 SQL（含 %s 占位符）；参数 args：参数元组/列表或 None。
        返回：影响行数。副作用：刷新本地结果缓冲，并记录本次事务是否写库。
        """
        session_id = self._ensure_session()
        body = _db_request(
            "/db/session/execute",
            {
                "session_id": session_id,
                "sql": sql,
                "args": list(args) if args is not None else None,
            },
        )
        self._columns = body.get("columns") or []
        self._rows = body.get("rows") or []
        self.wrote = self.wrote or bool(body.get("wrote"))
        return body.get("rowcount")

    def _convert(self, row):
        """按 dict_mode 把结果行转成字典或元组。参数 row：值序列或 None。"""
        if row is None:
            return None
        if self.dict_mode:
            return dict(zip(self._columns, row))
        return tuple(row)

    def fetchone(self):
        """取一行结果。返回：转换后的单行数据，无数据时返回 None。"""
        if not self._rows:
            return None
        return self._convert(self._rows.pop(0))

    def fetchall(self):
        """取全部剩余结果行。返回：行列表。"""
        rows = [self._convert(row) for row in self._rows]
        self._rows = []
        return rows

    def close(self):
        """关闭事务会话并释放数据库连接。返回：无。"""
        if self.session_id is None:
            return
        try:
            _db_request("/db/session/close", {"session_id": self.session_id})
        except Exception:
            pass
        self.session_id = None


@contextmanager
def db_cursor(dict_cursor=False):
    """数据库游标上下文管理器：自动提交、回滚并释放连接。

    参数 dict_cursor：True 时结果行按列名转成字典，否则是值元组。
    用法：`with db_cursor(True) as cursor:`，块内正常结束自动 commit，抛异常自动 rollback 并把异常继续上抛。
    返回：生成器，yield 出 RemoteCursor 实例（SQL 实际由 6060 数据库服务执行）。
    """
    cursor = RemoteCursor(dict_mode=dict_cursor)
    try:
        yield cursor
        # 本次事务没有任何写操作时不必提交，少一次网络往返
        if cursor.wrote and cursor.session_id:
            _db_request("/db/session/commit", {"session_id": cursor.session_id})
    except Exception:
        # 出错必须回滚，避免只写入一半的数据残留（例如工单状态与工位记录不一致）
        if cursor.session_id:
            try:
                _db_request("/db/session/rollback", {"session_id": cursor.session_id})
            except Exception:
                pass
        raise
    finally:
        # 无论成功失败都关闭会话，防止数据库连接泄漏
        cursor.close()


def init_db():
    """请求 6060 数据库服务完成建库、建表与基础数据初始化。

    返回：无。副作用：把数据库服务探测到的引擎写回本进程的 DB_ENGINE（供 /api/config 展示）；
    实际的建表、补列与种子数据都在数据库服务进程内完成，本进程不再直连数据库。
    说明：本函数可重复调用（幂等），启动失败时由调用方按重试策略处理。
    """
    global DB_ENGINE
    body = _db_request("/db/init", {}, timeout=30)
    DB_ENGINE = body.get("engine") or DB_ENGINE


def add_log(message, order_no="", level="INFO", category="sys"):
    """写入一条日志到 production_logs 表。

    参数 message：日志正文；参数 order_no：关联工单号，可为空；
    参数 level：INFO / WARN / ALARM；参数 category：sys 系统日志，line 产线运行日志。
    返回：无。写库失败时只打印提示，不打断主流程。
    """
    try:
        with db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO production_logs (order_no, level, message, category) VALUES (%s, %s, %s, %s)",
                (order_no, level, message, category),
            )
    except Exception as exc:
        print(f"日志写入失败: {exc}")


def fetch_logs(category=None, limit=30, levels=None):
    """查询最近日志，created_at 转成 HH:MM:SS，供页面和 /api/logs 使用。"""
    clauses, args = [], []
    if category:
        clauses.append("category=%s")
        args.append(category)
    if levels:
        marks = ",".join(["%s"] * len(levels))
        clauses.append(f"level IN ({marks})")
        args.extend(levels)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    args.append(int(limit))
    with db_cursor(True) as cursor:
        cursor.execute(f"SELECT * FROM production_logs{where} ORDER BY id DESC LIMIT %s", args)
        logs = cursor.fetchall()
    for item in logs:
        created = item.get("created_at")
        if not created:
            continue
        if hasattr(created, "strftime"):
            item["created_at"] = created.strftime("%H:%M:%S")
        else:
            text = str(created)
            item["created_at"] = text[11:19] if len(text) >= 19 else text
    return logs


def session_signature(user):
    """会话指纹：绑定当前会话代次与账号密码，改密码或重置会话后旧会话立即失效。

    参数 user：users 表的一行（需含 username 与 password_hash）。
    返回：sha256 十六进制摘要字符串；登录时写入 session["sign"]，其后每次请求由 login_required 重新比对。
    说明：摘要只依赖 data/.epoch 与数据库内容，前后端两个进程算出的结果一致。
    """
    raw = f"{SESSION_EPOCH}:{user['username']}:{user['password_hash']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def login_required(func):
    """登录校验装饰器。

    参数 func：被装饰的视图函数。
    返回：包装后的视图函数；未登录或会话失效时，/api/ 开头的请求返回 401 JSON，页面请求重定向到登录页。
    副作用：校验通过后会用数据库中的最新信息刷新 session 的 role、display_name、user_id，使角色变更即时生效。
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        """装饰器内部的实际执行体：校验登录状态与会话指纹后调用原视图函数。

        返回：校验通过时返回原视图函数的返回值；未登录或会话失效时返回 401 JSON 或登录页重定向。
        """
        if "logged_in" not in session:
            # 前端 fetch 期望 JSON 响应，浏览器访问页面则跳转登录页
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "未登录"}), 401
            return redirect(url_for("login"))
        user = get_user(session.get("username"))
        # 三类失效情形：账号被删除、账号被停用、指纹不匹配（会话代次变化或密码被重置）
        if not user or user.get("status") != "启用" or session.get("sign") != session_signature(user):
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "登录已失效，请重新登录"}), 401
            return redirect(url_for("login"))
        # 管理员可能刚改过该用户的信息，这里每次请求都回写最新值
        session["role"] = user["role"]
        session["display_name"] = user.get("display_name") or user["username"]
        session["user_id"] = user["id"]
        return func(*args, **kwargs)
    return wrapper


def admin_required(func):
    """管理员权限装饰器（内部已叠加 login_required，未登录同样会被拦截）。

    参数 func：被装饰的视图函数。
    返回：包装后的视图函数；非 admin 角色时，API 或 POST/DELETE 请求返回 403 JSON，其余情况渲染 403 错误页。
    """
    @wraps(func)
    @login_required
    def wrapper(*args, **kwargs):
        """装饰器内部的实际执行体：登录校验通过后再校验管理员身份。

        返回：角色为 admin 时返回原视图函数的返回值，否则返回 403 JSON 或 403 错误页。
        """
        if session.get("role") != "admin":
            # 前端 fetch 需要 JSON 错误体，普通页面访问则走统一的 403 页面
            if request.path.startswith("/api/") or request.method in ("POST", "DELETE"):
                return jsonify({"ok": False, "error": "需要管理员权限"}), 403
            abort(403)
        return func(*args, **kwargs)
    return wrapper


def is_admin():
    """判断当前会话是否为管理员。返回：True/False（只依赖 session 中的 role，不再查库）。"""
    return session.get("role") == "admin"


def invalidate_user_cache(username=None):
    """清掉用户短缓存。不传 username 时清空全部。"""
    with _user_cache_lock:
        if username is None:
            _user_cache.clear()
        else:
            _user_cache.pop(username, None)


def get_user(username):
    """按用户名查询用户记录。

    参数 username：登录账号；为空时直接返回 None，避免无意义的查询。
    返回：包含 id、password_hash、role、status 等字段的字典；未找到返回 None。
    说明：命中短缓存时返回副本，避免调用方改到缓存里的字典。
    """
    if not username:
        return None
    now = time.time()
    with _user_cache_lock:
        cached = _user_cache.get(username)
        if cached and now - cached[0] < USER_CACHE_TTL:
            return dict(cached[1])
    with db_cursor(True) as cursor:
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()
    if user:
        user = dict(user)
        with _user_cache_lock:
            _user_cache[username] = (now, user)
        return dict(user)
    return None


def verify_login(username, password):
    """校验账号密码与启用状态。

    返回：(user, code, message)。成功时 user 为用户字典、code 为 0、message 为 None；
    失败时 user 为 None，code 为 -2（账号密码错误）/ -3（账号停用）。
    说明：管理员与成员共用同一个登录入口，登录后能看到哪些功能由角色权限决定，与端口无关。
    """
    user = get_user(username)
    if not user or not check_password_hash(user["password_hash"], password):
        return None, -2, "账号或密码错误"
    if user["status"] != "启用":
        return None, -3, "账号已被停用，请联系管理员"
    return user, 0, None


def list_users():
    """查询全部用户列表（不返回密码哈希字段）。

    返回：按 id 升序的用户字典列表，字段为 id / username / display_name / role / status / created_at。
    """
    with db_cursor(True) as cursor:
        cursor.execute("SELECT id, username, display_name, role, status, created_at FROM users ORDER BY id")
        return cursor.fetchall()


def sign_in(user):
    """登录成功后把用户信息写入会话。

    参数 user：users 表的一行。
    返回：无。副作用：填充 session（logged_in、user_id、username、display_name、role）并写入会话指纹 sign。
    """
    session["logged_in"] = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["display_name"] = user.get("display_name") or user["username"]
    session["role"] = user["role"]
    # 指纹与账号密码绑定，供后续每次请求校验会话是否仍然有效
    session["sign"] = session_signature(user)


def next_order_no():
    """生成下一个工单号，格式为 WC + 年月日 + 3 位流水号。

    返回：形如 WC20260917-001 的工单号字符串。取当天已有工单的最大流水号加一，跨天自动从 001 重新开始。
    """
    # 前缀按月日生成，天然实现按天分段编号
    prefix = datetime.now().strftime("WC%Y%m%d")
    with db_cursor(True) as cursor:
        # 取当天流水号最大的工单（按 id 倒序即可，编号是顺序递增的）
        cursor.execute(
            "SELECT order_no FROM production_orders WHERE order_no LIKE %s ORDER BY id DESC LIMIT 1",
            (prefix + "%",),
        )
        row = cursor.fetchone()
    seq = 1
    # 末 3 位是流水号；若为历史脏数据（非数字）则从 001 开始
    if row and row["order_no"][-3:].isdigit():
        seq = int(row["order_no"][-3:]) + 1
    return f"{prefix}-{seq:03d}"


def order_stats(include_orders=True, order_limit=None):
    """统计工单总体情况，供首页、工单页、生产页模板以及 /api/stats 使用。

    参数 include_orders：False 时不拉工单明细（/api/stats 只要数字）。
    参数 order_limit：只取前 N 条工单（首页最近工单用），None 表示全部。
    返回：字典，含 orders、total_orders、pending_count、in_progress_count、
    completed_count、planned_qty、completed_qty、ng_qty、yield_rate（良率百分比，保留 1 位小数）。
    """
    with db_cursor(True) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS total_orders,
                   SUM(CASE WHEN status='待生产' THEN 1 ELSE 0 END) AS pending_count,
                   SUM(CASE WHEN status='生产中' THEN 1 ELSE 0 END) AS in_progress_count,
                   SUM(CASE WHEN status='已完成' THEN 1 ELSE 0 END) AS completed_count,
                   SUM(quantity) AS planned_qty,
                   SUM(completed_qty) AS completed_qty,
                   SUM(ng_qty) AS ng_qty
            FROM production_orders
            """
        )
        row = cursor.fetchone() or {}
        orders = []
        if include_orders:
            sql = "SELECT * FROM production_orders ORDER BY priority DESC, created_at DESC"
            params = None
            if order_limit:
                sql += " LIMIT %s"
                params = (_as_int(order_limit),)
            cursor.execute(sql, params)
            orders = cursor.fetchall()
    completed_qty = _as_int(row.get("completed_qty"))
    ng_qty = _as_int(row.get("ng_qty"))
    return {
        "orders": orders,
        "total_orders": _as_int(row.get("total_orders")),
        "pending_count": _as_int(row.get("pending_count")),
        "in_progress_count": _as_int(row.get("in_progress_count")),
        "completed_count": _as_int(row.get("completed_count")),
        "planned_qty": _as_int(row.get("planned_qty")),
        "completed_qty": completed_qty,
        "ng_qty": ng_qty,
        "yield_rate": round(completed_qty * 100 / max(completed_qty + ng_qty, 1), 1),
    }