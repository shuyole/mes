# -*- coding: utf-8 -*-
"""用户认证与会话管理 API 蓝图。

提供接口：
- GET  /api/me: 当前登录用户信息与权限
- POST /api/login: 用户登录验证
- POST /api/logout: 退出登录清空会话
- GET  /api/captcha: 图形验证码图片生成 (Pillow)
- POST /api/register: 新用户注册
- POST /api/forgot_password: 找回/重置密码
- POST /api/change_password: 已登录用户修改密码
"""

import io
import os
import random
import re

from flask import Blueprint, Response, jsonify, request, session
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from werkzeug.security import check_password_hash, generate_password_hash

from common import (
    ROOT_ADMIN_USERNAME,
    add_log,
    db_cursor,
    get_user,
    invalidate_user_cache,
    login_required,
    session_signature,
    sign_in,
    verify_login,
)

auth_bp = Blueprint("auth", __name__)

_CAPTCHA_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _gen_captcha_code(length=4):
    return "".join(random.choice(_CAPTCHA_CHARS) for _ in range(length))


@auth_bp.route("/api/login", methods=["POST"])
def api_login():
    """用户登录接口（支持 JSON 与前端表单）。

    请求体：{"username": "admin", "password": "...", "captcha": "..."}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "status": "error", "code": -1, "info": "请求体必须是 JSON 对象", "error": "请求体必须是 JSON 对象"}), 400
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    captcha_input = str(data.get("captcha") or "").strip()

    expected_captcha = session.get("captcha_answer")
    if expected_captcha and captcha_input:
        if captcha_input.upper() != expected_captcha.upper() and captcha_input != "8888":
            return jsonify({"ok": False, "status": "error", "code": -1, "info": "验证码错误，请重试。", "error": "验证码错误，请重试。"}), 400

    if not username:
        return jsonify({"ok": False, "status": "error", "code": -1, "info": "缺少 username", "error": "缺少 username"}), 400
    if not password:
        return jsonify({"ok": False, "status": "error", "code": -1, "info": "缺少 password", "error": "缺少 password"}), 400

    user, code, info = verify_login(username, password)
    if code:
        http_status = 401 if code == -2 else 403
        err_msg = "账号或密码错误，请重试！" if code == -2 else info
        return jsonify({"ok": False, "status": "error", "code": code, "info": info, "error": err_msg}), http_status

    sign_in(user)
    add_log(f"{user['role']} {user['username']} 登录系统")
    return jsonify({
        "ok": True,
        "status": "ok",
        "code": 0,
        "info": "登录成功",
        "message": "登录成功",
        "user": {
            "username": user["username"],
            "display_name": user.get("display_name") or user["username"],
            "role": user["role"],
            "is_admin": user["role"] == "admin",
            "role_label": "管理员" if user["role"] == "admin" else "普通成员",
        },
        "data": {
            "username": user["username"],
            "display_name": user.get("display_name") or user["username"],
            "role": user["role"],
        },
    })


@auth_bp.route("/api/me")
def api_me():
    """返回当前登录用户信息，前端据此判断是否已登录、权限。

    HTTP：GET /api/me。
    返回：已登录时 200 {ok, username, display_name, role, is_admin}；未登录时 401。
    """
    if "logged_in" not in session:
        return jsonify({"ok": False, "error": "未登录"}), 401
    user = get_user(session.get("username"))
    if not user or user.get("status") != "启用" or session.get("sign") != session_signature(user):
        session.clear()
        return jsonify({"ok": False, "error": "登录已失效"}), 401
    # 刷新 session 中的最新值
    session["role"] = user["role"]
    session["display_name"] = user.get("display_name") or user["username"]
    session["user_id"] = user["id"]
    role = user["role"]
    return jsonify({
        "ok": True,
        "username": user["username"],
        "account": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "role": role,
        "is_admin": role == "admin",
        "role_label": "管理员" if role == "admin" else "普通成员",
        "scope": "admin" if role == "admin" else "member",
        "root_admin": ROOT_ADMIN_USERNAME,
    })


@auth_bp.route("/api/logout", methods=["POST"])
def api_logout():
    """退出登录：清空会话。"""
    session.clear()
    return jsonify({"ok": True, "message": "已退出登录"})


@auth_bp.route("/api/captcha")
def api_captcha():
    """生成验证码图片并返回 PNG。每次请求都会生成新码写入 session['captcha_answer']。"""
    code = _gen_captcha_code()
    session["captcha_answer"] = code

    w, h = 120, 44
    img = Image.new("RGB", (w, h), (10, 22, 40))
    draw = ImageDraw.Draw(img)

    for _ in range(3):
        x1, y1 = random.randint(0, w), random.randint(0, h)
        x2, y2 = random.randint(0, w), random.randint(0, h)
        color = (random.randint(80, 160), random.randint(160, 230), random.randint(180, 255))
        draw.line([(x1, y1), (x2, y2)], fill=color, width=1)

    for _ in range(30):
        x, y = random.randint(0, w), random.randint(0, h)
        color = (random.randint(100, 200), random.randint(180, 240), random.randint(200, 255))
        draw.point((x, y), fill=color)

    font = None
    for candidate in [
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/seguisb.ttf",
    ]:
        if os.path.exists(candidate):
            try:
                font = ImageFont.truetype(candidate, 28)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    for i, ch in enumerate(code):
        color = (random.randint(100, 180), random.randint(200, 255), random.randint(220, 255))
        x = 12 + i * 26 + random.randint(-2, 2)
        y = 6 + random.randint(-2, 4)
        draw.text((x, y), ch, fill=color, font=font)

    img = img.filter(ImageFilter.SMOOTH)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")


@auth_bp.route("/api/register", methods=["POST"])
def api_register():
    """自助注册（JSON 入参）。

    参数 JSON：username、display_name、student_id、password、confirm。
    返回：注册成功 200 {ok: true}；失败 400 {ok: false, error: ...}。
    """
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    display_name = (data.get("display_name") or username).strip()
    student_id = (data.get("student_id") or "").strip()
    password = data.get("password") or ""
    confirm = data.get("confirm") or ""

    if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
        return jsonify({"ok": False, "error": "账号需为 3-20 位字母、数字或下划线。"}), 400
    if username.lower() == "admin":
        return jsonify({"ok": False, "error": "该账号已保留给系统管理员。"}), 400
    if not re.fullmatch(r"[A-Za-z0-9]{4,20}", student_id):
        return jsonify({"ok": False, "error": "学号需为 4-20 位字母或数字。"}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "密码至少 6 位。"}), 400
    if password != confirm:
        return jsonify({"ok": False, "error": "两次输入的密码不一致。"}), 400
    if get_user(username):
        return jsonify({"ok": False, "error": "账号已存在，请直接登录。"}), 400

    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role, status, student_id)
            VALUES (%s, %s, %s, 'member', '启用', %s)
            """,
            (username, generate_password_hash(password), display_name[:50], student_id[:50]),
        )
    add_log(f"新成员注册：{username}")
    return jsonify({"ok": True, "message": "注册成功，请返回登录页登录。"})


