# -*- coding: utf-8 -*-
import os
from flask import Flask, redirect, send_from_directory

# 项目根目录
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATES_DIR = os.path.join(ROOT_DIR, "frontend", "Templates")
STATIC_DIR = os.path.join(ROOT_DIR, "frontend", "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.route("/")
def index():
    return redirect("/login")


@app.route("/<page>")
def show_page(page):
    return send_from_directory(TEMPLATES_DIR, f"{page}.html")


if __name__ == "__main__":
    print("前端静态页面服务已启动: http://127.0.0.1:6031")
    app.run(host="0.0.0.0", port=6031)
