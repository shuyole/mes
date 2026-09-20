# -*- coding: utf-8 -*-
"""后端接口服务主入口（默认 8080 端口）。

职责：
1. 创建 Flask 应用实例与 CORS 跨域配置；
2. 注册各领域业务蓝图（routes/ 目录：auth, orders, line, scada, production, system）；
3. 启动常驻后台守护线程（core/ 目录：Modbus TCP 轮询与工业产线仿真引擎）；
4. 提供统一的异常捕获与启动自愈机制。

数据访问：本进程不连接数据库，所有 SQL 都通过 HTTP 转发给 6060 数据库服务（db_server.py），
启动时若该服务未运行会自动拉起（与虚拟 PLC 的处理方式一致）。

启动：python api_server.py
"""

from threading import Thread
import os
import subprocess
import sys
import time

from flask import Flask
from flask_cors import CORS

from common import (
    BACKEND_PORT,
    CONFIG,
    DB_SERVICE_URL,
    FRONTEND_PORT,
    PLC_CONFIG,
    db_service_alive,
    init_db,
)
from core.line_engine import line_simulator
from core.plc import poll_plc_status
from routes import register_routes
import virtual_plc_manager

# Flask 应用实例：后端只提供 JSON 接口，不需要模板与静态目录
app = Flask("mes_api")

# 与前端服务共用同一个 secret_key，前端签发的会话 Cookie 在这里同样有效
app.secret_key = CONFIG.get("secret_key") or "mes_secret_key_2026"

# 跨域配置：允许携带 Cookie 凭证
CORS(app, origins="*", supports_credentials=True)

# 注册全部业务蓝图（33 个 RESTful API 接口）
register_routes(app)

# 数据库服务脚本路径：与本文件同目录
_DB_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db_server.py")


def ensure_db_service():
    """确保 6060 数据库服务已就绪：未运行时拉起子进程并等待其探活通过。

    返回：True=服务可用，False=启动失败（此时后续 init_db 会继续报错并重试）。
    说明：单独运行 api_server.py（不走 start.bat）时也能自动带上数据库服务；
          服务已在运行时不会重复拉起，避免 6060 端口被抢占。
    """
    if db_service_alive():
        return True
    try:
        subprocess.Popen(
            [sys.executable or "python", _DB_SCRIPT],
            cwd=os.path.dirname(_DB_SCRIPT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        print(f"数据库服务启动失败: {exc}")
        return False
    # 数据库服务需要先探测引擎，给它最多 10 秒
    for _ in range(20):
        time.sleep(0.5)
        if db_service_alive():
            print(f"数据库服务已就绪：{DB_SERVICE_URL}")
            return True
    print(f"数据库服务未就绪，请检查 {_DB_SCRIPT}")
    return False


if __name__ == "__main__":
    import traceback as _tb
    try:
        # 1. 确保数据库服务可用，再初始化数据库（支持自动重试，等待数据库就绪）
        ensure_db_service()
        _init_ok = False
        for _i in range(6):
            try:
                init_db()
                print("数据库初始化成功")
                _init_ok = True
                break
            except Exception as exc:
                if _i < 5:
                    print(f"数据库暂未就绪（{exc}），2 秒后重试 ({_i + 1}/6)")
                    time.sleep(2)
                else:
                    print(f"数据库连接失败: {exc}")

        # 2. 启动虚拟 PLC（若目标 IP 为本地）与后台守护线程
        virtual_plc_manager.ensure_virtual_plc_for_ip(PLC_CONFIG.get("ip"))
        Thread(target=poll_plc_status, daemon=True).start()
        Thread(target=line_simulator, daemon=True).start()
        print(f"PLC 轮询与产线仿真线程已启动 ({PLC_CONFIG['ip']}:{PLC_CONFIG['port']})")

        # 3. 启动 HTTP 接口服务
        host = CONFIG.get("host") or "0.0.0.0"
        print(f"后端接口服务已启动： http://127.0.0.1:{BACKEND_PORT}  （前端页面服务在 {FRONTEND_PORT} 端口）")
        app.run(host=host, port=BACKEND_PORT, threaded=True)

    except Exception:
        _crash_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_crash.log")
        with open(_crash_path, "w", encoding="utf-8") as _cf:
            _tb.print_exc(file=_cf)
            _cf.flush()
        print(f"[FATAL] api_server 启动崩溃，traceback 已写入 {_crash_path}")
        raise