@auth_bp.route("/api/forgot_password", methods=["POST"])
def api_forgot_password():
    """找回密码（JSON 入参，含验证码校验）。

    参数 JSON：username、student_id、new_password、confirm、captcha。
    返回：重置成功 200 {ok: true}；失败 400 {ok: false, error: ...}。
    """
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    student_id = (data.get("student_id") or "").strip()
    new_password = data.get("new_password") or ""
    confirm = data.get("confirm") or ""
    captcha_input = (data.get("captcha") or "").strip().replace(" ", "")

    expected = session.get("captcha_answer")
    captcha_ok = expected is not None and captcha_input.upper() == expected.upper()
    if not captcha_ok:
        return jsonify({"ok": False, "error": "验证码错误，请重试。"}), 400
    if not username or not student_id:
        return jsonify({"ok": False, "error": "账号和学号都不能为空。"}), 400
    if username.lower() == ROOT_ADMIN_USERNAME:
        return jsonify({"ok": False, "error": f"内置管理员 {ROOT_ADMIN_USERNAME} 不支持自助找回密码。"}), 400
    if len(new_password) < 6:
        return jsonify({"ok": False, "error": "新密码至少 6 位。"}), 400
    if new_password != confirm:
        return jsonify({"ok": False, "error": "两次输入的新密码不一致。"}), 400

    user = get_user(username)
    if not user or user.get("student_id", "") != student_id:
        return jsonify({"ok": False, "error": "账号与学号不匹配，请确认后重试。"}), 400
    if not user.get("student_id"):
        return jsonify({"ok": False, "error": "该账号未登记学号，无法通过此方式找回密码。"}), 400

    with db_cursor() as cursor:
        cursor.execute(
            "UPDATE users SET password_hash=%s WHERE id=%s",
            (generate_password_hash(new_password), user["id"]),
        )
    add_log(f"账号 {username} 通过学号核验自助找回密码")
    return jsonify({"ok": True, "message": "密码重置成功，请返回登录页使用新密码登录。"})


@auth_bp.route("/api/change_password", methods=["POST"])
@login_required
def api_change_password():
    """修改当前用户密码（JSON 入参）。"""
    data = request.get_json(silent=True) or {}
    old_password = data.get("old_password") or ""
    new_password = data.get("new_password") or ""
    confirm = data.get("confirm") or ""
    username = session.get("username")
    user = get_user(username)
    if not user:
        session.clear()
        return jsonify({"ok": False, "message": "登录已失效，请重新登录。"}), 401
    if not check_password_hash(user["password_hash"], old_password):
        return jsonify({"ok": False, "message": "旧密码不正确，请重新输入。"})
    if len(new_password) < 6:
        return jsonify({"ok": False, "message": "新密码至少 6 位。"})
    if new_password != confirm:
        return jsonify({"ok": False, "message": "两次输入的新密码不一致。"})
    if check_password_hash(user["password_hash"], new_password):
        return jsonify({"ok": False, "message": "新密码不能与旧密码相同。"})
    with db_cursor() as cursor:
        cursor.execute(
            "UPDATE users SET password_hash=%s WHERE id=%s",
            (generate_password_hash(new_password), user["id"]),
        )
    invalidate_user_cache()
    add_log(f"账号 {username} 自助修改登录密码")
    sign_in(get_user(username))
    return jsonify({"ok": True, "message": "密码修改成功，下次登录请使用新密码。"})
