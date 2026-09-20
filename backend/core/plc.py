# -*- coding: utf-8 -*-
"""Modbus TCP 硬件通讯驱动与 PLC 状态管理模块。

职责：
1. 维护与 PLC 的 Modbus TCP 客户端连接池及互斥锁 (plc_lock)；
2. 保持全局 PLC_STATE 缓存（连接状态、最近读写值、时间、累计读写计数、寄存器快照）；
3. 提供统一的寄存器读写接口（read_from_plc, write_to_plc, write_plc_map）；
4. 提供后台常驻的 poll_plc_status 轮询保活线程；
5. PLC 通讯地址动态配置与持久化（apply_plc_address, save_config）。
"""

from datetime import datetime
from threading import Lock
import json
import logging
import time

from flask import session
from pymodbus.client import ModbusTcpClient

from common import (
    CONFIG,
    CONFIG_PATH,
    PLC_CONFIG,
    add_log,
)
import virtual_plc_manager

logging.getLogger("pymodbus").setLevel(logging.CRITICAL)

# PLC 通讯互斥锁：Modbus 客户端非线程安全，保证同一时刻只有一个线程在读/写 PLC
plc_lock = Lock()

# PLC 连接失败后的重试冷却秒数，避免离线时每个节拍都阻塞在 connect 上
PLC_RETRY_COOLDOWN = 5

# PLC 运行时状态缓存，由 read_from_plc / write_plc_map 与 poll_plc_status 轮询线程共同维护，供 HMI 页面与 /api/plc_status 展示
# 字段：connected 连接状态 / last_read_value|last_read_time 最近读值与时间 / last_write_value|last_write_time 最近写值与时间
#      error_msg 最近一次错误描述 / total_reads|total_writes 累计读写次数 / registers 寄存器地址->值 的最近快照
#      last_fail_ts 最近一次失败时间戳，用于失败后 5 秒内不再重试连接，避免 PLC 离线时反复阻塞
PLC_STATE = {
    "connected": False,
    "last_read_value": None,
    "last_read_time": None,
    "last_write_value": None,
    "last_write_time": None,
    "error_msg": "尚未连接",
    "total_reads": 0,
    "total_writes": 0,
    "registers": {},
    "last_fail_ts": 0,
}


