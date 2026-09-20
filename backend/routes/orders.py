# -*- coding: utf-8 -*-
"""生产工单管理与排产调度 API 蓝图。

提供接口：
- GET    /api/orders: 工单列表与排产总览统计
- POST   /api/orders: 创建新生产工单
- DELETE /api/orders/<id>: 删除指定工单
- POST   /api/orders/<id>/dispatch: 下发工单到产线投产
- POST   /api/orders/<id>/progress: 手动调整工单完成数/状态
- POST   /api/demo/seed_orders: 一键生成教学示范工单数据
"""

from datetime import date, datetime

from flask import Blueprint, jsonify, request, session

from common import (
    PRODUCTS,
    STATION_DEFS,
    _as_int,
    add_log,
    db_cursor,
    is_admin,
    json_safe,
    login_required,
    next_order_no,
    order_stats,
)
from core.line_engine import (
    LINE,
    ORDER_STATUSES,
    apply_manual_progress,
    line_lock,
    start_line_order,
    update_order_progress,
)
from core.plc import PLC_STATE

orders_bp = Blueprint("orders", __name__)


@orders_bp.route("/api/orders", methods=["GET"])
@login_required
def api_orders_list():
    """获取工单列表与统计数据。

    HTTP：GET /api/orders。权限：需登录。
    返回：JSON {ok, orders, stats, default_order_no, today, products}。
    """
    stats = order_stats()
    orders = json_safe(stats.pop("orders", []))
    return jsonify({
        "ok": True,
        "orders": orders,
        "default_order_no": next_order_no(),
        "today": date.today().isoformat(),
        "products": PRODUCTS,
        **stats,
    })


