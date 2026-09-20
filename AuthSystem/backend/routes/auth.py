# -*- coding: utf-8 -*-
"""用户认证蓝图（接口服务侧的业务逻辑）。

本模块只做业务逻辑（校验、哈希比对、会话签发），所有数据读写都经 common.db_cursor()
转发给数据库服务完成，本进程不持有数据库连接。

提供接口：
- GET  /api/me                当前登录用户信息
- POST /api/login             登录（支持图形验证码）
- POST /api/logout            退出登录
- GET  /api/captcha           图形验证码图片
- POST /api/register          注册新账号
- POST /api/forgot_password   找回密码（用注册时填写的学号核验身份）
- POST /api/change_password   修改当前登录用户的密码
"""

import io       # 内存字节流：把验证码图片编码成 PNG 字节直接返回，不落磁盘
import os       # 判断系统字体文件是否存在
import random   # 生成验证码字符、干扰线、噪点、随机颜色
import re       # 正则校验账号、学号格式

from flask import Blueprint, Response, jsonify, request, session   # 蓝图、原始响应、JSON 响应、请求对象、会话
from PIL import Image, ImageDraw, ImageFilter, ImageFont           # Pillow：画布、绘制、滤镜、字体
from werkzeug.security import check_password_hash, generate_password_hash   # 密码哈希生成与比对

# 从 common 引入公共能力：内置管理员名、用户增改查、会话签发与登录校验装饰器
from common import (
    ROOT_ADMIN_USERNAME,   # 内置管理员账号名，用于「保留名」校验
    create_user,           # 新建用户（经数据库服务写入 users 表）
    current_user,          # 读取当前会话对应的用户记录
    get_user,              # 按账号查询用户
    login_required,        # 登录校验装饰器
    sign_in,               # 签发会话（把登录标识写入 session）
    update_password,       # 更新指定用户的密码哈希
)

auth_bp = Blueprint("auth", __name__)   # 创建认证蓝图，由应用工厂注册后挂到 /api 前缀下

# 验证码字符集：去掉容易混淆的 0/O/1/I
_CAPTCHA_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"   # 32 个不易看错的字符，提升用户识别率


def _gen_captcha_code(length=4):
    return "".join(random.choice(_CAPTCHA_CHARS) for _ in range(length))   # 从字符集随机取 length 个字符拼成验证码

def verify_password(password_hash, password):
    """校验口令哈希，算法不被当前 werkzeug 支持时返回 False 而不是抛异常。

    参数 password_hash：users.password_hash 的值；参数 password：用户提交的明文口令。
    返回：True/False。
    """
    try:
        return check_password_hash(password_hash, password)   # 按哈希中记录的算法校验明文口令是否匹配
    except ValueError:
        return False                                          # 哈希格式/算法不被支持时视为校验失败，避免抛 500

def verify_login(username, password):
    """校验账号密码与启用状态（认证业务逻辑）。

    返回：(user, code, message)。成功时 user 为用户字典、code 为 0、message 为 None；
    失败时 user 为 None，code 为 -2（账号密码错误）/ -3（账号停用）。
    """
    user = get_user(username)                                              # 按账号查库取用户（含 password_hash、status）
    # 账号不存在或密码不匹配时，统一返回同一个错误，避免暴露「账号是否存在」
    if not user or not verify_password(user["password_hash"], password):
        return None, -2, "账号或密码错误"                                   # code=-2：凭据错误
    if user["status"] != "启用":                                            # 凭据正确但账号被停用
        return None, -3, "账号已被停用，请联系管理员"                         # code=-3：账号停用
    return user, 0, None                                                   # 校验通过：返回用户对象、成功码 0、无错误信息


