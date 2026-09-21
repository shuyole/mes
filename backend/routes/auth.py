# -*- coding: utf-8 -*-
import io
import random
from flask import Blueprint, Response, jsonify, request
from PIL import Image, ImageDraw, ImageFont
from werkzeug.security import check_password_hash, generate_password_hash
from common import get_user, create_user, update_password

auth_bp = Blueprint("auth", __name__)

# 保存最新生成的验证码字符
CURRENT_CAPTCHA = ""


# 图形验证码接口
@auth_bp.route("/api/captcha")
def captcha():
    global CURRENT_CAPTCHA
    chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    code = "".join(random.sample(chars, 4))
    CURRENT_CAPTCHA = code

    img = Image.new("RGB", (120, 44), (20, 30, 50))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("arial.ttf", 26)
    except Exception:
        font = ImageFont.load_default()

    for i, ch in enumerate(code):
        draw.text((16 + i * 24, 8), ch, fill=(34, 211, 238), font=font)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Response(buf.getvalue(), mimetype="image/png")


# 用户登录接口
@auth_bp.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    code = data.get("captcha", "").strip()

    # 核对验证码（忽略大小写）
    if CURRENT_CAPTCHA and code.upper() != CURRENT_CAPTCHA.upper():
        return jsonify({"ok": False, "error": "验证码错误"}), 400

    if not username or not password:
        return jsonify({"ok": False, "error": "用户名和密码不能为空"}), 400

    user = get_user(username)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"ok": False, "error": "账号或密码错误"}), 401

    if user.get("status") != "启用":
        return jsonify({"ok": False, "error": "账号已被停用"}), 403

    # 前后端分离：直接把用户信息返回给前端保存
    return jsonify({
        "ok": True,
        "message": "登录成功",
        "user": {
            "username": user["username"],
            "display_name": user.get("display_name") or user["username"],
            "role": user.get("role", "member"),
            "role_label": "管理员" if user.get("role") == "admin" else "普通成员"
        }
    })


# 查询用户信息
@auth_bp.route("/api/me")
def me():
    username = request.args.get("username", "").strip()
    if not username:
        return jsonify({"ok": False, "error": "未提供用户名"}), 400

    user = get_user(username)
    if not user:
        return jsonify({"ok": False, "error": "用户不存在"}), 404

    return jsonify({
        "ok": True,
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "role": user.get("role", "member"),
        "role_label": "管理员" if user.get("role") == "admin" else "普通成员"
    })


# 退出登录
@auth_bp.route("/api/logout", methods=["POST"])
def logout():
    return jsonify({"ok": True, "message": "退出成功"})


# 注册新用户
@auth_bp.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    confirm = data.get("confirm", "")
    display_name = data.get("display_name", "").strip()
    student_id = data.get("student_id", "").strip()

    if not username or not password:
        return jsonify({"ok": False, "error": "账号和密码不能为空"}), 400

    if password != confirm:
        return jsonify({"ok": False, "error": "两次密码不一致"}), 400

    if not student_id:
        return jsonify({"ok": False, "error": "学号不能为空"}), 400

    if get_user(username):
        return jsonify({"ok": False, "error": "该账号已被注册"}), 400

    pwd_hash = generate_password_hash(password)
    create_user(username, pwd_hash, display_name or username, student_id)
    return jsonify({"ok": True, "message": "注册成功"})


# 找回密码
@auth_bp.route("/api/forgot_password", methods=["POST"])
def forgot_password():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    student_id = data.get("student_id", "").strip()
    new_password = data.get("new_password", "")
    confirm = data.get("confirm", "")
    code = data.get("captcha", "").strip()

    # 核对验证码（忽略大小写）
    if CURRENT_CAPTCHA and code.upper() != CURRENT_CAPTCHA.upper():
        return jsonify({"ok": False, "error": "验证码错误"}), 400

    if not username or not student_id:
        return jsonify({"ok": False, "error": "账号和学号不能为空"}), 400

    if new_password != confirm:
        return jsonify({"ok": False, "error": "两次新密码不一致"}), 400

    user = get_user(username)
    if not user or user.get("student_id") != student_id:
        return jsonify({"ok": False, "error": "账号与学号不匹配"}), 400

    new_hash = generate_password_hash(new_password)
    update_password(user["id"], new_hash)
    return jsonify({"ok": True, "message": "密码重置成功"})


# 修改密码
@auth_bp.route("/api/change_password", methods=["POST"])
def change_password():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    old_pwd = data.get("old_password", "")
    new_pwd = data.get("new_password", "")
    confirm = data.get("confirm", "")

    if not username:
        return jsonify({"ok": False, "error": "缺少用户名"}), 400

    user = get_user(username)
    if not user:
        return jsonify({"ok": False, "error": "用户不存在"}), 404

    if not check_password_hash(user["password_hash"], old_pwd):
        return jsonify({"ok": False, "error": "旧密码错误"}), 400

    if new_pwd != confirm:
        return jsonify({"ok": False, "error": "两次新密码不一致"}), 400

    if old_pwd == new_pwd:
        return jsonify({"ok": False, "error": "新密码不能与旧密码相同"}), 400

    new_hash = generate_password_hash(new_pwd)
    update_password(user["id"], new_hash)
    return jsonify({"ok": True, "message": "密码修改成功"})
