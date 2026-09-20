# -*- coding: utf-8 -*-
"""设备监控与 SCADA 控制 API 蓝图。

提供接口：
- GET  /api/plc_status: PLC 运行状态与产线联动快照
- POST /api/plc/write: 手动写 PLC 寄存器 (管理员调试)
- POST /api/plc/config: 修改 PLC 通讯 IP/端口并重连
- GET  /api/station_st01: ST01 自动上料工作站专用监控数据
"""

from flask import Blueprint, jsonify, request

from common import (
    PLC_CONFIG,
    STATION_DEFS,
    is_admin,
    login_required,
)
from core.line_engine import (
    LINE,
    VIRTUAL,
    line_lock,
    snapshot_line,
)
from core.plc import (
    PLC_STATE,
    apply_plc_address,
    write_to_plc,
)

scada_bp = Blueprint("scada", __name__)


@scada_bp.route("/api/plc_status")
@login_required
def api_plc_status():
    """PLC 与产线状态查询接口（HMI 页面定时轮询此接口）。

    HTTP：GET /api/plc_status。权限：需登录。
    返回：JSON 对象，包含 PLC_STATE 的全部字段 + 产线快照字段 + ip / port。
    说明：寄存器快照由后台 poll_plc_status 线程刷新，接口本身不再同步读 PLC。
    """
    data = dict(PLC_STATE)
    data["registers"] = dict(PLC_STATE.get("registers") or {})
    line_snap = snapshot_line(plc_gate=True)
    if line_snap.get("plc_connected") and not line_snap.get("running") and not line_snap.get("order_id"):
        virt = snapshot_line(VIRTUAL, plc_gate=False)
        line_snap["running"] = virt.get("running", False)
        line_snap["alarm"] = virt.get("alarm", False)
        line_snap["order_no"] = virt.get("order_no") or line_snap.get("order_no")
        line_snap["robot"] = virt.get("robot") or line_snap.get("robot")
        if virt.get("alarm_msg"):
            line_snap["alarm_msg"] = virt["alarm_msg"]
    data.update(line_snap)
    data["ip"] = PLC_CONFIG["ip"]
    data["port"] = PLC_CONFIG["port"]
    return jsonify(data)


@scada_bp.route("/api/plc/write", methods=["POST"])
@login_required
def api_plc_write():
    """手动写 PLC 寄存器接口（HMI 页面调试用）。

    HTTP：POST /api/plc/write。权限：需登录且必须是管理员。
    参数：JSON 请求体或表单字段 address（寄存器地址）、value（写入值），均按 int 解析。
    返回：JSON {"ok": bool, "error": null|具体错误信息}。
    """
    if not is_admin():
        return jsonify({"ok": False, "error": "普通成员不能写入 PLC 寄存器"}), 403
    payload = request.get_json(silent=True) or request.form
    address = int(payload.get("address") or 0)
    value = int(payload.get("value") or 0)
    ok = write_to_plc(value, address=address)
    return jsonify({"ok": ok, "error": None if ok else PLC_STATE["error_msg"]})


@scada_bp.route("/api/plc/config", methods=["POST"])
@login_required
def api_plc_config():
    """修改 PLC 连接地址（IP / 端口），写入内存并保存到 config.json。"""
    if not is_admin():
        return jsonify({"ok": False, "error": "普通成员不能修改 PLC 地址"}), 403
    payload = request.get_json(silent=True) or request.form
    reconnect = str(payload.get("reconnect", "1")).lower() not in ("0", "false", "no")
    ok, msg = apply_plc_address(payload.get("ip"), payload.get("port"), reconnect=reconnect)
    return jsonify({
        "ok": ok,
        "message": msg if ok else None,
        "error": None if ok else msg,
        "ip": PLC_CONFIG["ip"],
        "port": PLC_CONFIG["port"],
    }), (200 if ok else 400)


@scada_bp.route("/api/station_st01")
@login_required
def api_station_st01():
    """ST01 自动上料工作站专用监控接口。

    返回：
      - PLC 连接状态、寄存器实时值（地址 10~17 对应 ST01）
      - ST01 工位静态定义（传感器、参数、工艺描述）
      - 实时工位状态（运行/空闲/故障）与累计过站量
      - 产线全局状态（running / alarm / order_no）
    """
    st01 = next((s for s in STATION_DEFS if s["code"] == "ST01"), None)
    if not st01:
        return jsonify({"ok": False, "error": "ST01 工位定义缺失"}), 500

    with line_lock:
        live_station = next((s for s in LINE["stations"] if s["code"] == "ST01"), st01)
        line_running = LINE["running"]
        line_alarm = LINE["alarm"]
        line_order_no = LINE["order_no"]

    regs = PLC_STATE.get("registers") or {}
    st01_regs = {}
    for addr in range(10, 18):
        st01_regs[f"HR{addr:02d}"] = regs.get(addr, "--")

    plc_on = bool(PLC_STATE["connected"])
    station_run = live_station.get("status") == "运行"

    sensors = []
    for sen in st01.get("sensors", []):
        s = dict(sen)
        s["status"] = "ON" if (plc_on and station_run) else "OFF"
        sensors.append(s)

    return jsonify({
        "ok": True,
        "station": {
            "code": st01["code"],
            "name": st01["name"],
            "full_name": st01["full_name"],
            "desc": st01.get("desc", ""),
            "role": st01.get("role", "上料"),
            "cycle_sec": st01.get("cycle_sec", 3),
            "plc_address": st01.get("plc_address", 10),
        },
        "status": live_station.get("status", "空闲"),
        "processed_qty": live_station.get("processed_qty", 0),
        "sensors": sensors,
        "params": st01.get("params", []),
        "qc_criteria": st01.get("qc_criteria", ""),
        "registers": st01_regs,
        "plc": {
            "connected": plc_on,
            "ip": PLC_CONFIG["ip"],
            "port": PLC_CONFIG["port"],
            "error_msg": PLC_STATE.get("error_msg", ""),
            "last_read_time": PLC_STATE.get("last_read_time"),
        },
        "line": {
            "running": line_running,
            "alarm": line_alarm,
            "order_no": line_order_no,
        },
    })
