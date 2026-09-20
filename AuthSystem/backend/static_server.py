# -*- coding: utf-8 -*-
"""前端静态页面服务（默认 6031 端口）。

职责：只提供 frontend/ 目录的静态文件（HTML/CSS/JS）。本服务不连接数据库、不含业务逻辑，
页面里的所有数据交互都由浏览器直接调用后端接口服务（8090 端口）的 /api/* 完成。

页面路由：
- GET /                  跳转到登录页
- GET /login             登录页
- GET /register          注册页
- GET /forgot_password   找回密码页
- GET /home              登录后的系统主页（登录态由前端调用 /api/me 判断）
- GET /settings          系统设置页，内含「修改登录密码」入口

启动：python backend/static_server.py
"""

# ===== 导入 =====
import mimetypes   # 按文件扩展名返回正确的 Content-Type
import os          # 拼路径

from flask import Flask, redirect, send_from_directory, url_for   # Web 框架、重定向、静态文件发送、URL 反向解析

from common import FRONTEND_DIR, FRONTEND_PORT, HOST   # 前端目录、端口、监听地址（都来自 config.json）


# ===== MIME 类型修正 =====
# 确保常见 MIME 类型正确（Windows 注册表可能把 .js 映射成 text/plain）
mimetypes.add_type("application/javascript", ".js")   # 不修的话浏览器会拒绝执行 .js（当成纯文本下载）
mimetypes.add_type("text/css", ".css")                 # 同理保证 CSS 被当作样式表而不是文本


# ===== 目录与 Flask 应用 =====
# 页面片段目录：frontend/Templates
TEMPLATES_DIR = os.path.join(FRONTEND_DIR, "Templates")   # HTML 模板目录，下面每个 .html 对应一个页面

# Flask 应用：静态文件映射到 /static，模板页面由下面的路由函数手动返回
app = Flask(
    "auth_static",
    static_folder=os.path.join(FRONTEND_DIR, "static"),   # /static/* → frontend/static/*
    static_url_path="/static",
)

# 禁用浏览器缓存，开发期间改完刷新即生效
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0   # 响应头 Cache-Control: no-cache，避免改了 CSS/JS 不生效


# ===== 页面分发 =====
def _page(filename):
    """从 Templates 目录返回指定页面。

    统一的页面返回入口：所有路由函数都调这个，避免每处重复写 send_from_directory。
    """
    return send_from_directory(TEMPLATES_DIR, filename)


@app.route("/")
def index():
    """根路径统一跳转到登录页。用户访问 6031 根地址时不会看到 404，而是直接到登录页。"""
    return redirect(url_for("page_login"))


@app.route("/login")
def page_login():
    """登录页。"""
    return _page("login.html")


@app.route("/register")
def page_register():
    """注册页。"""
    return _page("register.html")


@app.route("/forgot_password")
def page_forgot_password():
    """找回密码页。"""
    return _page("forgot_password.html")


@app.route("/home")
def page_home():
    """登录后的系统主页（是否已登录由页面内 JS 调用后端 /api/me 判断）。

    说明：本服务不校验登录态，只负责把 HTML 发给浏览器；
    页面加载后由 JS 调 8090 的 /api/me，返回 401 就跳回登录页。
    """
    return _page("home.html")


@app.route("/settings")
def page_settings():
    """系统设置页：修改登录密码入口在此，点击后弹出改密弹窗。"""
    return _page("settings.html")


# ===== 启动入口 =====
if __name__ == "__main__":
    print(f"前端静态页面服务已启动： http://127.0.0.1:{FRONTEND_PORT}")
    print(f"  提供目录: {FRONTEND_DIR}")
    print("  所有 API 请求请直接访问后端服务（8090 端口）")
    app.run(host=HOST, port=FRONTEND_PORT, threaded=True)   # threaded=True 支持并发请求
