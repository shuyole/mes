# -*- coding: utf-8 -*-
import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = "data/auth.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            student_id TEXT DEFAULT '',
            role TEXT DEFAULT 'member',
            status TEXT DEFAULT '启用',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    # 默认管理员账号 admin / admin123
    c.execute("SELECT id FROM users WHERE username = ?", ("admin",))
    if not c.fetchone():
        c.execute("""
            INSERT INTO users (username, password_hash, display_name, student_id, role, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("admin", generate_password_hash("admin123"), "管理员", "ADMIN001", "admin", "启用"))
    conn.commit()
    conn.close()


def get_user(username):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def create_user(username, password_hash, display_name, student_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO users (username, password_hash, display_name, student_id, role, status)
        VALUES (?, ?, ?, ?, 'member', '启用')
    """, (username, password_hash, display_name, student_id))
    conn.commit()
    conn.close()
    return True


def update_password(user_id, password_hash):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
    conn.commit()
    conn.close()
    return True
