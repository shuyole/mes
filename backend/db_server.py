# -*- coding: utf-8 -*-
"""数据库服务（默认 6060 端口）。

职责：本项目唯一直接连接数据库的进程。后端接口服务（8080）与页面服务（6021）
都不再持有数据库驱动与连接，所有 SQL 统一通过本服务的 HTTP 接口执行：
后端进程用 db_cursor() 开启一个会话，逐条 execute，提交或回滚后关闭。

对外接口（请求与响应都是 JSON）：
- GET  /db/health             探活并返回当前引擎信息
- POST /db/init               建库建表、写入基础数据（幂等，可重复调用）
- POST /db/session/open       开启一个事务会话，返回 session_id
- POST /db/session/execute    在会话中执行一条 SQL，返回列名与结果行
- POST /db/session/commit     提交会话事务
- POST /db/session/rollback   回滚会话事务
- POST /db/session/close      关闭会话并释放数据库连接

启动：python db_server.py
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from decimal import Decimal
from functools import wraps

import pymysql
from flask import Flask, jsonify, request
from werkzeug.security import generate_password_hash

from common import (
    CONFIG,
    DATA_DIR,
    DB_CONFIG,
    DB_SERVICE_PORT,
    PRODUCTS,
    ROOT_ADMIN_USERNAME,
    STATION_DEFS,
)

# SQLite 兜底数据库文件路径（MySQL 不可用时自动切换到它，首次使用时自动创建 data 目录）
SQLITE_PATH = os.path.join(DATA_DIR, "mes.db")
# 项目文件同步目录：data/sync/<table>.json
SYNC_DIR = os.path.join(DATA_DIR, "sync")
# 上次连接的数据库签名文件：用于检测是否切换了库并触发 JSON 快照回填
_LAST_DB_SIG_PATH = os.path.join(DATA_DIR, ".last_db")

# 当前实际生效的数据库引擎："mysql" 或 "sqlite"
ENGINE = "mysql"
# 需要快照到项目文件的业务表清单
SYNC_TABLES = ("users", "production_orders", "work_records", "production_logs", "line_stations", "products")

# 会话空闲回收时间（秒）：客户端异常退出时兜底释放数据库连接
SESSION_IDLE_TTL = 300
# 会话表：session_id -> {conn, cursor, lock, wrote, last_used}
_sessions = {}
_sessions_lock = threading.Lock()

# 防止同步函数递归调用（同步内部读 DB 时不再触发同步）
_SYNC_GUARD = threading.local()
_SYNC_LOCK = threading.Lock()


def detect_engine():
    """探测并确定实际使用的数据库引擎，结果写入全局 ENGINE。

    规则：config.json 的 database.type 为 sqlite 时直接用 SQLite；为 mysql 时连不上会降级；
    为 auto（默认）时优先尝试 MySQL，3 秒内连不上则自动回退到本地 SQLite。
    返回：无。副作用：修改全局 ENGINE，可能创建 data 目录，并打印最终选中的引擎与原因。
    """
    global ENGINE
    # 缺省按 auto 处理；统一小写，避免配置里写成 MySQL / SQLITE 导致判断失效
    wanted = (CONFIG["database"].get("type") or "auto").lower()
    if wanted == "sqlite":
        ENGINE = "sqlite"
        # 保证 SQLite 文件所在目录存在，否则连接时会报无法打开数据库
        os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
        print(f"数据库：SQLite  {SQLITE_PATH}")
        return
    try:
        cfg = dict(DB_CONFIG)
        # 探测阶段目标库可能还没建，先去掉库名只连 MySQL 服务器；
        # connect_timeout=3 限制等待时间，避免 MySQL 未启动时启动流程长时间卡住
        cfg.pop("database")
        conn = pymysql.connect(connect_timeout=3, **cfg)
        conn.close()
        ENGINE = "mysql"
        print(f"数据库：MySQL  {DB_CONFIG['host']} / {DB_CONFIG['database']}")
        return
    except Exception as exc:
        ENGINE = "sqlite"
        os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
        print(f"MySQL 无法连接（{exc}），自动降级使用本地 SQLite: {SQLITE_PATH}")
        return


def get_db_connection():
    """按当前生效的引擎创建一个数据库连接。

    返回：SQLite 时返回 sqlite3.Connection（check_same_thread=False 允许后台线程共用连接，
    row_factory 设为 sqlite3.Row 以便按列名取值，timeout=10 缓解并发写锁等待）；
    MySQL 时返回 pymysql 连接。
    """
    if ENGINE == "sqlite":
        # 每次连接前确认目录存在，防止 data 目录被手工删除后报错
        os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
        conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    return pymysql.connect(**DB_CONFIG)


def prepare_sql(sql):
    """把 MySQL 风格的 SQL 改写成 SQLite 可执行的等价写法（仅 SQLite 模式下生效）。

    参数 sql：业务代码统一按 MySQL 语法书写的 SQL 字符串。
    返回：改写后的 SQL；MySQL 模式下原样返回。
    说明：这一层兼容处理让上层业务只维护一套 SQL，无需在各处判断当前引擎。
    """
    if ENGINE != "sqlite":
        return sql
    # SQLite 不支持反引号包裹标识符
    sql = sql.replace("`", "")
    # SQLite 的占位符是 ?，而业务代码统一按 pymysql 的 %s 书写
    sql = sql.replace("%s", "?")
    # 自增主键两种数据库的关键字组合不同
    sql = sql.replace("INT AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
    # SQLite 的 CURRENT_TIMESTAMP 取的是 UTC，改为 datetime('now','localtime') 与 MySQL 的本地时间语义一致
    sql = sql.replace("TIMESTAMP DEFAULT CURRENT_TIMESTAMP", "TEXT DEFAULT (datetime('now','localtime'))")
    # 生产趋势统计里的「近 7 天」条件：DATE_SUB(CURDATE(), INTERVAL 6 DAY) 换成 SQLite 的 date('now','-6 days')
    sql = sql.replace("DATE_SUB(CURDATE(), INTERVAL 6 DAY)", "date('now','-6 days')")
    # date() 两者同名同义，这里保留原样以便将来统一替换成其它方言
    sql = sql.replace("DATE(created_at)", "date(created_at)")
    return sql


class CompatCursor:
    """游标适配器：屏蔽 MySQL 与 SQLite 之间的占位符、结果行类型和事务行为差异。

    上层业务统一按 MySQL 语法（%s 占位符）编写，SQLite 模式下的转换由本类自动完成；
    结果行统一是「值序列」，列名由 raw.description 提供，便于序列化后经 HTTP 返回。
    """

    def __init__(self, raw):
        """包装一个真实游标。参数 raw：底层驱动游标（pymysql 或 sqlite3 的 Cursor）。"""
        self.raw = raw
        # 标记本次事务是否包含写操作（INSERT/UPDATE/DELETE/REPLACE），
        # 会话提交后据此决定是否触发项目文件同步
        self.wrote = False

    def execute(self, sql, args=None):
        """执行一条 SQL，执行前先做 SQLite 语法兼容改写。

        参数 sql：MySQL 风格 SQL；参数 args：参数元组/列表，为 None 时表示无参执行。
        返回：底层游标 execute 的返回值（通常为影响行数）。
        """
        sql = prepare_sql(sql)
        # 检测写操作（前缀匹配，跳过注释和空白），用于触发文件同步
        head = sql.lstrip()
        # 去掉行首的 SQL 行注释
        if head.startswith("--"):
            head = ""
        head_upper = head[:6].upper()
        if head_upper.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
            self.wrote = True
        if args is None:
            return self.raw.execute(sql)
        return self.raw.execute(sql, args)

    def fetchone(self):
        """取一行结果。返回：单行值序列，无数据时返回 None。"""
        return self.raw.fetchone()

    def fetchall(self):
        """取全部结果行。返回：行列表。"""
        return self.raw.fetchall()

    def close(self):
        """关闭底层游标。返回：无。"""
        self.raw.close()


def ensure_database():
    """MySQL 模式下确保目标数据库已存在（首次部署时配置的库通常还没建）。

    返回：无。副作用：在 MySQL 中执行 CREATE DATABASE IF NOT EXISTS，字符集固定 utf8mb4 以支持中文；
    SQLite 模式直接返回，数据库文件由 get_db_connection 负责创建。
    """
    if ENGINE != "mysql":
        return
    cfg = dict(DB_CONFIG)
    # 连接参数必须去掉库名，否则连一个还不存在的库会直接报错
    db_name = cfg.pop("database")
    conn = pymysql.connect(**cfg)
    cursor = conn.cursor()
    cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    cursor.close()
    conn.close()


def _db_signature():
    """当前连接的数据库签名：host + database 名。用于检测是否切换了库。"""
    return f"{DB_CONFIG.get('host')}:{DB_CONFIG.get('database')}"


def _read_last_db_sig():
    """读取上次连接的数据库签名。文件不存在时返回空串（视为首次启动）。"""
    try:
        with open(_LAST_DB_SIG_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _write_last_db_sig(sig):
    """把当前数据库签名写盘，作为下次启动的对照基线。"""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_LAST_DB_SIG_PATH, "w", encoding="utf-8") as f:
            f.write(sig)
    except Exception as e:
        print(f"[sync] 写 last_db 签名失败: {e}")


def sync_from_project_files():
    """把 data/sync/<table>.json 的数据回填到当前连接的数据库。

    用于「切换数据库」场景：新库可能只有空表或种子数据，本函数把项目内最近一次
    快照的行通过 REPLACE INTO 推到新库，使新库与原库内容一致。
    幂等：JSON 缺失的表跳过；行有自增 id 时 REPLACE 按主键覆盖。
    失败只打印告警，不向上抛。
    """
    if not os.path.isdir(SYNC_DIR):
        return
    try:
        conn = get_db_connection()
        try:
            cur = CompatCursor(conn.cursor())
            for table in SYNC_TABLES:
                path = os.path.join(SYNC_DIR, f"{table}.json")
                if not os.path.exists(path):
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        rows = json.load(f)
                    if not rows:
                        continue
                    # 取列名并构造 REPLACE INTO（按主键覆盖，新库已有的同 id 行会被替换）
                    cols = list(rows[0].keys())
                    col_sql = ", ".join(f"`{c}`" for c in cols)
                    marks = ", ".join(["%s"] * len(cols))
                    sql = f"REPLACE INTO `{table}` ({col_sql}) VALUES ({marks})"
                    for r in rows:
                        cur.execute(sql, tuple(r.get(c) for c in cols))
                    print(f"[sync] 回填 {table}: {len(rows)} 行")
                except Exception as e:
                    print(f"[sync] 跳过回填 {table}: {e}")
            conn.commit()
            cur.close()
        finally:
            conn.close()
    except Exception as e:
        print(f"[sync] 回填失败: {e}")


def sync_to_project_files():
    """把业务表快照到 data/sync/<table>.json，作为远程数据库的项目内镜像。

    幂等、可重入：用线程本地 guard 防止嵌套触发（同步内部会读 DB，读 DB 不应再触发同步）。
    失败不影响主业务：任何异常都只打印告警，不向上抛。
    """
    if getattr(_SYNC_GUARD, "in_progress", False):
        return
    with _SYNC_LOCK:
        if getattr(_SYNC_GUARD, "in_progress", False):
            return
        _SYNC_GUARD.in_progress = True
    try:
        os.makedirs(SYNC_DIR, exist_ok=True)
        conn = get_db_connection()
        try:
            cur = CompatCursor(conn.cursor())
            for table in SYNC_TABLES:
                try:
                    cur.execute(f"SELECT * FROM {table}")
                    columns = [desc[0] for desc in cur.raw.description or ()]
                    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
                    target = os.path.join(SYNC_DIR, f"{table}.json")
                    tmp = target + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(rows, f, ensure_ascii=False, indent=2, default=str)
                    # 原子替换：临时文件 rename 覆盖目标，避免读到写一半的内容
                    os.replace(tmp, target)
                except Exception as e:
                    print(f"[sync] 跳过表 {table}: {e}")
            cur.close()
        finally:
            conn.close()
    except Exception as e:
        print(f"[sync] 快照失败: {e}")
    finally:
        _SYNC_GUARD.in_progress = False


def ensure_column(cursor, table, column, definition):
    """启动时做表结构升级：列不存在才 ALTER TABLE 添加，实现老库平滑升级且可重复执行。

    参数 cursor：CompatCursor 实例；参数 table：表名；参数 column：列名；参数 definition：列定义（MySQL 语法）。
    返回：无。副作用：可能修改表结构（两种数据库查看列的语句不同，这里分别处理）。
    """
    if ENGINE == "sqlite":
        # SQLite 没有 SHOW COLUMNS，改用 PRAGMA table_info 取列信息
        cursor.execute(f"PRAGMA table_info({table})")
        # PRAGMA 结果每行为 (cid, name, type, notnull, dflt_value, pk)，列名在第 2 列
        names = [row[1] for row in cursor.fetchall()]
        if column not in names:
            # SQLite 的 ADD COLUMN 只支持追加列，正好符合升级场景
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        return
    # MySQL 用 SHOW COLUMNS ... LIKE 判断列是否已存在，避免重复添加报错
    cursor.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (column,))
    if not cursor.fetchone():
        cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")


def upsert(cursor, table, unique_col, data):
    """按唯一列执行「存在则更新、不存在则插入」。

    参数 cursor：CompatCursor 实例；参数 table：表名；参数 unique_col：唯一键列名；
    参数 data：列名 -> 值 的字典（不应包含自增主键 id）。
    返回：无。副作用：写数据库；用于启动时把 PRODUCTS、STATION_DEFS 同步进库而不产生重复行。
    """
    cols = list(data.keys())
    # 占位符个数与列数一致，值仍走参数化绑定，避免拼接 SQL 注入
    marks = ", ".join(["%s"] * len(cols))
    col_sql = ", ".join(cols)
    values = list(data.values())
    if ENGINE == "sqlite":
        # SQLite 语法：ON CONFLICT(唯一列) DO UPDATE，冲突时用 excluded.列 引用本次要插入的新值
        updates = ", ".join(f"{col}=excluded.{col}" for col in cols if col != unique_col)
        sql = f"INSERT INTO {table} ({col_sql}) VALUES ({marks}) ON CONFLICT({unique_col}) DO UPDATE SET {updates}"
    else:
        # MySQL 语法：ON DUPLICATE KEY UPDATE，用 VALUES(列) 引用本次要插入的新值
        updates = ", ".join(f"{col}=VALUES({col})" for col in cols if col != unique_col)
        sql = f"INSERT INTO {table} ({col_sql}) VALUES ({marks}) ON DUPLICATE KEY UPDATE {updates}"
    cursor.execute(sql, values)


def init_database():
    """初始化数据库：探测引擎 → 建库 → 建表 → 补列 → 写入基础数据。

    返回：无（异常向上抛，由调用方捕获后打印提示）。
    副作用：可能创建数据库以及 production_orders / products / line_stations / work_records / production_logs / users 六张表，
    并在缺失时写入内置管理员 admin（密码 ADMIN）、产品型号和 7 个工位的基础数据；本函数可重复执行（幂等）。
    """
    detect_engine()
    ensure_database()
    conn = get_db_connection()
    cursor = CompatCursor(conn.cursor())
    # 建表语句统一按 MySQL 语法书写，SQLite 下由 prepare_sql 自动改写
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS production_orders (
            id INT AUTO_INCREMENT PRIMARY KEY,
            order_no VARCHAR(50) NOT NULL,
            product_name VARCHAR(100) NOT NULL,
            quantity INT NOT NULL,
            status VARCHAR(20) DEFAULT '待生产',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # 老版本库缺失的列在这里补齐，保证升级后代码里的字段都能用上（已存在则跳过）
    for column, definition in [
        ("product_code", "VARCHAR(50) DEFAULT ''"),
        ("completed_qty", "INT DEFAULT 0"),
        ("ng_qty", "INT DEFAULT 0"),
        ("priority", "INT DEFAULT 1"),
        ("due_date", "DATE NULL"),
        ("progress", "INT DEFAULT 0"),
        ("current_station", "VARCHAR(50) DEFAULT ''"),
        ("started_at", "DATETIME NULL"),
        ("finished_at", "DATETIME NULL"),
        ("remark", "VARCHAR(255) DEFAULT ''"),
        ("created_by", "VARCHAR(50) DEFAULT ''"),
    ]:
        ensure_column(cursor, "production_orders", column, definition)

    # 产品型号表：与代码中的 PRODUCTS 常量对应，code 唯一
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INT AUTO_INCREMENT PRIMARY KEY,
            code VARCHAR(50) NOT NULL UNIQUE,
            name VARCHAR(100) NOT NULL,
            model VARCHAR(50),
            cycle_time INT DEFAULT 30
        )
        """
    )
    # 工位基础信息表：由 STATION_DEFS 同步，sequence 表示工艺顺序（1 起）
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS line_stations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            code VARCHAR(20) NOT NULL UNIQUE,
            name VARCHAR(50) NOT NULL,
            sequence INT NOT NULL,
            cycle_sec INT DEFAULT 8,
            plc_address INT DEFAULT 10,
            role VARCHAR(20) DEFAULT '',
            status VARCHAR(20) DEFAULT '空闲',
            processed_qty INT DEFAULT 0
        )
        """
    )
    # 过站记录表：仿真过程中每完成一个工位就写一条，供生产统计与良率分析使用
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS work_records (
            id INT AUTO_INCREMENT PRIMARY KEY,
            order_id INT,
            order_no VARCHAR(50),
            station_code VARCHAR(20),
            station_name VARCHAR(50),
            ok_qty INT DEFAULT 0,
            ng_qty INT DEFAULT 0,
            status VARCHAR(20) DEFAULT '完成',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # 生产日志表：登录、下发工单、报警等事件都记录于此，页面按时间倒序展示
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS production_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            order_no VARCHAR(50) DEFAULT '',
            level VARCHAR(20) DEFAULT 'INFO',
            message VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    ensure_column(cursor, "production_logs", "category", "VARCHAR(20) DEFAULT 'sys'")

    # 用户表：密码只存 werkzeug 哈希；role 为 admin/member，status 为 启用/停用
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            display_name VARCHAR(50) DEFAULT '',
            role VARCHAR(20) DEFAULT 'member',
            status VARCHAR(20) DEFAULT '启用',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # 老库平滑升级：旧 users 表没有 student_id 列时自动补上，用于找回密码的身份验证
    ensure_column(cursor, "users", "student_id", "VARCHAR(50) DEFAULT ''")
    # 内置管理员仅在首次部署（表中还没有 admin）时创建，避免覆盖已被修改的密码
    cursor.execute("SELECT id FROM users WHERE username=%s LIMIT 1", (ROOT_ADMIN_USERNAME,))
    if not cursor.fetchone():
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role, status)
            VALUES (%s, %s, %s, 'admin', '启用')
            """,
            (ROOT_ADMIN_USERNAME, generate_password_hash("ADMIN"), "系统管理员"),
        )

    # 产品与工位属于只读基础数据，每次启动 upsert 一遍，保证与代码中的定义一致
    for product in PRODUCTS:
        upsert(
            cursor,
            "products",
            "code",
            {
                "code": product["code"],
                "name": product["name"],
                "model": product["model"],
                "cycle_time": product["cycle_time"],
            },
        )
    # start=1 让 sequence 从 1 开始，与界面展示的工位顺序一致
    for idx, station in enumerate(STATION_DEFS, start=1):
        upsert(
            cursor,
            "line_stations",
            "code",
            {
                "code": station["code"],
                "name": station["name"],
                "sequence": idx,
                "cycle_sec": station["cycle_sec"],
                "plc_address": station["plc_address"],
                "role": station["role"],
            },
        )
    keep_codes = [station["code"] for station in STATION_DEFS]
    marks = ", ".join(["%s"] * len(keep_codes))
    cursor.execute(f"DELETE FROM line_stations WHERE code NOT IN ({marks})", keep_codes)
    conn.commit()
    cursor.close()
    conn.close()
    # 检测数据库是否切换：签名与上次不同时，把项目内 JSON 快照回填到新库
    current_sig = _db_signature()
    last_sig = _read_last_db_sig()
    if last_sig and last_sig != current_sig:
        print(f"[sync] 检测到数据库切换：{last_sig} -> {current_sig}，开始回填项目数据")
        sync_from_project_files()
    # 启动初始化也走一次文件同步，保证 data/sync/*.json 与库一致
    sync_to_project_files()
    # 记录本次连接的数据库签名，作为下次启动的基线
    _write_last_db_sig(current_sig)