@orders_bp.route("/api/orders", methods=["POST"])
@login_required
def api_orders_create():
    """创建新工单（JSON 入参）。

    参数 JSON：product_code、quantity、priority、due_date、remark、order_no。
    返回：创建成功 200 {ok: true}。
    """
    data = request.get_json(silent=True) or {}
    product_code = data.get("product_code") or "WC-10W"
    product = next((item for item in PRODUCTS if item["code"] == product_code), PRODUCTS[0])
    try:
        quantity = int(data.get("quantity") or 0)
        priority = int(data.get("priority") or 1)
    except (TypeError, ValueError):
        quantity = 0
        priority = 1
    due_date = data.get("due_date") or None
    remark = data.get("remark") or ""
    order_no = data.get("order_no") or next_order_no()
    if quantity <= 0:
        return jsonify({"ok": False, "error": "数量必须大于 0"}), 400
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO production_orders
            (order_no, product_name, product_code, quantity, priority, due_date, remark, status, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, '待生产', %s)
            """,
            (
                order_no,
                product["name"],
                product["code"],
                quantity,
                priority,
                due_date,
                remark,
                session.get("username") or "",
            ),
        )
    add_log(f"{session.get('username')} 新建工单 {order_no}，产品 {product['name']} x {quantity}", order_no)
    return jsonify({"ok": True, "message": f"工单 {order_no} 创建成功", "order_no": order_no})


@orders_bp.route("/api/orders/<int:order_id>", methods=["DELETE"])
@login_required
def api_orders_delete(order_id):
    """删除工单。"""
    with line_lock:
        if LINE["order_id"] == order_id and LINE["running"]:
            return jsonify({"ok": False, "error": "该工单正在产线上执行，不能删除"}), 400
    with db_cursor() as cursor:
        cursor.execute("DELETE FROM production_orders WHERE id=%s", (order_id,))
    add_log(f"删除工单 ID={order_id}")
    return jsonify({"ok": True, "message": "工单已删除"})


@orders_bp.route("/api/orders/<int:order_id>/dispatch", methods=["POST"])
@login_required
def api_orders_dispatch(order_id):
    """下发工单到产线（管理员）。"""
    if not is_admin():
        return jsonify({"ok": False, "error": "普通成员不能下发产线"}), 403
    with db_cursor(True) as cursor:
        cursor.execute("SELECT * FROM production_orders WHERE id=%s", (order_id,))
        order = cursor.fetchone()
    if not order:
        return jsonify({"ok": False, "error": "工单不存在"}), 404
    ok, msg = start_line_order(order, state=LINE, write_plc=PLC_STATE["connected"])
    if ok and PLC_STATE["connected"]:
        update_order_progress(
            order["id"],
            status="生产中",
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            current_station=STATION_DEFS[0]["name"],
        )
    return jsonify({"ok": ok, "message": msg})


@orders_bp.route("/api/orders/<int:order_id>/progress", methods=["POST"])
@login_required
def api_order_progress(order_id):
    """手动调整工单完成数 / 状态，供排产队列进度条拖拽、加减和状态切换。

    HTTP：POST /api/orders/<id>/progress。权限：需登录。
    参数 JSON：completed_qty 绝对完成数、delta 相对增减、progress 百分比、status 状态文案。
    返回：工单当前进度 JSON。非法状态 400，工单不存在 404。
    """
    payload = request.get_json(silent=True) or {}
    with db_cursor(True) as cursor:
        cursor.execute("SELECT * FROM production_orders WHERE id=%s", (order_id,))
        order = cursor.fetchone()
    if not order:
        return jsonify({"ok": False, "error": "工单不存在"}), 404

    new_status = (payload.get("status") or "").strip() or None
    if new_status and new_status not in ORDER_STATUSES:
        return jsonify({"ok": False, "error": "状态无效"}), 400

    qty_changed = False
    done = None
    pct = None
    if "completed_qty" in payload and payload.get("completed_qty") is not None:
        try:
            done = int(payload.get("completed_qty"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "完成数无效"}), 400
        qty_changed = True
    elif "delta" in payload and payload.get("delta") is not None:
        try:
            done = _as_int(order.get("completed_qty")) + int(payload.get("delta"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "增减值无效"}), 400
        qty_changed = True
    elif "progress" in payload and payload.get("progress") is not None:
        try:
            pct = min(max(int(payload.get("progress")), 0), 100)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "进度无效"}), 400

    try:
        view = apply_manual_progress(
            order,
            completed_qty=done if qty_changed else None,
            new_status=new_status,
            rework_qty=payload.get("rework_qty"),
            progress=pct,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    add_log(
        f"{session.get('username')} 手动调整工单 {view['order_no']} "
        f"{view['completed_qty']}/{view['quantity']}（{view['status']}）",
        view["order_no"],
    )
    view["ok"] = True
    view["message"] = (
        f"已安排返工 {view['completed_qty']}/{view['quantity']}"
        if view["status"] == "返工"
        else "进度已更新"
    )
    return jsonify(view)


@orders_bp.route("/api/demo/seed_orders", methods=["POST"])
@login_required
def api_seed_orders():
    """一键生成标准化教学与演示排产工单。"""
    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%H%M%S")
    seeds = [
        {"order_no": f"DEMO-WC15-{ts}", "product_code": "WC-15W", "product_name": "15W智能车载无线充电器", "quantity": 8, "priority": 2, "due_date": today, "remark": "【教学示范】智能车载无线充批次"},
        {"order_no": f"DEMO-MAG-{ts}", "product_code": "WC-MAG", "product_name": "15W磁吸超薄无线充模块", "quantity": 12, "priority": 3, "due_date": today, "remark": "【加急订单】MagSafe磁吸快充模块"},
        {"order_no": f"DEMO-PAD-{ts}", "product_code": "WC-PAD", "product_name": "20W三线圈无线充工作垫", "quantity": 5, "priority": 1, "due_date": today, "remark": "【常规批次】多设备三线圈旗舰板"},
    ]
    created = []
    with db_cursor(True) as cursor:
        for item in seeds:
            cursor.execute(
                """
                INSERT INTO production_orders (order_no, product_name, product_code, quantity, priority, due_date, status, remark)
                VALUES (%s, %s, %s, %s, %s, %s, '待生产', %s)
                """,
                (item["order_no"], item["product_name"], item["product_code"], item["quantity"], item["priority"], item["due_date"], item["remark"])
            )
            created.append(item["order_no"])
    user = session.get("username") or "operator"
    add_log(f"操作员 {user} 快速生成了 3 笔标准示范排产工单: {', '.join(created)}")
    return jsonify({"ok": True, "count": len(created), "orders": created, "message": f"成功生成 {len(created)} 笔标准演示排产工单！"})
