# -*- coding: utf-8 -*-
import json
import pymysql
from pymysql.cursors import DictCursor
from werkzeug.security import generate_password_hash

with open("config/config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)["database"]


def get_db():
    return pymysql.connect(
        host=cfg.get("host", "127.0.0.1"),
        port=int(cfg.get("port", 3306)),
        user=cfg.get("user", "root"),
        password=cfg.get("password", ""),
        database=cfg.get("name", "auth_db"),
        charset="utf8mb4",
        cursorclass=DictCursor
    )


def init_db():
    # 自动建库
    conn = pymysql.connect(
        host=cfg.get("host", "127.0.0.1"),
        port=int(cfg.get("port", 3306)),
        user=cfg.get("user", "root"),
        password=cfg.get("password", "")
    )
    c = conn.cursor()
    c.execute(f"CREATE DATABASE IF NOT EXISTS `{cfg.get('name', 'auth_db')}` DEFAULT CHARACTER SET utf8mb4")
    c.close()
    conn.close()

    # 建表与默认管理员
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            display_name VARCHAR(50) DEFAULT '',
            student_id VARCHAR(50) DEFAULT '',
            role VARCHAR(20) DEFAULT 'member',
            status VARCHAR(20) DEFAULT '启用',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("SELECT id FROM users WHERE username = %s", ("admin",))
    if not c.fetchone():
        c.execute("""
            INSERT INTO users (username, password_hash, display_name, student_id, role, status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, ("admin", generate_password_hash("admin123"), "管理员", "ADMIN001", "admin", "启用"))
    conn.commit()
    conn.close()


def get_user(username):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    conn.close()
    return row


def create_user(username, password_hash, display_name, student_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO users (username, password_hash, display_name, student_id, role, status)
        VALUES (%s, %s, %s, %s, 'member', '启用')
    """, (username, password_hash, display_name, student_id))
    conn.commit()
    conn.close()
    return True


def update_password(user_id, password_hash):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))
    conn.commit()
    conn.close()
    return True