def save_config():
    """把当前 CONFIG 写回 config.json，重启后连接地址仍然有效。"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(CONFIG, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def apply_plc_address(ip, port, reconnect=True):
    """更新 PLC 目标地址，写入 config.json；reconnect 为真时立即断开并按新地址重连。

    返回：(True, 提示文案) 或 (False, 错误原因)。
    """
    ip = str(ip or "").strip()
    if not ip:
        return False, "请填写 PLC IP"
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False, "端口必须是数字"
    if not (1 <= port <= 65535):
        return False, "端口范围 1–65535"
    PLC_CONFIG["ip"] = ip
    PLC_CONFIG["port"] = port
    CONFIG.setdefault("plc", {})["ip"] = ip
    CONFIG["plc"]["port"] = port
    save_config()
    # 切换 IP 时自动管理虚拟 PLC 子进程：
    # 127.0.0.1/localhost/0.0.0.0 → 起 virtual_plc.py；其他地址 → 停掉子进程（连真实 PLC）
    virtual_plc_manager.ensure_virtual_plc_for_ip(ip)
    if reconnect:
        with plc_lock:
            PLC_STATE["connected"] = False
            PLC_STATE["last_fail_ts"] = 0
            PLC_STATE["error_msg"] = "地址已更新，正在重连"
            PLC_STATE["registers"] = {}
        add_log(f"管理员 {session.get('username') or ''} 更新 PLC 地址并重连 {ip}:{port}")
        return True, f"已保存并开始连接 {ip}:{port}"
    add_log(f"管理员 {session.get('username') or ''} 保存 PLC 地址 {ip}:{port}")
    return True, f"已保存 {ip}:{port}，重启后仍然有效"


def _modbus_read(client, address, count=1):
    """读取保持寄存器的兼容封装。

    参数 client：ModbusTcpClient 实例；参数 address：起始寄存器地址；参数 count：读取寄存器个数。
    返回：pymodbus 的读结果对象（是否成功由调用方判断 isError()）。
    说明：不同 pymodbus 版本的从站参数名不一致（有的用 slave，有的关键字不匹配），这里按写法逐个尝试。
    """
    for kwargs in (
        {"address": address, "count": count},
        {"address": address, "count": count, "slave": 1},
    ):
        try:
            return client.read_holding_registers(**kwargs)
        except TypeError:
            # 参数签名不匹配（版本差异），换下一种写法重试
            continue
    return client.read_holding_registers(address, count)


def _modbus_write(client, address, value):
    """写单个保持寄存器的兼容封装。

    参数 client：ModbusTcpClient 实例；参数 address：寄存器地址；参数 value：写入值（内部转 int）。
    返回：pymodbus 的写结果对象。参数名在不同版本间有差异，故用 try/except 兼容两种调用方式。
    """
    try:
        return client.write_register(address=address, value=int(value))
    except TypeError:
        return client.write_register(address, int(value))


def plc_client():
    """创建一个新的 Modbus TCP 客户端（不建立连接）。

    返回：ModbusTcpClient 对象。每次读写都新建客户端，避免长连接被对端断开后残留旧状态。
    """
    return ModbusTcpClient(PLC_CONFIG["ip"], port=int(PLC_CONFIG["port"]))


def _plc_in_cooldown():
    """刚连接失败过则暂缓重试，避免离线时每个请求都卡在 TCP 超时上。"""
    return (not PLC_STATE["connected"]) and (
        time.time() - PLC_STATE.get("last_fail_ts", 0) < PLC_RETRY_COOLDOWN
    )


def _mark_plc_disconnected(message):
    """把 PLC_STATE 标为断开并记下失败时间。调用方需已持有 plc_lock。"""
    PLC_STATE["connected"] = False
    PLC_STATE["last_fail_ts"] = time.time()
    PLC_STATE["error_msg"] = message


def _close_modbus(client):
    """关闭 Modbus 客户端，忽略关闭过程中的异常，避免掩盖真正的读写错误。"""
    if client is None:
        return
    try:
        client.close()
    except Exception:
        pass


def write_plc_map(values):
    """批量写 PLC 保持寄存器，并同步维护全局 PLC_STATE。

    参数 values：寄存器地址 -> 数值 的字典，一次连接把多个地址写完，减少连接开销。
    返回：True 表示全部写入成功；False 表示未连接、处于失败冷却期或写入过程中出错。
    副作用：修改 PLC_STATE（连接状态、最近写值/时间、累计写次数、错误信息）；全程持有 plc_lock。
    """
    if not values:
        return False
    if _plc_in_cooldown():
        return False
    with plc_lock:
        client = None
        try:
            client = plc_client()
            if not client.connect():
                _mark_plc_disconnected(f"无法连接到 PLC ({PLC_CONFIG['ip']}:{PLC_CONFIG['port']})")
                return False
            last_value = None
            for address, value in values.items():
                _modbus_write(client, address, value)
                last_value = value
            PLC_STATE["last_write_value"] = last_value
            PLC_STATE["last_write_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            PLC_STATE["total_writes"] += len(values)
            PLC_STATE["error_msg"] = "正常"
            PLC_STATE["connected"] = True
            return True
        except Exception as exc:
            _mark_plc_disconnected(str(exc))
            print(f"PLC 写入失败: {exc}")
            return False
        finally:
            _close_modbus(client)


def write_to_plc(value, address=0):
    """写单个 PLC 寄存器（write_plc_map 的便捷封装）。

    参数 value：写入值；参数 address：寄存器地址，默认 0（0 号寄存器约定为产线启停命令）。
    返回：True/False，含义同 write_plc_map。
    """
    return write_plc_map({address: value})


def read_from_plc(address=0, count=1):
    """读 PLC 保持寄存器并把结果同步到全局 PLC_STATE。

    参数 address：起始寄存器地址（默认 0）；参数 count：读取的寄存器个数（默认 1）。
    返回：count 为 1 时返回单个寄存器值，count 大于 1 时返回寄存器值列表；
          处于失败冷却期、连接失败或 Modbus 返回错误时返回 None。
    副作用：修改 PLC_STATE（连接状态、最近读值/时间、累计读次数、registers 快照、错误信息）；读取过程持有 plc_lock。
    """
    if _plc_in_cooldown():
        return None
    with plc_lock:
        client = None
        try:
            client = plc_client()
            if not client.connect():
                _mark_plc_disconnected(f"无法连接到 PLC ({PLC_CONFIG['ip']}:{PLC_CONFIG['port']})")
                return None
            result = _modbus_read(client, address, count)
            if result and not result.isError():
                registers = result.registers
                PLC_STATE["connected"] = True
                PLC_STATE["last_read_value"] = registers[0]
                PLC_STATE["last_read_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                PLC_STATE["total_reads"] += 1
                PLC_STATE["error_msg"] = "正常"
                for idx, val in enumerate(registers):
                    PLC_STATE["registers"][str(address + idx)] = val
                return registers[0] if count == 1 else registers
            PLC_STATE["error_msg"] = "Modbus 读取错误"
        except Exception as exc:
            _mark_plc_disconnected(str(exc))
        finally:
            _close_modbus(client)
        return None


def poll_plc_status():
    """PLC 状态轮询线程主体（后台守护线程，常驻）。

    返回：无（while True 不会正常退出）。
    作用：每 2 秒读一次 0~7 号寄存器，刷新 PLC_STATE 供 HMI 页面和 /api/plc_status 展示，
    避免每个 HTTP 轮询都去连一次 PLC。同时监视 HR0 的边沿变化，把 HMI/上位机对
    HR0（0停止 1运行 3故障）的写入反向作用到虚拟产线，实现寄存器↔产线双向联动。
    """
    while True:
        read_from_plc(0, 8)
        if PLC_STATE["connected"]:
            from core.line_engine import apply_plc_register_control
            apply_plc_register_control(PLC_STATE["registers"])
        time.sleep(2)
