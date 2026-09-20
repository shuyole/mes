# -*- coding: utf-8 -*-
"""系统配置、日志查询、用户管理与探活 API 蓝图。

提供接口：
- GET  /api/config: 前端所需静态配置（产品、工位、工艺、节拍计划、端口）
- GET  /api/ping: 页面会话心跳探活
- GET  /api/logs: 生产操作日志分页查询
- GET  /api/users: 用户账号列表（管理员）
- POST /api/users/<id>: 用户账号启停/重置密码/角色变更/删除（管理员）
"""

from flask import Blueprint, jsonify, request, session
from werkzeug.security import generate_password_hash

import common
from common import (
    BACKEND_PORT,
    FRONTEND_PORT,
    PLAN,
    PROCESS_STEPS,
    PRODUCTS,
    ROOT_ADMIN_USERNAME,
    STATION_DEFS,
    add_log,
    admin_required,
    db_cursor,
    fetch_logs,
    json_safe,
    list_users,
    login_required,
)

system_bp = Blueprint("system", __name__)


@system_bp.route("/api/config")
def api_config():
    """返回前端所需的静态配置数据（无需登录）。

    包括产品列表、工位定义、工艺步骤、节拍计划、端口信息等。

    数据库信息取 common 模块的运行时值：DB_ENGINE 由 init_db() 在启动时探测后写回，
    因此必须用 common.DB_ENGINE 而不是 import 时的快照。只回传主机与库名，不含密码。
    """
    return jsonify({
        "ok": True,
        "products": PRODUCTS,
        "station_defs": STATION_DEFS,
        "process_steps": PROCESS_STEPS,
        "plan": PLAN,
        "frontend_port": FRONTEND_PORT,
        "backend_port": BACKEND_PORT,
        "db_engine": common.DB_ENGINE,
        "db_host": common.DB_CONFIG.get("host"),
        "db_name": common.DB_CONFIG.get("database"),
    })


@system_bp.route("/api/ping")
@login_required
def api_ping():
    """会话探活接口。页面心跳打这里，避免每 5 秒都去查生产日志。"""
    return jsonify({"ok": True})


@system_bp.route("/api/logs")
@login_required
def api_logs():
    """生产日志查询接口（前端定时刷新日志列表）。

    HTTP：GET /api/logs。权限：需登录。
    返回：JSON 数组。?category=line 只返回产线运行日志。
    """
    category = (request.args.get("category") or "").strip() or None
    logs = fetch_logs(category=category, limit=30)
    return jsonify(logs)


@system_bp.route("/api/users", methods=["GET"])
@admin_required
def api_users_list():
    """获取用户列表（管理员）。"""
    users = json_safe(list_users())
    return jsonify({
        "ok": True,
        "users": users,
        "root_admin": ROOT_ADMIN_USERNAME,
    })


@system_bp.route("/api/users/<int:user_id>", methods=["POST"])
@admin_required
def api_users_manage(user_id):
    """用户管理操作（启停、重置密码、改角色、删除）。

    参数 JSON：action（enable/disable/reset/role/delete）、role（仅 action=role 时需要）。
    """
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip()

    with db_cursor(True) as cursor:
        cursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))
        user = cursor.fetchone()
    if not user:
        return jsonify({"ok": False, "error": "账号不存在"}), 404
    if user["username"] == session.get("username"):
        return jsonify({"ok": False, "error": "不能对自己的账号执行该操作"}), 400
    if user["username"] == ROOT_ADMIN_USERNAME and session.get("username") != ROOT_ADMIN_USERNAME:
        return jsonify({"ok": False, "error": f"只有内置管理员 {ROOT_ADMIN_USERNAME} 可以修改这个账号"}), 403

    if action == "disable":
        if user["role"] == "admin":
            return jsonify({"ok": False, "error": "不能停用管理员账号"}), 400
        with db_cursor() as cur:
            cur.execute("UPDATE users SET status='停用' WHERE id=%s", (user_id,))
        add_log(f"停用账号 {user['username']}")
        return jsonify({"ok": True, "message": f"已停用 {user['username']}"})

    if action == "enable":
        with db_cursor() as cur:
            cur.execute("UPDATE users SET status='启用' WHERE id=%s", (user_id,))
        add_log(f"启用账号 {user['username']}")
        return jsonify({"ok": True, "message": f"已启用 {user['username']}"})

    if action == "reset":
        with db_cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash=%s WHERE id=%s",
                (generate_password_hash("123456"), user_id),
            )
        add_log(f"重置账号 {user['username']} 密码")
        return jsonify({"ok": True, "message": f"{user['username']} 密码已重置为 123456"})

    if action == "role":
        new_role = data.get("role")
        if new_role not in ("admin", "member"):
            return jsonify({"ok": False, "error": "无效角色"}), 400
        with db_cursor() as cur:
            cur.execute("UPDATE users SET role=%s WHERE id=%s", (new_role, user_id))
        add_log(f"将 {user['username']} 角色调整为 {new_role}")
        return jsonify({"ok": True, "message": f"{user['username']} 已设为{'管理员' if new_role == 'admin' else '普通成员'}"})

    if action == "delete":
        if user["role"] == "admin" and session.get("username") != ROOT_ADMIN_USERNAME:
            return jsonify({"ok": False, "error": f"只有内置管理员 {ROOT_ADMIN_USERNAME} 可以删除管理员账号"}), 403
        with db_cursor() as cur:
            cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
        add_log(f"删除账号 {user['username']}（{user['role']}）")
        return jsonify({"ok": True, "message": f"已删除账号 {user['username']}"})

    return jsonify({"ok": False, "error": "未知操作"}), 400
