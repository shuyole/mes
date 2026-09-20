# -*- coding: utf-8 -*-
"""三个服务共用的模块。

- 前端静态页面服务 static_server.py（默认 6031）：只提供 frontend/ 目录的 HTML/CSS/JS；
- 后端接口服务 api_server.py（默认 8090）：提供 /api/* 接口，负责账号密码校验等业务逻辑；
- 数据库服务 db_server.py（默认 6070）：唯一直接读写 SQLite 的进程。

前端与后端都导入本模块：读同一份 config/config.json、共用会话工具，
所有 SQL 都通过 HTTP 转发给数据库服务执行（见 db_cursor），本进程不持有数据库连接。

会话为什么能跨端口：前端页面与后端接口同主机、不同端口，浏览器判定为「同站」，
因此会一并在请求中带上后端签发的会话 Cookie，登录态可以跨端口识别。
"""

from contextlib import contextmanager
from functools import wraps
from threading import Lock
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.request

from flask import jsonify, session


# ===== 目录常量 =====
# 后端目录（本文件所在目录）
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
# 项目根目录：backend/ 的上一级
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
# 前端目录：与 backend/ 同级的 frontend/
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")
# 配置目录：config/config.json
CONFIG_DIR = os.path.join(PROJECT_DIR, "config")
# 数据目录：data/auth.db、data/.epoch
DATA_DIR = os.path.join(PROJECT_DIR, "data")


def load_config():
    """读取并合并服务端配置。

    数据来源：config/config.json；文件不存在时全部使用内置默认值。
    db_service 与 database 两个子字典按「默认值 + 配置文件字段覆盖」二级合并，其余顶层键直接覆盖。
    返回：配置字典，含 host、frontend_port、backend_port、secret_key、db_service（host/port）、
          database（filename）。
    """
    path = os.path.join(CONFIG_DIR, "config.json")
    cfg = {
        "host": "0.0.0.0",
        "frontend_port": 6031,
        "backend_port": 8090,
        "secret_key": "auth_system_secret_key_2026",
        "db_service": {"host": "127.0.0.1", "port": 6070},
        "database": {"filename": "auth.db"},
    }
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        cfg.update({k: v for k, v in loaded.items() if k not in ("db_service", "database")})
        cfg["db_service"].update(loaded.get("db_service") or {})
        cfg["database"].update(loaded.get("database") or {})
    return cfg


# 全局配置总入口
CONFIG = load_config()
# config.json 的绝对路径
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
# 服务监听地址
HOST = CONFIG.get("host") or "0.0.0.0"
# 前端静态页面服务端口：只返回 HTML/CSS/JS
FRONTEND_PORT = int(CONFIG.get("frontend_port") or 6031)
# 后端接口服务端口：所有 /api/* 认证接口
BACKEND_PORT = int(CONFIG.get("backend_port") or 8090)
# 会话签名密钥：前端与后端保持一致（页面服务虽不签发会话，但保持同一份配置便于扩展）
SECRET_KEY = CONFIG.get("secret_key") or "auth_system_secret_key_2026"
# 数据库服务地址：唯一直接访问 SQLite 的进程，本进程通过 HTTP 调用它执行 SQL
DB_SERVICE_HOST = (CONFIG.get("db_service") or {}).get("host") or "127.0.0.1"
DB_SERVICE_PORT = int((CONFIG.get("db_service") or {}).get("port") or 6070)
DB_SERVICE_URL = f"http://{DB_SERVICE_HOST}:{DB_SERVICE_PORT}"
# 单次调用超时（秒）：数据库服务无响应时直接报错，避免请求线程被无限挂住
DB_SERVICE_TIMEOUT = 10
# 内置的初始管理员账号名：由数据库服务首次建库时创建
ROOT_ADMIN_USERNAME = "admin"
# 内置管理员的初始密码：仅在首次建库（users 表中还没有 admin）时使用
ROOT_ADMIN_PASSWORD = "admin123"
# 用户短缓存：页面轮询会频繁查询用户，避免每次请求都打一次 users 表
USER_CACHE_TTL = 3
_user_cache = {}
_user_cache_lock = Lock()


