# -*- coding: utf-8 -*-
"""
虚拟 PLC 子进程管理器

职责：把 virtual_plc.py 作为独立进程启停，供 api_server.py 在 PLC IP 切换到
127.0.0.1 / localhost / 本机局域网 IP 时自动拉起，切换到其他 IP 时自动关闭。
独立子进程的好处：ModbusTcpServer 阻塞式，不能直接导入到 Flask 进程里跑；
               子进程挂掉也不会拖垮 Flask，重启服务就能自动拉起。
"""

import os
import sys
import subprocess

# virtual_plc.py 路径：与本模块同目录
_VPLC_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "virtual_plc.py")

# 当前虚拟 PLC 子进程对象；None 表示未启动或已退出
_process = None


def _is_loopback(ip):
    """判断 IP 是否应该走虚拟仿真（本机回环或 0.0.0.0 监听）。"""
    if not ip:
        return False
    s = str(ip).strip().lower()
    return s in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def start_virtual_plc():
    """启动虚拟 PLC 子进程。已在运行时返回 False；端口被占用返回 False；
    其它异常只打印告警不向上抛。
    返回：True=已启动或已在运行；False=启动失败。
    """
    global _process
    if _process is not None and _process.poll() is None:
        return True  # 已经在跑
    try:
        python = sys.executable or "python"
        _process = subprocess.Popen(
            [python, _VPLC_SCRIPT],
            cwd=os.path.dirname(_VPLC_SCRIPT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # 给子进程一点启动时间，避免立刻就被检测为端口占用
        import time
        time.sleep(0.8)
        if _process.poll() is None:
            print(f"[virtual_plc] 已启动 PID={_process.pid}")
            return True
        print("[virtual_plc] 子进程启动后立即退出，可能 502 端口被占用")
        _process = None
        return False
    except Exception as exc:
        print(f"[virtual_plc] 启动失败: {exc}")
        _process = None
        return False


def stop_virtual_plc():
    """关闭虚拟 PLC 子进程。没有在运行时返回 False。"""
    global _process
    if _process is None or _process.poll() is not None:
        _process = None
        return False
    try:
        _process.terminate()
        _process.wait(timeout=3)
    except Exception:
        try:
            _process.kill()
        except Exception:
            pass
    finally:
        _process = None
    print("[virtual_plc] 已停止")
    return True


def ensure_virtual_plc_for_ip(ip):
    """根据目标 IP 决定虚拟 PLC 子进程的启停。

    目标 IP 是本机回环（127.0.0.1 / localhost / ::1 / 0.0.0.0）时启动子进程，
    否则关闭。典型调用点：
      - api_server.py 启动时（确保 config.json 里写的是本机 IP 时有虚拟 PLC 可用）
      - HMI 页面通过 /api/plc/config 切 IP 时（自动切换）
    返回：(used_virtual, started_or_stopped)
      used_virtual  True=应该走虚拟 PLC；started_or_stopped  True=状态有变化
    """
    should_run = _is_loopback(ip)
    was_running = _process is not None and _process.poll() is None
    if should_run and not was_running:
        return True, start_virtual_plc()
    if not should_run and was_running:
        return False, stop_virtual_plc()
    return should_run, False
