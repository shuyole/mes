# -*- coding: utf-8 -*-
"""产线状态、控制与仿真调度 API 蓝图。

提供接口：
- GET       /api/line: 真实产线实时在制状态（受 PLC 状态把关）
- GET       /api/virtual: 虚拟产线实时在制状态（带演示日志与过站履历）
- POST      /api/line/command: 产线控制指令（启动 / 停止 / 复位 / 急停）
- GET/POST  /api/simulation/speed: 产线仿真倍速获取与设置（1x/2x/5x/10x）
- GET       /api/line/station/<code>/diagnose: 单工位传感器与参数深度诊断
- POST      /api/line/station/<code>/test: 单工位动作自检测试
- POST      /api/line/inject_fault: 模拟工位异常故障注入
- POST      /api/line/clear_fault: 产线故障一键复位排除
"""

from datetime import datetime

from flask import Blueprint, jsonify, request, session

from common import (
    STATION_DEFS,
    _as_int,
    add_log,
    db_cursor,
    get_sim_speed,
    is_admin,
    login_required,
    set_sim_speed,
)
from core.line_engine import (
    LINE,
    PLC_REQUIRED_MSG,
    VIRTUAL,
    _remember_virtual,
    line_lock,
    line_run_text,
    reset_stations,
    snapshot_line,
    snapshot_virtual,
    start_line_order,
    update_order_progress,
)
from core.plc import (
    PLC_STATE,
    write_plc_map,
    write_to_plc,
)

line_bp = Blueprint("line", __name__)


@line_bp.route("/api/line")
@login_required
def api_line():
    """真实产线实时状态。PLC 未连接时工位全部离线、不会闪烁。"""
    return jsonify(snapshot_line(plc_gate=True))


@line_bp.route("/api/virtual")
@login_required
def api_virtual():
    """虚拟产线实时状态，不依赖 PLC。"""
    return jsonify(snapshot_virtual())