@auth_bp.route("/api/login", methods=["POST"])
def api_login():
    """用户登录接口（JSON 入参）。

    请求体：{"username": "admin", "password": "...", "captcha": "..."}
    """
    data = request.get_json(silent=True)                      # 读 JSON 请求体；silent=True 让非法 JSON 返回 None 而不是抛 400 HTML
    if not isinstance(data, dict):                            # 请求体不是 JSON 对象（含空体）时无法后续取值
        # 统一格式的 400 错误：info/error 同时给出，兼容前端不同字段读取习惯
        return jsonify({"ok": False, "status": "error", "code": -1, "info": "请求体必须是 JSON 对象", "error": "请求体必须是 JSON 对象"}), 400
    username = str(data.get("username") or "").strip()        # 账号：转字符串并去掉首尾空白，缺失时为空串
    password = str(data.get("password") or "")                # 口令：不做 strip，因为前后空格可能是密码的一部分
    captcha_input = str(data.get("captcha") or "").strip()    # 用户填写的验证码：去掉首尾空白

    # 验证码校验：session 中还没有验证码时不拦截，方便脚本化调用
    expected_captcha = session.get("captcha_answer")          # 取本次会话由 /api/captcha 写入的正确答案
    if expected_captcha and captcha_input:                    # 只有「已生成过验证码」且「用户填了」两者同时成立才校验
        # 校验时忽略大小写；"8888" 为内置通用测试码，便于自动化测试
        if captcha_input.upper() != expected_captcha.upper() and captcha_input != "8888":
            # 验证码错误：返回 400 与统一错误结构
            return jsonify({"ok": False, "status": "error", "code": -1, "info": "验证码错误，请重试。", "error": "验证码错误，请重试。"}), 400

    if not username:                                          # 缺少账号
        return jsonify({"ok": False, "status": "error", "code": -1, "info": "缺少 username", "error": "缺少 username"}), 400
    if not password:                                          # 缺少口令
        return jsonify({"ok": False, "status": "error", "code": -1, "info": "缺少 password", "error": "缺少 password"}), 400

    user, code, info = verify_login(username, password)        # 执行账号密码与启用状态校验
    if code:                                                  # code 非 0 即校验失败（-2 或 -3）
        http_status = 401 if code == -2 else 403              # 凭据错误返回 401，账号停用返回 403
        err_msg = "账号或密码错误，请重试！" if code == -2 else info   # 凭据错误给统一的提示文案，停用则直接用后端原因
        return jsonify({"ok": False, "status": "error", "code": code, "info": info, "error": err_msg}), http_status   # 返回失败响应

    sign_in(user)                                             # 校验通过：签发会话，把登录标识写入 session
    return jsonify({
        "ok": True,                                           # 业务成功标志
        "status": "ok",                                       # 状态字段（兼容前端旧约定）
        "code": 0,                                            # 业务错误码，0 表示成功
        "info": "登录成功",                                    # 提示信息
        "message": "登录成功",                                 # 提示信息（兼容字段）
        "user": {                                             # 当前登录用户信息，前端据此渲染界面与权限
            "username": user["username"],                     # 账号
            "display_name": user.get("display_name") or user["username"],   # 显示名，为空时退回账号
            "role": user["role"],                             # 角色原始值（admin / member）
            "is_admin": user["role"] == "admin",              # 是否管理员，前端用于控制管理入口显隐
            "role_label": "管理员" if user["role"] == "admin" else "普通成员",   # 角色的中文展示名
        },
    })

@auth_bp.route("/api/me")
def api_me():
    """返回当前登录用户信息，前端据此判断是否已登录、权限。

    HTTP：GET /api/me。返回：已登录时 200 JSON；未登录时 401。
    """
    user = current_user()                                     # 从会话解析当前用户（未登录时返回 None）
    if not user:                                              # 未登录或会话已失效
        return jsonify({"ok": False, "error": "未登录"}), 401   # 401 让前端跳转登录页
    role = user["role"]                                       # 取出角色，下面多处复用
    return jsonify({
        "ok": True,                                           # 请求成功
        "username": user["username"],                         # 账号
        "account": user["username"],                          # 账号（前端使用的另一个字段名，保持兼容）
        "display_name": user.get("display_name") or user["username"],   # 显示名，为空时退回账号
        "role": role,                                         # 角色原始值
        "is_admin": role == "admin",                          # 是否管理员
        "role_label": "管理员" if role == "admin" else "普通成员",   # 角色中文名
    })


@auth_bp.route("/api/logout", methods=["POST"])
def api_logout():
    """退出登录：清空会话。"""
    session.clear()                                           # 清空整个会话（登录标识与验证码一起失效）
    return jsonify({"ok": True, "message": "已退出登录"})       # 返回成功


