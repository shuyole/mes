# -*- coding: utf-8 -*-
"""前端静态文件服务（默认 6021 端口）。

职责：提供 frontend/ 目录的静态文件（HTML/CSS/JS），所有非文件路由 fallback 到 index.html（SPA 路由支持）。
本服务不连接数据库、不含业务逻辑，所有数据交互通过浏览器直接调用 api_server.py（8080 端口）的 API 完成。

启动：python static_server.py
"""

import mimetypes
import os

from flask import Flask, send_from_directory

from common import CONFIG, FRONTEND_DIR, FRONTEND_PORT

# 确保常见 MIME 类型正确
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

app = Flask(
    "mes_static",
    static_folder=os.path.join(FRONTEND_DIR, "static"),
    static_url_path="/static",
)

# 禁用浏览器缓存，开发期间改完刷新即生效
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_spa(path):
    """SPA 路由 fallback：有对应文件则返回文件，否则返回 index.html。

    这样前端可以使用 hash 路由（/#/home）或 history 路由（/home），
    刷新页面时服务器总能返回 index.html，由前端 JS 接管路由。
    """
    # 先检查 frontend/ 目录下是否有对应文件
    file_path = os.path.join(FRONTEND_DIR, path)
    if path and os.path.isfile(file_path):
        return send_from_directory(FRONTEND_DIR, path)
    # 检查 Templates/ 子目录
    pages_path = os.path.join(FRONTEND_DIR, "Templates", path)
    if path and os.path.isfile(pages_path):
        return send_from_directory(os.path.join(FRONTEND_DIR, "Templates"), path)
    # 其他路径一律返回 index.html，由前端路由器处理
    return send_from_directory(FRONTEND_DIR, "index.html")


if __name__ == "__main__":
    host = CONFIG.get("host") or "0.0.0.0"
    print(f"前端静态文件服务已启动： http://10.144.11.105:{FRONTEND_PORT}")
    print(f"  提供目录: {FRONTEND_DIR}")
    print(f"  所有 API 请求请直接访问后端服务（8080 端口）")
    app.run(host=host, port=FRONTEND_PORT, threaded=True)