def json_value(value):
    """把数据库返回值转成可 JSON 序列化的类型。

    参数 value：单列值。返回：Decimal 转 int，datetime/date 转格式化字符串，bytes 转 utf-8 文本，其余原样返回。
    说明：HTTP 传输前必须转换，否则 Flask 无法序列化 Decimal 与日期对象。
    """
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return value


def open_session():
    """开启一个数据库事务会话。

    返回：session_id 字符串。副作用：新建一个数据库连接与游标并登记到 _sessions。
    """
    session_id = uuid.uuid4().hex
    conn = get_db_connection()
    session = {
        "conn": conn,
        "cursor": CompatCursor(conn.cursor()),
        "lock": threading.Lock(),
        "wrote": False,
        "last_used": time.time(),
    }
    with _sessions_lock:
        _sessions[session_id] = session
    return session_id


def execute_on_session(session_id, sql, args):
    """在指定会话中执行一条 SQL 并取回全部结果行。

    参数 session_id：会话标识；参数 sql：MySQL 风格 SQL；参数 args：参数列表或 None。
    返回：(columns, rows, rowcount, wrote)，行是「值序列」的列表，值已转为可 JSON 序列化类型。
    说明：结果行一次性取回并随响应返回，调用方按需 fetch，不保留服务端游标状态。
    """
    session = _sessions.get(session_id)
    if not session:
        raise KeyError("会话不存在或已关闭，请重新开启会话")
    with session["lock"]:
        cursor = session["cursor"]
        raw = cursor.raw
        cursor.execute(sql, args)
        columns = [desc[0] for desc in raw.description] if raw.description else []
        rows = [[json_value(v) for v in row] for row in raw.fetchall()] if columns else []
        rowcount = raw.rowcount
        session["wrote"] = session["wrote"] or cursor.wrote
        session["last_used"] = time.time()
        return columns, rows, rowcount, session["wrote"]