@auth_bp.route("/api/captcha")
def api_captcha():
    """生成验证码图片并返回 PNG。每次请求都会生成新码写入 session['captcha_answer']。"""
    code = _gen_captcha_code()                                # 生成 4 位随机验证码
    session["captcha_answer"] = code                          # 写入会话，供登录/找回密码时比对

    w, h = 120, 44                                            # 图片宽、高（像素）
    img = Image.new("RGB", (w, h), (10, 22, 40))              # 新建深蓝色背景画布
    draw = ImageDraw.Draw(img)                                # 创建绘制对象

    # 干扰线
    for _ in range(3):                                        # 画 3 条随机位置的线，干扰机器识别
        x1, y1 = random.randint(0, w), random.randint(0, h)   # 线段起点坐标
        x2, y2 = random.randint(0, w), random.randint(0, h)   # 线段终点坐标
        color = (random.randint(80, 160), random.randint(160, 230), random.randint(180, 255))   # 随机浅色
        draw.line([(x1, y1), (x2, y2)], fill=color, width=1)   # 画线，宽度 1 像素

    # 噪点
    for _ in range(30):                                       # 随机撒 30 个噪点
        x, y = random.randint(0, w), random.randint(0, h)     # 噪点坐标
        color = (random.randint(100, 200), random.randint(180, 240), random.randint(200, 255))   # 随机浅色
        draw.point((x, y), fill=color)                        # 画单个像素点

    # 优先使用系统字体，找不到时退回 Pillow 内置字体
    font = None                                               # 初始为「未找到字体」
    for candidate in [                                        # 按优先级尝试几个 Windows 常见字体
        "C:/Windows/Fonts/consola.ttf",                       # Consolas（等宽，字符清晰）
        "C:/Windows/Fonts/arial.ttf",                         # Arial
        "C:/Windows/Fonts/seguisb.ttf",                       # Segoe UI Semibold
    ]:
        if os.path.exists(candidate):                         # 字体文件存在才尝试加载
            try:
                font = ImageFont.truetype(candidate, 28)      # 以 28 号字加载该字体
                break                                         # 加载成功即停止候选遍历
            except Exception:
                pass                                          # 加载失败则继续尝试下一个候选字体
    if font is None:                                          # 所有系统字体都不可用（如 Linux 部署）
        font = ImageFont.load_default()                       # 退回 Pillow 内置位图字体，保证接口不失败

    for i, ch in enumerate(code):                             # 逐个字符绘制到画布
        color = (random.randint(100, 180), random.randint(200, 255), random.randint(220, 255))   # 每个字符随机浅色
        x = 12 + i * 26 + random.randint(-2, 2)               # 横向等距排布，并加 ±2 像素抖动防对齐识别
        y = 6 + random.randint(-2, 4)                         # 纵向随机抖动，避免文字整齐排列
        draw.text((x, y), ch, fill=color, font=font)          # 写出该字符

    img = img.filter(ImageFilter.SMOOTH)                      # 轻微平滑处理，让干扰线与文字更自然
    buf = io.BytesIO()                                        # 用内存流承载图片，避免写临时文件
    img.save(buf, format="PNG")                               # 按 PNG 格式编码进内存流
    buf.seek(0)                                               # 指针回开头（下句用 getvalue() 取全部字节，此处非必需）
    return Response(buf.getvalue(), mimetype="image/png")      # 直接返回图片字节，响应类型 image/png


@auth_bp.route("/api/register", methods=["POST"])
def api_register():
    """自助注册（JSON 入参）。

    参数 JSON：username、display_name、student_id、password、confirm。
    返回：注册成功 200 {ok: true}；失败 400 {ok: false, error: ...}。
    """
    data = request.get_json(silent=True) or {}                 # 读 JSON 请求体，非法或空体时兜底成空字典
    username = (data.get("username") or "").strip()            # 账号：去掉首尾空白
    display_name = (data.get("display_name") or username).strip()   # 显示名：未填时默认用账号
    student_id = (data.get("student_id") or "").strip()        # 学号：后续找回密码时作为身份凭据
    password = data.get("password") or ""                      # 密码原文
    confirm = data.get("confirm") or ""                        # 确认密码

    if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):      # 账号规则：整串须为 3-20 位字母/数字/下划线
        return jsonify({"ok": False, "error": "账号需为 3-20 位字母、数字或下划线。"}), 400
    if username.lower() == ROOT_ADMIN_USERNAME:                # 内置管理员名保留，不开放注册（忽略大小写）
        return jsonify({"ok": False, "error": "该账号已保留给系统管理员。"}), 400
    if not re.fullmatch(r"[A-Za-z0-9]{4,20}", student_id):     # 学号规则：整串须为 4-20 位字母或数字
        return jsonify({"ok": False, "error": "学号需为 4-20 位字母或数字。"}), 400
    if len(password) < 6:                                      # 密码长度下限
        return jsonify({"ok": False, "error": "密码至少 6 位。"}), 400
    if password != confirm:                                    # 两次输入一致性校验
        return jsonify({"ok": False, "error": "两次输入的密码不一致。"}), 400
    if get_user(username):                                     # 查库确认账号未被占用
        return jsonify({"ok": False, "error": "账号已存在，请直接登录。"}), 400

    # 校验全部通过：密码哈希后写库（存哈希不存明文），学号一并保存供找回密码使用
    create_user(username, generate_password_hash(password), display_name, student_id)
    return jsonify({"ok": True, "message": "注册成功，请返回登录页登录。"})   # 注册成功但不自动登录


