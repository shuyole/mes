# -*- coding: utf-8 -*-
"""后端接口服务主入口（默认 8090 端口）。

职责：
1. 创建 Flask 应用实例与 CORS 跨域配置（前端页面与接口不同端口，需允许跨端口携带 Cookie）；
2. 注册认证业务蓝图（routes/ 目录）；
3. 启动时确保数据库服务已就绪，并请求它完成建表与内置管理员初始化。

数据访问：本进程不连接数据库，所有 SQL 都通过 HTTP 转发给数据库服务（db_server.py），
启动时若该服务未运行会自动拉起。

启动：python backend/api_server.py
"""

# ===== 导入 =====
import os           # 拼路径（定位 db_server.py 脚本位置）
import subprocess   # 拉起数据库服务子进程
import sys          # 取当前 Python 解释器路径，确保子进程用同一个 Python
import time         # 轮询等待数据库服务就绪

from flask import Flask       # Web 框架
from flask_cors import CORS   # 跨域支持（前端 6031 → 后端 8090 需要跨端口）

# 从 common 引入：端口、密钥、数据库服务地址、数据库探活与初始化函数
from common import (
    BACKEND_PORT,        # 后端接口服务端口（默认 8090）
    DB_SERVICE_URL,      # 数据库服务地址（http://127.0.0.1:6070）
    FRONTEND_PORT,       # 前端端口，仅用于启动提示
    HOST,                # 监听地址
    SECRET_KEY,          # 会话签名密钥（与前端服务共用同一份）
    db_service_alive,    # 探测数据库服务是否就绪
    init_db,             # 请求数据库服务建表 + 写入内置管理员
)
from routes import register_routes   # 注册全部业务蓝图（auth_bp 等）


# ===== Flask 应用与中间件 =====
# Flask 应用实例：后端只提供 JSON 接口，不需要模板与静态目录
app = Flask("auth_api")

# 会话签名密钥：与前端静态页面服务共用同一份配置
app.secret_key = SECRET_KEY   # Flask 用它对 session cookie 签名，防篡改；两个服务同密钥才能互相识别会话

# 跨域配置：前端页面与接口端口不同，需允许携带 Cookie 凭证
# origins="*" + supports_credentials=True 时，flask-cors 会把 Access-Control-Allow-Origin
# 回显成实际 Origin（而不是字面的 *），否则浏览器会拒绝带凭证的跨域请求
CORS(app, origins="*", supports_credentials=True)

# 注册全部业务蓝图
register_routes(app)   # 把 routes/auth.py 里的 auth_bp 等挂到 app 上，路由前缀 /api/*


# ===== 数据库服务自动拉起 =====
# 数据库服务脚本路径：与本文件同目录
_DB_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db_server.py")


def ensure_db_service():
    """确保数据库服务已就绪：未运行时拉起子进程并等待其探活通过。

    返回：True=服务可用，False=启动失败（此时后续 init_db 会继续报错并重试）。
    说明：单独运行 api_server.py 时也能自动带上数据库服务；服务已在运行时不会重复拉起。
    """
    if db_service_alive():          # 先探活，已在运行就直接返回
        return True
    try:
        # 拉起子进程运行 db_server.py；CREATE_NO_WINDOW 在 Windows 上避免弹出控制台窗口
        subprocess.Popen(
            [sys.executable or "python", _DB_SCRIPT],
            cwd=os.path.dirname(_DB_SCRIPT),
            stdout=subprocess.DEVNULL,   # 丢弃子进程输出，避免干扰当前终端
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),   # 非 Windows 上 getattr 返回 0，不影响
        )
    except Exception as exc:
        print(f"数据库服务启动失败: {exc}")
        return False
    # 数据库服务需要先建立连接，给它最多 10 秒
    for _ in range(20):             # 20 次 × 0.5 秒 = 最多等 10 秒
        time.sleep(0.5)
        if db_service_alive():
            print(f"数据库服务已就绪：{DB_SERVICE_URL}")
            return True
    print(f"数据库服务未就绪，请检查 {_DB_SCRIPT}")
    return False


# ===== 启动入口 =====
if __name__ == "__main__":
    # 1. 确保数据库服务可用，再初始化数据库（支持自动重试，等待数据库就绪）
    ensure_db_service()                         # 拉起 6070（如未运行）
    for i in range(6):                          # 最多重试 6 次调 /db/init
        try:
            info = init_db()                    # 请 6070 建表 + 写入内置管理员
            print(f"数据库初始化成功（引擎：{info.get('engine')}，地址：{info.get('host')}:{info.get('port')}，库/文件：{info.get('database')}）")
            break
        except Exception as exc:
            if i < 5:
                print(f"数据库暂未就绪（{exc}），2 秒后重试 ({i + 1}/6)")
                time.sleep(2)
            else:
                print(f"数据库初始化失败: {exc}")

    # 2. 启动 HTTP 接口服务
    print(f"后端接口服务已启动： http://127.0.0.1:{BACKEND_PORT}  （前端页面服务在 {FRONTEND_PORT} 端口）")
    app.run(host=HOST, port=BACKEND_PORT, threaded=True)   # threaded=True 支持并发请求