def commit_session(session_id):
    """提交会话事务；若本次会话有过写操作，则顺带把业务表快照到 data/sync/*.json。

    返回：wrote（本次会话是否写库）。副作用：提交事务，可能写项目文件。
    """
    session = _sessions.get(session_id)
    if not session:
        raise KeyError("会话不存在或已关闭，请重新开启会话")
    with session["lock"]:
        session["conn"].commit()
        session["last_used"] = time.time()
        wrote = session["wrote"]
    if wrote:
        sync_to_project_files()
    return wrote


def rollback_session(session_id):
    """回滚会话事务。返回：无。"""
    session = _sessions.get(session_id)
    if not session:
        raise KeyError("会话不存在或已关闭，请重新开启会话")
    with session["lock"]:
        session["conn"].rollback()
        session["last_used"] = time.time()


def close_session(session_id):
    """关闭会话并释放数据库连接。会话不存在时视为已关闭，不报错。"""
    with _sessions_lock:
        session = _sessions.pop(session_id, None)
    if not session:
        return
    with session["lock"]:
        try:
            session["cursor"].close()
        except Exception:
            pass
        try:
            session["conn"].close()
        except Exception:
            pass


def _reap_idle_sessions():
    """后台线程：回收超时未关闭的会话，避免客户端异常退出后连接泄漏。"""
    while True:
        time.sleep(30)
        now = time.time()
        with _sessions_lock:
            stale = [sid for sid, item in _sessions.items() if now - item["last_used"] > SESSION_IDLE_TTL]
        for sid in stale:
            close_session(sid)
            print(f"[db] 回收空闲会话 {sid}")