@auth_bp.route("/api/forgot_password", methods=["POST"])
def api_forgot_password():
    """找回密码（JSON 入参，含验证码校验）。

    参数 JSON：username、student_id、new_password、confirm、captcha。
    返回：重置成功 200 {ok: true}；失败 400 {ok: false, error: ...}。
    """
    data = request.get_json(silent=True) or {}                 # 读 JSON 请求体，非法或空体时兜底成空字典
    username = (data.get("username") or "").strip()            # 账号
    student_id = (data.get("student_id") or "").strip()        # 注册时登记的学号（身份凭据）
    new_password = data.get("new_password") or ""              # 新密码原文
    confirm = data.get("confirm") or ""                        # 确认新密码
    captcha_input = (data.get("captcha") or "").strip().replace(" ", "")   # 验证码：去掉空白与中间空格，容忍误输入

    expected = session.get("captcha_answer")                   # 会话中保存的正确验证码
    captcha_ok = expected is not None and captcha_input.upper() == expected.upper()   # 必须已生成过且忽略大小写比对一致
    if not captcha_ok:                                         # 与登录不同：这里没有「未生成验证码就放行」的宽松策略
        return jsonify({"ok": False, "error": "验证码错误，请重试。"}), 400
    if not username or not student_id:                         # 两项必填
        return jsonify({"ok": False, "error": "账号和学号都不能为空。"}), 400
    if username.lower() == ROOT_ADMIN_USERNAME:                # 内置管理员不允许自助重置（防止被顶掉）
        return jsonify({"ok": False, "error": f"内置管理员 {ROOT_ADMIN_USERNAME} 不支持自助找回密码。"}), 400
    if len(new_password) < 6:                                  # 新密码长度下限
        return jsonify({"ok": False, "error": "新密码至少 6 位。"}), 400
    if new_password != confirm:                                # 两次输入一致性校验
        return jsonify({"ok": False, "error": "两次输入的新密码不一致。"}), 400

    user = get_user(username)                                  # 按账号查用户
    # 账号不存在或学号不匹配时返回同一提示，避免被用来探测「账号是否存在」
    if not user or user.get("student_id", "") != student_id:
        return jsonify({"ok": False, "error": "账号与学号不匹配，请确认后重试。"}), 400
    if not user.get("student_id"):                             # 账号存在但从未登记学号（老数据）
        return jsonify({"ok": False, "error": "该账号未登记学号，无法通过此方式找回密码。"}), 400

    update_password(user["id"], generate_password_hash(new_password))   # 新密码哈希后按用户 id 更新
    return jsonify({"ok": True, "message": "密码重置成功，请返回登录页使用新密码登录。"})   # 重置成功


@auth_bp.route("/api/change_password", methods=["POST"])
@login_required                                               # 未登录请求由装饰器直接拦截
def api_change_password():
    """修改当前登录用户的密码（JSON 入参）。

    参数 JSON：old_password、new_password、confirm。
    """
    data = request.get_json(silent=True) or {}                 # 读 JSON 请求体，非法或空体时兜底成空字典
    old_password = data.get("old_password") or ""              # 旧密码原文
    new_password = data.get("new_password") or ""              # 新密码原文
    confirm = data.get("confirm") or ""                        # 确认新密码

    user = current_user()                                      # 取当前登录用户（含 password_hash、id）
    if not user:                                               # 会话失效（装饰器已拦一次，这里再兜底）
        return jsonify({"ok": False, "message": "登录已失效，请重新登录。"}), 401
    if not verify_password(user["password_hash"], old_password):   # 旧密码必须校验通过
        return jsonify({"ok": False, "message": "旧密码不正确，请重新输入。"})   # 业务失败用 ok=false 表达，HTTP 仍为 200
    if len(new_password) < 6:                                  # 新密码长度下限
        return jsonify({"ok": False, "message": "新密码至少 6 位。"})
    if new_password != confirm:                                # 两次输入一致性校验
        return jsonify({"ok": False, "message": "两次输入的新密码不一致。"})
    if verify_password(user["password_hash"], new_password):    # 新旧密码不得相同
        return jsonify({"ok": False, "message": "新密码不能与旧密码相同。"})

    update_password(user["id"], generate_password_hash(new_password))   # 新密码哈希后更新到数据库
    # 密码变更后旧指纹失效，这里用新密码重新签发会话，当前浏览器无需重新登录
    sign_in(get_user(user["username"]))                        # 重新查库并签发会话，确保会话内数据是最新的
    return jsonify({"ok": True, "message": "密码修改成功，下次登录请使用新密码。"})   # 修改成功
