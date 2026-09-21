# -*- coding: utf-8 -*-
import json
import urllib.request

# 数据库服务地址（6070 端口）
DB_URL = "http://127.0.0.1:6070"


def call_db(path, data=None):
    """向 6070 数据库服务发送请求并获取返回数据"""
    req = urllib.request.Request(
        DB_URL + path,
        data=json.dumps(data).encode("utf-8") if data else None,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_user(username):
    """查询用户"""
    res = call_db("/db/get_user", {"username": username})
    return res.get("user")


def create_user(username, password_hash, display_name, student_id):
    """新建用户"""
    res = call_db("/db/create_user", {
        "username": username,
        "password_hash": password_hash,
        "display_name": display_name,
        "student_id": student_id
    })
    return res.get("ok", False)


def update_password(user_id, password_hash):
    """更新用户密码"""
    res = call_db("/db/update_password", {
        "user_id": user_id,
        "password_hash": password_hash
    })
    return res.get("ok", False)