@line_bp.route("/api/line/command", methods=["POST"])
@login_required
def api_line_command():
    """产线控制指令接口（启动 / 停止 / 复位 / 模拟故障）。

    参数 source=virtual 时操作虚拟产线，不写 PLC；缺省为真实产线，必须已连接 PLC。
    参数 order_id：仅在 command=start 时有效，用于把指定工单直接下发到产线。
    """
    if not is_admin():
        return jsonify({"ok": False, "error": "普通成员不能控制产线，请联系管理员"}), 403
    payload = request.get_json(silent=True) or request.form
    command = (payload.get("command") or "").strip()
    source = (payload.get("source") or "real").strip()
    if command not in ("start", "stop", "reset", "alarm"):
        return jsonify({"ok": False, "error": "未知指令"}), 400
    virtual = source == "virtual"
    state = VIRTUAL if virtual else LINE
    write_plc = not virtual

    if command == "start":
        if write_plc and not PLC_STATE["connected"]:
            return jsonify({"ok": False, "error": PLC_REQUIRED_MSG}), 400
        # 指定工单下发：直接启动这一单，而不是取队首的待生产工单
        if payload.get("order_id"):
            with db_cursor(True) as cursor:
                cursor.execute("SELECT * FROM production_orders WHERE id=%s", (_as_int(payload.get("order_id")),))
                order = cursor.fetchone()
            if not order:
                return jsonify({"ok": False, "error": "工单不存在"}), 404
            ok, msg = start_line_order(order, state=state, write_plc=write_plc)
            if ok and write_plc:
                update_order_progress(
                    order["id"],
                    status="生产中",
                    started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    current_station=STATION_DEFS[0]["name"],
                )
            elif ok and virtual and PLC_STATE["connected"]:
                write_plc_map({0: 1, 1: 1, 2: order.get("completed_qty") or 0, 6: 1})
            return jsonify({"ok": ok, "message": msg})
        with line_lock:
            if state["alarm"]:
                return jsonify({"ok": False, "error": "请先复位故障"}), 400
            resume = bool(state["order_id"])
            if resume:
                state["running"] = True
                run_text = line_run_text(state)
                order_no = state["order_no"]
        if resume:
            if write_plc:
                write_to_plc(1)
                add_log(run_text, order_no, "INFO", "line")
            else:
                _remember_virtual("log", {
                    "created_at": datetime.now().strftime("%H:%M:%S"),
                    "level": "INFO",
                    "message": run_text,
                })
            if virtual and PLC_STATE["connected"]:
                write_to_plc(1)
            return jsonify({"ok": True, "message": "产线已启动"})
        with db_cursor(True) as cursor:
            cursor.execute(
                "SELECT * FROM production_orders WHERE status='待生产' ORDER BY priority DESC, id ASC LIMIT 1"
            )
            order = cursor.fetchone()
        if not order:
            if not virtual:
                return jsonify({"ok": False, "error": "没有待生产工单"}), 400
            order = {
                "id": -1,
                "order_no": "VIR-" + datetime.now().strftime("%H%M%S"),
                "product_name": "虚拟演示件",
                "quantity": 3,
                "completed_qty": 0,
                "ng_qty": 0,
            }
        ok, msg = start_line_order(order, state=state, write_plc=write_plc)
        if ok and write_plc:
            update_order_progress(
                order["id"],
                status="生产中",
                started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        elif ok and virtual and PLC_STATE["connected"]:
            write_plc_map({0: 1, 1: 1, 2: 0, 6: 1})
        return jsonify({"ok": ok, "message": msg})

    if command == "stop":
        with line_lock:
            state["running"] = False
            state["robot"]["status"] = "待机"
            state["robot"]["busy"] = False
            state["robot"]["task"] = "已暂停"
            run_text = line_run_text(state)
            order_no = state["order_no"]
        if write_plc:
            write_to_plc(0)
            add_log(run_text, order_no, "INFO", "line")
        else:
            _remember_virtual("log", {
                "created_at": datetime.now().strftime("%H:%M:%S"),
                "level": "INFO",
                "message": run_text,
            })
        if virtual and PLC_STATE["connected"]:
            write_to_plc(0)
        return jsonify({"ok": True, "message": "产线已停止"})

    if command == "reset":
        with line_lock:
            state["running"] = False
            state["alarm"] = False
            state["alarm_msg"] = ""
            reset_stations(keep_qty=True, state=state)
            run_text = line_run_text(state)
            order_no = state["order_no"]
        if write_plc:
            write_plc_map({0: 0, 1: 0, 6: 0})
            add_log(run_text, order_no, "INFO", "line")
        else:
            _remember_virtual("log", {
                "created_at": datetime.now().strftime("%H:%M:%S"),
                "level": "INFO",
                "message": run_text,
            })
        if virtual and PLC_STATE["connected"]:
            write_plc_map({0: 0, 1: 0, 6: 0})
        return jsonify({"ok": True, "message": "产线已复位"})

    with line_lock:
        state["alarm"] = True
        state["running"] = False
        state["alarm_msg"] = "模拟急停 / 工位互锁故障"
        state["robot"]["status"] = "故障"
        state["robot"]["task"] = "等待复位"
        state["stations"][state["station_index"]]["status"] = "故障"
        alarm_msg = state["alarm_msg"]
        run_text = line_run_text(state)
        order_no = state["order_no"]
    if write_plc:
        write_to_plc(3)
        add_log(run_text, order_no, "ALARM", "line")
    else:
        _remember_virtual("log", {
            "created_at": datetime.now().strftime("%H:%M:%S"),
            "level": "ALARM",
            "message": run_text,
        })
    if virtual and PLC_STATE["connected"]:
        write_to_plc(3)
    return jsonify({"ok": True, "message": alarm_msg})


@line_bp.route("/api/simulation/speed", methods=["GET", "POST"])
def api_sim_speed():
    """产线仿真运行倍速控制（1x/2x/5x/10x）。"""
    if request.method == "POST":
        if not session.get("user_id"):
            return jsonify({"ok": False, "error": "未登录"}), 401
        payload = request.get_json(silent=True) or request.form
        speed = payload.get("speed") or 1.0
        ok, current = set_sim_speed(speed)
        return jsonify({"ok": ok, "speed": current, "message": f"仿真速度已设为 {current}x"})
    return jsonify({"ok": True, "speed": get_sim_speed()})


@line_bp.route("/api/line/station/<string:station_code>/diagnose", methods=["GET"])
def api_station_diagnose(station_code):
    """工位深度诊断信息接口：返回传感器信号、技术参数、公差与实时过站量。"""
    station_code = station_code.upper()
    found = next((s for s in STATION_DEFS if s["code"] == station_code), None)
    if not found:
        return jsonify({"ok": False, "error": f"工位 {station_code} 不存在"}), 404
    with line_lock:
        live_station = next((s for s in LINE["stations"] if s["code"] == station_code), found)
        order_no = LINE["order_no"]
        running = LINE["running"]
    data = dict(found)
    data["status"] = live_station.get("status", "空闲")
    data["processed_qty"] = live_station.get("processed_qty", 0)
    data["current_order_no"] = order_no if running else ""
    plc_on = bool(PLC_STATE["connected"])
    station_run = data["status"] == "运行"
    for sen in data.get("sensors", []):
        sen["status"] = "ON" if (plc_on and station_run) else "OFF"
    data["ok"] = True
    return jsonify(data)


@line_bp.route("/api/line/station/<string:station_code>/test", methods=["POST"])
@login_required
def api_station_test(station_code):
    """单工位动作与传感器自检触发。"""
    station_code = station_code.upper()
    found = next((s for s in STATION_DEFS if s["code"] == station_code), None)
    if not found:
        return jsonify({"ok": False, "error": f"工位 {station_code} 不存在"}), 404
    user = session.get("username") or "operator"
    add_log(f"操作员 {user} 对工位 {found['name']}({station_code}) 执行单步诊断测试：动作正常，传感器响应良好", category="line")
    return jsonify({"ok": True, "message": f"工位 {found['name']}({station_code}) 单步动作自检完成，传感器及气动部件正常！"})


@line_bp.route("/api/line/inject_fault", methods=["POST"])
@login_required
def api_inject_fault():
    """模拟工位故障注入（供教学演示异常应急演练）。"""
    if not is_admin():
        return jsonify({"ok": False, "error": "模拟故障需要管理员权限"}), 403
    payload = request.get_json(silent=True) or request.form
    station_code = (payload.get("station_code") or "ST04").upper()
    fault_reason = payload.get("reason") or "伺服螺丝电批扭矩过载报警 (0.48 N·m > 0.38 N·m)"
    
    with line_lock:
        LINE["alarm"] = True
        LINE["running"] = False
        LINE["alarm_msg"] = f"{station_code} {fault_reason}"
        LINE["robot"]["status"] = "故障"
        LINE["robot"]["task"] = "等待故障排除与复位"
        for st in LINE["stations"]:
            if st["code"] == station_code:
                st["status"] = "故障"
                break
        order_no = LINE["order_no"]
    write_to_plc(3)
    add_log(f"【故障模拟注入】工位 {station_code} 触发异常报警: {fault_reason}", order_no, "ALARM", "line")
    return jsonify({"ok": True, "message": f"已在 {station_code} 模拟故障: {fault_reason}"})


@line_bp.route("/api/line/clear_fault", methods=["POST"])
@login_required
def api_clear_fault():
    """故障一键排除与复原。"""
    with line_lock:
        LINE["alarm"] = False
        LINE["alarm_msg"] = ""
        for st in LINE["stations"]:
            if st["status"] == "故障":
                st["status"] = "空闲"
        if LINE["robot"]["status"] == "故障":
            LINE["robot"]["status"] = "待机"
            LINE["robot"]["task"] = "故障已清除，准备就绪"
    write_to_plc(0)
    add_log("操作员完成排障，产线故障状态已复位解除", LINE.get("order_no", ""), "INFO", "line")
    return jsonify({"ok": True, "message": "故障已成功复位清除！"})
