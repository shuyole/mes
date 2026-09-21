# -*- coding: utf-8 -*-
import subprocess
import sys
import time
from flask import Flask
from flask_cors import CORS
from common import call_db
from routes import register_routes

app = Flask(__name__)
# 允许跨域（前端 6031 -> 后端 8090）
CORS(app)

register_routes(app)


def check_and_start_db():
    res = call_db("/db/health")
    if not res.get("ok"):
        subprocess.Popen([sys.executable, "backend/db_server.py"])
        time.sleep(1)


if __name__ == "__main__":
    check_and_start_db()
    call_db("/db/init")
    print("后端接口服务已启动: http://127.0.0.1:8090")
    app.run(host="0.0.0.0", port=8090)