app = Flask("mes_db")


def _api(func):
    """统一的接口错误处理：业务异常转成 500 + JSON 错误体，避免直接抛 HTML 错误页。"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return jsonify(func(*args, **kwargs))
        except Exception as exc:
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    return wrapper


@app.route("/db/health", methods=["GET"])
@_api
def db_health():
    """探活：后端与页面服务用它判断数据库服务是否就绪。"""
    return {
        "ok": True,
        "engine": ENGINE,
        "host": DB_CONFIG.get("host"),
        "database": DB_CONFIG.get("database"),
        "port": DB_SERVICE_PORT,
        "sessions": len(_sessions),
    }


@app.route("/db/init", methods=["POST"])
@_api
def db_init():
    """建库建表与基础数据初始化（幂等）。返回实际生效的引擎信息供后端展示。"""
    init_database()
    return {
        "ok": True,
        "engine": ENGINE,
        "host": DB_CONFIG.get("host"),
        "database": DB_CONFIG.get("database"),
    }


@app.route("/db/session/open", methods=["POST"])
@_api
def db_session_open():
    """开启事务会话。"""
    return {"ok": True, "session_id": open_session()}


@app.route("/db/session/execute", methods=["POST"])
@_api
def db_session_execute():
    """在会话中执行 SQL，返回列名与结果行。"""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id") or ""
    sql = data.get("sql") or ""
    args = data.get("args")
    if not sql:
        raise ValueError("缺少 sql 参数")
    columns, rows, rowcount, wrote = execute_on_session(session_id, sql, args)
    return {"ok": True, "columns": columns, "rows": rows, "rowcount": rowcount, "wrote": wrote}


@app.route("/db/session/commit", methods=["POST"])
@_api
def db_session_commit():
    """提交会话事务。"""
    data = request.get_json(silent=True) or {}
    return {"ok": True, "wrote": commit_session(data.get("session_id") or "")}


@app.route("/db/session/rollback", methods=["POST"])
@_api
def db_session_rollback():
    """回滚会话事务。"""
    data = request.get_json(silent=True) or {}
    rollback_session(data.get("session_id") or "")
    return {"ok": True}


@app.route("/db/session/close", methods=["POST"])
@_api
def db_session_close():
    """关闭会话并释放数据库连接。"""
    data = request.get_json(silent=True) or {}
    close_session(data.get("session_id") or "")
    return {"ok": True}


if __name__ == "__main__":
    threading.Thread(target=_reap_idle_sessions, daemon=True).start()
    host = CONFIG.get("host") or "0.0.0.0"
    print(f"数据库服务已启动： http://127.0.0.1:{DB_SERVICE_PORT}")
    app.run(host=host, port=DB_SERVICE_PORT, threaded=True)
