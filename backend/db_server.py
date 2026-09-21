# -*- coding: utf-8 -*-
import json
from flask import Flask, jsonify, request

# 读取配置选择数据库
with open("config/config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)

db_type = cfg.get("database", {}).get("type", "auto").lower()

if db_type == "mysql":
    import db_mysql as db
elif db_type == "sqlite":
    import db_sqlite as db
else:
    try:
        import db_mysql as db
        conn = db.get_db()
        conn.close()
    except Exception:
        import db_sqlite as db

app = Flask(__name__)


@app.route("/db/health")
def health():
    return jsonify({"ok": True})


@app.route("/db/init", methods=["POST"])
def init():
    db.init_db()
    return jsonify({"ok": True})


@app.route("/db/get_user", methods=["POST"])
def get_user():
    data = request.get_json() or {}
    user = db.get_user(data.get("username"))
    return jsonify({"ok": True, "user": user})


@app.route("/db/create_user", methods=["POST"])
def create_user():
    d = request.get_json() or {}
    db.create_user(d["username"], d["password_hash"], d.get("display_name", ""), d.get("student_id", ""))
    return jsonify({"ok": True})


@app.route("/db/update_password", methods=["POST"])
def update_password():
    d = request.get_json() or {}
    db.update_password(d["user_id"], d["password_hash"])
    return jsonify({"ok": True})


if __name__ == "__main__":
    db.init_db()
    print("数据库服务已启动: http://127.0.0.1:6070")
    app.run(host="0.0.0.0", port=6070)
