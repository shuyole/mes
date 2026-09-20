# -*- coding: utf-8 -*-
"""品质追溯、生产统计与报表导出 API 蓝图。

提供接口：
- GET /api/production: 生产数据（趋势、工位统计、过站记录、工单列表）
- GET /api/stats: 总览统计指标（工单数字 + 产线快照 + PLC 摘要）
- GET /api/export/orders: 导出排产工单报表 (CSV 格式)
- GET /api/export/trace: 导出工位过站质量追溯链报表 (CSV 格式)
"""

from datetime import datetime
import csv
import io

from flask import Blueprint, Response, jsonify

from common import (
    db_cursor,
    get_sim_speed,
    json_safe,
    login_required,
    order_stats,
)
from core.line_engine import snapshot_line
from core.plc import PLC_STATE

production_bp = Blueprint("production", __name__)


@production_bp.route("/api/production")
@login_required
def api_production():
    """生产统计数据（趋势、工位统计、作业记录、工单列表）。"""
    stats = order_stats()
    orders = json_safe(stats.pop("orders", []))
    with db_cursor(True) as cursor:
        cursor.execute("SELECT * FROM work_records ORDER BY id DESC LIMIT 40")
        records = json_safe(cursor.fetchall())
        cursor.execute(
            """
            SELECT DATE(created_at) AS day,
                   SUM(quantity) AS planned,
                   SUM(completed_qty) AS completed,
                   SUM(ng_qty) AS ng_qty
            FROM production_orders
            WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
            GROUP BY DATE(created_at)
            ORDER BY day
            """
        )
        trend = json_safe(cursor.fetchall())
        cursor.execute(
            """
            SELECT station_name, SUM(ok_qty) AS ok_qty, SUM(ng_qty) AS ng_qty
            FROM work_records
            GROUP BY station_name
            ORDER BY station_name
            """
        )
        station_stats = json_safe(cursor.fetchall())
    return jsonify({
        "ok": True,
        "orders": orders,
        "records": records,
        "trend": trend,
        "station_stats": station_stats,
        **stats,
    })


@production_bp.route("/api/stats")
@login_required
def api_stats():
    """总览统计接口：工单统计 + 产线快照 + PLC 摘要。"""
    stats = order_stats(include_orders=False)
    stats.pop("orders", None)
    stats["line"] = snapshot_line(plc_gate=True)
    stats["plc"] = {
        "connected": PLC_STATE["connected"],
        "error_msg": PLC_STATE["error_msg"],
        "last_read_value": PLC_STATE["last_read_value"],
    }
    stats["sim_speed"] = get_sim_speed()
    return jsonify(stats)


@production_bp.route("/api/export/orders")
@login_required
def api_export_orders():
    """导出排产工单报表 (CSV 格式，Excel 友好)。"""
    with db_cursor(True) as cursor:
        cursor.execute("SELECT * FROM production_orders ORDER BY id DESC")
        rows = cursor.fetchall()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["工单ID", "工单编号", "产品编码", "产品名称", "计划数量", "完成合格数", "不良数", "优先级", "工单状态", "当前工位", "交货日期", "创建时间"])
    for r in rows:
        pri = "紧急" if r.get("priority") == 3 else ("加急" if r.get("priority") == 2 else "普通")
        writer.writerow([
            r.get("id"),
            r.get("order_no"),
            r.get("product_code") or "",
            r.get("product_name") or "",
            r.get("quantity") or 0,
            r.get("completed_qty") or 0,
            r.get("ng_qty") or 0,
            pri,
            r.get("status") or "",
            r.get("current_station") or "",
            r.get("due_date") or "",
            r.get("created_at") or "",
        ])
    output.seek(0)
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=mes_orders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
    )


@production_bp.route("/api/export/trace")
@login_required
def api_export_trace():
    """导出生产工位过站质量追溯链报表 (CSV 格式)。"""
    with db_cursor(True) as cursor:
        cursor.execute("SELECT * FROM work_records ORDER BY id DESC LIMIT 500")
        rows = cursor.fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["记录ID", "工单编号", "工位编号", "工位名称", "合格数", "不良数", "判定结果", "过站时间"])
    for r in rows:
        writer.writerow([
            r.get("id"),
            r.get("order_no") or "",
            r.get("station_code") or "",
            r.get("station_name") or "",
            r.get("ok_qty") or 0,
            r.get("ng_qty") or 0,
            r.get("status") or "",
            r.get("created_at") or "",
        ])
    output.seek(0)
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=mes_trace_records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
    )