def _load_session_epoch():
    """读取进程间共享的会话代次（会话指纹的一部分）。

    返回：16 字节随机十六进制字符串；各进程读到同一个值，因此互相能校验对方签发的会话。
    说明：值保存在 data/.epoch，文件不存在时自动生成。
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


# 会话代次：删除 data/.epoch 并重启服务即可让所有已登录会话立即失效
SESSION_EPOCH = _load_session_epoch()


# ===== 数据库服务调用（本进程不直连数据库） =====

class DBServiceError(RuntimeError):
    """数据库服务调用失败（服务不可达或 SQL 执行报错）。"""


def _db_request(path, payload=None, method="POST", timeout=DB_SERVICE_TIMEOUT):
    """调用数据库服务的 HTTP 接口。

    参数 path：接口路径（如 /db/session/execute）；参数 payload：请求体字典，GET 时忽略；
    参数 method：HTTP 方法；参数 timeout：超时秒数。
    返回：响应体解析后的字典（已确认 ok 为真）。
    异常：服务不可达或响应 ok 为假时抛 DBServiceError。
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
    """远程游标：对外用法与本地数据库游标一致，实际把 SQL 转发给数据库服务执行。

    服务端一次性返回本次查询的全部结果行，本类在客户端按需 fetchone / fetchall；
    dict_cursor 为 True 时（对应 db_cursor(True)）结果行按列名转成字典，否则保持值序列。
    """

    def __init__(self, dict_mode=False):
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

        参数 sql：SQLite 风格 SQL（使用 ? 占位符）；参数 args：参数元组/列表或 None。
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
        """按 dict_mode 把结果行转成字典或元组。"""
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
    用法：`with db_cursor(True) as cursor:`，块内正常结束自动 commit，抛异常自动 rollback 并继续上抛。
    返回：生成器，yield 出 RemoteCursor 实例（SQL 实际由数据库服务执行）。
    """
    cursor = RemoteCursor(dict_mode=dict_cursor)
    try:
        yield cursor
        # 本次事务没有任何写操作时不必提交，少一次网络往返
        if cursor.wrote and cursor.session_id:
            _db_request("/db/session/commit", {"session_id": cursor.session_id})
    except Exception:
        if cursor.session_id:
            try:
                _db_request("/db/session/rollback", {"session_id": cursor.session_id})
            except Exception:
                pass
        raise
    finally:
        cursor.close()


def init_db():
    """请求数据库服务完成建表与内置管理员初始化（幂等，可重复调用）。

    返回：数据库服务返回的信息字典，含 engine（mysql/sqlite）、host、port、database。
    """
    return _db_request("/db/init", {}, timeout=30)


# ===== 用户数据访问 =====

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
    返回：包含 id、password_hash、role、status、student_id 等字段的字典；未找到返回 None。
    说明：命中短缓存时返回副本，避免调用方改到缓存里的字典。SQL 统一按 MySQL 的 %s 占位符书写，
          SQLite 模式下由数据库服务的 prepare_sql 自动改写。
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


def create_user(username, password, display_name, student_id):
    """新建一个普通成员账号（密码只存 werkzeug 哈希，由调用方传入已哈希值）。"""
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role, status, student_id)
            VALUES (%s, %s, %s, 'member', '启用', %s)
            """,
            (username, password, (display_name or username)[:50], (student_id or "")[:50]),
        )
    invalidate_user_cache(username)


def update_password(user_id, password_hash):
    """按用户 id 更新密码哈希。"""
    with db_cursor() as cursor:
        cursor.execute("UPDATE users SET password_hash=%s WHERE id=%s", (password_hash, user_id))
    invalidate_user_cache()


# ===== 会话工具 =====

def session_signature(user):
    """会话指纹：绑定当前会话代次与账号密码，改密码后旧会话立即失效。

    参数 user：users 表的一行（需含 username 与 password_hash）。
    返回：sha256 十六进制摘要字符串。
    """
    raw = f"{SESSION_EPOCH}:{user['username']}:{user['password_hash']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sign_in(user):
    """登录成功后把用户信息写入会话。

    返回：无。副作用：填充 session（logged_in、user_id、username、display_name、role）并写入指纹 sign。
    """
    session["logged_in"] = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["display_name"] = user.get("display_name") or user["username"]
    session["role"] = user["role"]
    session["sign"] = session_signature(user)


def current_user():
    """取当前会话对应的用户；未登录或会话失效时返回 None 并清空会话。

    返回：用户字典或 None。三类失效情形：账号被删除、账号被停用、指纹不匹配。
    """
    if "logged_in" not in session:
        return None
    user = get_user(session.get("username"))
    if not user or user.get("status") != "启用" or session.get("sign") != session_signature(user):
        session.clear()
        return None
    return user


def login_required(func):
    """接口登录校验装饰器：未登录或会话失效时返回 401 JSON。

    参数 func：被装饰的视图函数。返回：包装后的视图函数。
    副作用：校验通过后回写 session 中的最新 role、display_name、user_id。
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"ok": False, "error": "未登录或登录已失效，请重新登录"}), 401
        session["role"] = user["role"]
        session["display_name"] = user.get("display_name") or user["username"]
        session["user_id"] = user["id"]
        return func(*args, **kwargs)
    return wrapper
