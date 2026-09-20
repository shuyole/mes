# -*- coding: utf-8 -*-
"""数据库服务（默认 6070 端口）。

职责：本系统唯一直接连接数据库的进程。后端接口服务（8090）不持有数据库连接，
所有 SQL 都通过本服务的 HTTP 接口执行：后端用 db_cursor() 开启一个会话，
逐条 execute，提交或回滚后关闭。

数据库引擎（config/config.json 的 database.type）：
- mysql  强制使用 MySQL（连不上直接报错）
- sqlite 强制使用本地 SQLite 文件
- auto   默认；优先连 MySQL，连不上自动降级到 data/<filename> 的 SQLite 文件

对外接口（请求与响应都是 JSON）：
- GET  /db/health             探活并返回当前引擎信息
- POST /db/init               建库建表并写入内置管理员（幂等，可重复调用）
- POST /db/session/open       开启一个事务会话，返回 session_id
- POST /db/session/execute    在会话中执行一条 SQL，返回列名与结果行
- POST /db/session/commit     提交会话事务
- POST /db/session/rollback   回滚会话事务
- POST /db/session/close      关闭会话并释放数据库连接

启动：python backend/db_server.py
"""

import os                       # 拼路径、创建 data 目录、判断文件是否存在
import sqlite3                  # Python 内置的 SQLite 驱动（本地兜底引擎）
import threading                # 会话级互斥锁 + 后台空闲回收线程
import time                     # 记录会话最后使用时间、回收线程睡眠
import uuid                     # 生成随机会话 ID
from datetime import datetime   # 结果序列化时识别并格式化日期时间值
from decimal import Decimal     # 判断并转换 MySQL DECIMAL 类型的返回值
from functools import wraps     # 装饰器保留原函数名与文档字符串

import pymysql                                  # MySQL 驱动
from flask import Flask, jsonify, request       # Web 框架、JSON 响应、读取请求体
from werkzeug.security import generate_password_hash   # 给内置管理员密码做加盐哈希（不存明文）

# 从 common 读取集中配置：配置字典、data 目录、服务端口、监听地址、内置管理员账号与密码
from common import CONFIG, DATA_DIR, DB_SERVICE_PORT, HOST, ROOT_ADMIN_PASSWORD, ROOT_ADMIN_USERNAME

# ===== 数据库连接参数 =====
_DB_CFG = CONFIG.get("database") or {}    # config.json 的 database 段；为空时兜底成空字典，避免后续 .get 报错
# MySQL 连接参数字典（pymysql.connect 直接展开使用）
DB_CONFIG = {
    "host": _DB_CFG.get("host", "127.0.0.1"),      # MySQL 主机，默认本机
    "port": int(_DB_CFG.get("port", 3306)),        # MySQL 端口，默认 3306；配置里可能是字符串，强制转 int
    "user": _DB_CFG.get("user", "root"),           # 连接账号，默认 root
    "password": _DB_CFG.get("password", ""),       # 连接密码，默认空
    "database": _DB_CFG.get("name", "auth_db"),    # 目标库名，默认 auth_db
    "charset": "utf8mb4",                          # 字符集，支持中文与 emoji
}
# SQLite 兜底数据库文件：data/<filename>，首次使用时自动创建
SQLITE_PATH = os.path.join(DATA_DIR, _DB_CFG.get("filename") or "auth.db")   # 拼出 SQLite 文件绝对路径，配置缺失时用 auth.db

# 当前实际生效的数据库引擎："mysql" 或 "sqlite"
ENGINE = "sqlite"   # 模块级全局变量，启动时由 detect_engine() 覆写；这里给默认值避免未初始化

# 会话空闲回收时间（秒）：客户端异常退出时兜底释放数据库连接
SESSION_IDLE_TTL = 300   # 会话 300 秒（5 分钟）无人使用即被判定为僵尸会话并回收
# 会话表：session_id -> {conn, cursor, lock, wrote, last_used}
_sessions = {}                     # 进程内的会话注册表，key 是 session_id
_sessions_lock = threading.Lock()  # 保护 _sessions 字典本身的增删（不负责保护 SQL 执行）


def detect_engine():
    """探测并确定实际使用的数据库引擎，结果写入全局 ENGINE。

    规则：type 为 sqlite 时直接用 SQLite；为 mysql 时连不上会抛错；
    为 auto（默认）时优先尝试 MySQL，3 秒内连不上则自动回退到本地 SQLite。
    返回：无。副作用：修改全局 ENGINE，可能创建 data 目录，并打印最终选中的引擎与原因。
    """
    global ENGINE                                    # 声明此处修改的是模块级全局变量，而不是新建局部变量
    # 缺省按 auto 处理；统一小写，避免配置里写成 MySQL / SQLITE 导致判断失效
    wanted = (_DB_CFG.get("type") or "auto").lower()  # 读取配置的 database.type，缺省 auto 并统一转小写
    if wanted == "sqlite":                            # 配置强制使用 SQLite 时，不再尝试 MySQL
        ENGINE = "sqlite"                             # 确定引擎为 sqlite
        os.makedirs(DATA_DIR, exist_ok=True)          # 确保 data 目录存在（exist_ok=True 避免目录已存在时报错）
        print(f"数据库：SQLite  {SQLITE_PATH}")        # 打印选中的引擎与文件路径，便于排查问题
        return                                        # 提前结束，跳过 MySQL 探测
    try:                                              # -- 以下尝试连接 MySQL --
        cfg = dict(DB_CONFIG)                         # 复制一份连接参数，避免修改全局 DB_CONFIG
        # 探测阶段目标库可能还没建，先去掉库名只连 MySQL 服务器；
        # connect_timeout=3 限制等待时间，避免 MySQL 未启动时启动流程长时间卡住
        cfg.pop("database")                           # 去掉库名，否则连接一个不存在的库会直接报错
        conn = pymysql.connect(connect_timeout=3, **cfg)   # 展开参数连接 MySQL 服务器，最多等 3 秒
        conn.close()                                  # 探测成功，立即关闭这个临时连接（不占用连接数）
        ENGINE = "mysql"                              # 连接可用，引擎确定为 mysql
        # 打印实际连接目标：主机:端口 / 库名
        print(f"数据库：MySQL  {DB_CONFIG['host']}:{DB_CONFIG['port']} / {DB_CONFIG['database']}")
        return                                        # 探测通过，结束函数
    except Exception as exc:                          # 连接失败：服务未启动、账号密码错、网络不通等
        if wanted == "mysql":                         # 配置明确要求 MySQL 时不允许静默降级
            raise RuntimeError(f"MySQL 无法连接（{exc}）") from exc   # 直接抛错终止启动，并保留原始异常链
        ENGINE = "sqlite"                             # auto 模式：自动降级为本地 SQLite
        os.makedirs(DATA_DIR, exist_ok=True)          # 降级后要落文件，确保 data 目录存在
        # 打印降级原因，方便定位「为什么跑到了 SQLite」
        print(f"MySQL 无法连接（{exc}），自动降级使用本地 SQLite: {SQLITE_PATH}")


def get_db_connection():
    """按当前生效的引擎创建一个数据库连接。

    返回：SQLite 时返回 sqlite3.Connection（check_same_thread=False 允许会话锁下跨线程使用，
    row_factory 设为 sqlite3.Row 便于按列名取值，timeout=10 缓解并发写锁等待）；
    MySQL 时返回 pymysql 连接。
    """
    if ENGINE == "sqlite":                            # SQLite 分支
        # 每次连接前确认目录存在，防止 data 目录被手工删除后报错
        os.makedirs(DATA_DIR, exist_ok=True)          # 确保 data 目录存在
        conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False, timeout=10)   # 建连接：允许跨线程、写锁最多等 10 秒，文件不存在会自动创建
        conn.row_factory = sqlite3.Row                # 查询结果行可按列名取值（与 pymysql 风格更接近）
        return conn                                   # 返回连接，向上屏蔽两种引擎的差异
    return pymysql.connect(**DB_CONFIG)               # MySQL 分支：用统一参数字典建连接


def prepare_sql(sql):
    """把 MySQL 风格的 SQL 改写成 SQLite 可执行的等价写法（仅 SQLite 模式下生效）。

    参数 sql：业务代码统一按 MySQL 语法书写的 SQL 字符串。
    返回：改写后的 SQL；MySQL 模式下原样返回。
    说明：这一层兼容处理让上层业务只维护一套 SQL，无需在各处判断当前引擎。
    """
    if ENGINE != "sqlite":                # MySQL 模式：语法本来就一致
        return sql                        # 原样返回，不做任何改写
    # SQLite 不支持反引号包裹标识符
    sql = sql.replace("`", "")            # 去掉所有反引号（如 `users` -> users）
    # SQLite 的占位符是 ?，而业务代码统一按 pymysql 的 %s 书写
    sql = sql.replace("%s", "?")          # 占位符统一转换 %s -> ?
    # 自增主键两种数据库的关键字组合不同
    sql = sql.replace("INT AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")   # 主键写法转换
    # SQLite 的 CURRENT_TIMESTAMP 取的是 UTC，改为本地时间与 MySQL 的语义一致
    sql = sql.replace("TIMESTAMP DEFAULT CURRENT_TIMESTAMP", "TEXT DEFAULT (datetime('now','localtime'))")   # 默认时间改为本地时间
    return sql                            # 返回改写后的 SQL


class CompatCursor:
    """游标适配器：屏蔽 MySQL 与 SQLite 之间的占位符、结果行类型差异。

    上层业务统一按 MySQL 语法（%s 占位符）编写，SQLite 模式下的转换由本类自动完成；
    结果行统一是「值序列」，列名由 raw.description 提供，便于序列化后经 HTTP 返回。
    """

    def __init__(self, raw):
        """包装一个真实游标。参数 raw：底层驱动游标（pymysql 或 sqlite3 的 Cursor）。"""
        self.raw = raw                  # 持有底层真实游标，所有实际操作都转发给它
        # 标记本次事务是否包含写操作，提交时据此决定是否需要额外处理
        self.wrote = False              # 初始为「未写库」；execute 识别到写语句时置 True

    def execute(self, sql, args=None):
        """执行一条 SQL，执行前先做 SQLite 语法兼容改写。

        参数 sql：MySQL 风格 SQL；参数 args：参数元组/列表，为 None 时表示无参执行。
        返回：底层游标 execute 的返回值（通常为影响行数）。
        """
        sql = prepare_sql(sql)          # 先做引擎兼容改写（SQLite 下换占位符、主键、时间默认值）
        # 检测写操作（前缀匹配，跳过行首注释与空白）
        head = sql.lstrip()             # 去掉行首空白，取到语句真正的开头
        if head.startswith("--"):       # 行首是注释时，避免把注释里的词误判成语句类型
            head = ""                   # 置空后不会匹配到任何写关键字
        # 前 6 个字符匹配写操作关键字（INSERT/UPDATE/DELETE/REPLACE）
        if head[:6].upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
            self.wrote = True           # 标记本次事务发生过写操作
        if args is None:                # 无参数执行（如建表、PRAGMA）
            return self.raw.execute(sql)              # 直接执行整条 SQL
        return self.raw.execute(sql, args)            # 带参数执行，由驱动负责转义，天然防 SQL 注入

    def fetchone(self):
        """取一行结果。返回：单行值序列，无数据时返回 None。"""
        return self.raw.fetchone()      # 转发给底层游标

    def fetchall(self):
        """取全部结果行。返回：行列表。"""
        return self.raw.fetchall()      # 转发给底层游标，一次性取完所有行

    def close(self):
        """关闭底层游标。返回：无。"""
        self.raw.close()                # 转发关闭，释放游标资源


def ensure_database():
    """MySQL 模式下确保目标数据库已存在（首次部署时配置的库通常还没建）。

    返回：无。副作用：在 MySQL 中执行 CREATE DATABASE IF NOT EXISTS，字符集固定 utf8mb4 以支持中文；
    SQLite 模式直接返回，数据库文件由 get_db_connection 负责创建。
    """
    if ENGINE != "mysql":               # 只有 MySQL 才有「库」这一层概念
        return                          # SQLite 是文件数据库，直接结束
    cfg = dict(DB_CONFIG)               # 复制连接参数
    # 连接参数必须去掉库名，否则连一个还不存在的库会直接报错
    db_name = cfg.pop("database")       # 取出库名并从连接参数里移除，后续只连服务器
    conn = pymysql.connect(**cfg)       # 连接到 MySQL 服务器（不指定库）
    cursor = conn.cursor()              # 建一个临时游标用于执行建库语句
    cursor.execute(                     # 建库：已存在则忽略；utf8mb4 支持中文与 emoji
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    cursor.close()                      # 关闭临时游标
    conn.close()                        # 关闭临时连接


def ensure_column(cursor, table, column, definition):
    """启动时做表结构升级：列不存在才 ALTER TABLE 添加，实现老库平滑升级且可重复执行。

    参数 cursor：CompatCursor 实例；参数 table：表名；参数 column：列名；参数 definition：列定义（MySQL 语法）。
    返回：无。副作用：可能修改表结构（两种数据库查看列的语句不同，这里分别处理）。
    """
    if ENGINE == "sqlite":              # SQLite 分支
        # SQLite 没有 SHOW COLUMNS，改用 PRAGMA table_info 取列信息
        cursor.execute(f"PRAGMA table_info({table})")            # 查询该表的列结构
        # PRAGMA 结果每行为 (cid, name, type, notnull, dflt_value, pk)，列名在第 2 列
        names = [row[1] for row in cursor.fetchall()]            # 取出所有已存在的列名
        if column not in names:                                  # 只有缺列时才加，避免重复添加报错
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")   # 补列
        return                          # 结束 SQLite 分支
    # MySQL 用 SHOW COLUMNS ... LIKE 判断列是否已存在，避免重复添加报错
    cursor.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (column,))   # 查该列是否存在（%s 在 MySQL 模式下由 pymysql 处理）
    if not cursor.fetchone():                                     # 查不到说明列不存在
        cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")   # 补列


def init_database():
    """初始化数据库：探测引擎 → 建库 → 建表 → 补列 → 写入内置管理员。

    返回：实际生效的引擎名（"mysql" / "sqlite"）。异常向上抛，由调用方捕获后打印提示。
    副作用：可能创建数据库与 users 表，并在缺少 admin 时写入内置管理员（账号 admin / 密码 admin123）；
    本函数可重复执行（幂等）。
    """
    detect_engine()                     # 第 1 步：探测并确定引擎（写入全局 ENGINE）
    ensure_database()                   # 第 2 步：MySQL 下确保库存在（SQLite 下是空操作）
    conn = get_db_connection()          # 第 3 步：取一个独立短连接（注意不是事务会话）
    try:
        cursor = CompatCursor(conn.cursor())    # 用适配器包装游标，统一占位符与结果类型
        # 建表语句统一按 MySQL 语法书写，SQLite 下由 prepare_sql 自动改写
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (        -- 表不存在才创建，保证本函数可重复执行
                id INT AUTO_INCREMENT PRIMARY KEY,    -- 自增主键（SQLite 下会被改写成 AUTOINCREMENT）
                username VARCHAR(50) NOT NULL UNIQUE, -- 登录名：非空且唯一
                password_hash VARCHAR(255) NOT NULL,  -- 密码哈希（不存明文）
                display_name VARCHAR(50) DEFAULT '',  -- 显示名
                role VARCHAR(20) DEFAULT 'member',    -- 角色，默认普通成员
                status VARCHAR(20) DEFAULT '启用',     -- 账号状态
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP   -- 创建时间，默认当前时间
            )
            """
        )
        # 老库平滑升级：早期 users 表没有 student_id 列时自动补上（找回密码用）
        ensure_column(cursor, "users", "student_id", "VARCHAR(50) DEFAULT ''")   # 缺列才加
        # 内置管理员仅在首次部署（表中还没有 admin）时创建，避免覆盖已被修改的密码
        cursor.execute("SELECT id FROM users WHERE username=%s LIMIT 1", (ROOT_ADMIN_USERNAME,))   # 查 admin 是否已存在
        if not cursor.fetchone():       # 查不到说明是首次初始化
            cursor.execute(
                """
                INSERT INTO users (username, password_hash, display_name, role, status)
                VALUES (%s, %s, %s, 'admin', '启用')          -- 角色固定 admin，状态启用
                """,
                # 密码先哈希再入库，杜绝明文存储
                (ROOT_ADMIN_USERNAME, generate_password_hash(ROOT_ADMIN_PASSWORD), "系统管理员"),
            )
        conn.commit()                   # 提交建表与插入，真正落库
        cursor.close()                  # 关闭游标
    finally:
        conn.close()                    # 无论成功或异常都释放连接，避免泄漏
    return ENGINE                       # 回传实际生效的引擎，供接口层展示


def json_value(value):
    """把数据库返回值转成可 JSON 序列化的类型。

    参数 value：单列值。返回：Decimal 转 int，datetime/date 转格式化字符串，bytes 转 utf-8 文本，其余原样返回。
    """
    if isinstance(value, Decimal):                     # MySQL 的 DECIMAL 类型对象
        return int(value)                              # 转成 int，避免 JSON 序列化失败
    if isinstance(value, datetime):                    # datetime 对象（MySQL 驱动常见返回类型）
        return value.strftime("%Y-%m-%d %H:%M:%S")     # 格式化成「年-月-日 时:分:秒」
    if hasattr(value, "strftime"):                     # 其他带 strftime 的对象，如 datetime.date
        return value.strftime("%Y-%m-%d")              # 只格式化成日期
    if isinstance(value, (bytes, bytearray)):          # 二进制字段（如 BLOB）
        return value.decode("utf-8", "replace")        # 按 UTF-8 解码，非法字节用替换符兜底，保证不抛异常
    return value                                       # int/float/str/None 本身可序列化，原样返回


def open_session():
    """开启一个数据库事务会话。

    返回：session_id 字符串。副作用：新建数据库连接与游标并登记到 _sessions。
    """
    session_id = uuid.uuid4().hex      # 生成 32 位十六进制随机 ID，不可预测也不易重复
    conn = get_db_connection()         # 为该会话独占一个数据库连接（事务挂在这个连接上）
    session = {                        # 会话状态字典
        "conn": conn,                  # 数据库连接，用于 commit / rollback / close
        "cursor": CompatCursor(conn.cursor()),   # 适配器包装的游标，用于执行 SQL
        "lock": threading.Lock(),      # 会话级锁：保证同一会话的 SQL 串行执行
        "wrote": False,                # 本次事务是否发生过写操作
        "last_used": time.time(),      # 最后使用时间戳，供空闲回收线程判断
    }
    with _sessions_lock:               # 在全局锁内登记，避免与回收线程并发修改字典
        _sessions[session_id] = session
    return session_id                  # 把会话 ID 返回给调用方（后续请求都要带上它）


def execute_on_session(session_id, sql, args):
    """在指定会话中执行一条 SQL 并取回全部结果行。

    参数 session_id：会话标识；参数 sql：MySQL 风格 SQL；参数 args：参数列表或 None。
    返回：(columns, rows, rowcount, wrote)，行是「值序列」的列表，值已转为可 JSON 序列化类型。
    说明：结果行一次性取回并随响应返回，调用方按需 fetch，服务端不保留游标状态。
    """
    session = _sessions.get(session_id)     # 按 ID 查找会话
    if not session:                         # 找不到说明未开启、已关闭或已被回收
        raise KeyError("会话不存在或已关闭，请重新开启会话")   # 抛业务异常，由 _api 统一转成 500 JSON
    with session["lock"]:                   # 进入会话锁，保证同一会话内 SQL 串行执行
        cursor = session["cursor"]          # 取出适配器游标
        raw = cursor.raw                    # 取出底层真实游标，用于读 description / fetchall / rowcount
        cursor.execute(sql, args)           # 执行 SQL（内部做引擎兼容改写，并记录是否写操作）
        # 查询语句才有列名；非查询语句 description 为 None，列名给空列表
        columns = [desc[0] for desc in raw.description] if raw.description else []
        # 一次性取回全部行，并把每个值转成可 JSON 序列化的类型；没有列名说明不是查询，行列表为空
        rows = [[json_value(v) for v in row] for row in raw.fetchall()] if columns else []
        rowcount = raw.rowcount             # 影响行数（写操作主要看这个）
        session["wrote"] = session["wrote"] or cursor.wrote   # 累计标记：本会话只要写过一次就保持 True
        session["last_used"] = time.time()  # 刷新活跃时间，防止长事务被空闲回收误杀
        return columns, rows, rowcount, session["wrote"]      # 返回给接口层组装响应


def commit_session(session_id):
    """提交会话事务。返回：本次会话是否写库。"""
    session = _sessions.get(session_id)     # 按 ID 查找会话
    if not session:                         # 会话不存在则报错
        raise KeyError("会话不存在或已关闭，请重新开启会话")
    with session["lock"]:                   # 会话锁内提交，避免与正在执行的 SQL 竞争
        session["conn"].commit()            # 提交事务，数据真正落库
        session["last_used"] = time.time()  # 刷新活跃时间
        return session["wrote"]             # 回传本会话是否发生过写操作


def rollback_session(session_id):
    """回滚会话事务。返回：无。"""
    session = _sessions.get(session_id)     # 按 ID 查找会话
    if not session:                         # 会话不存在则报错
        raise KeyError("会话不存在或已关闭，请重新开启会话")
    with session["lock"]:                   # 会话锁内回滚
        session["conn"].rollback()          # 撤销本会话所有未提交的改动
        session["last_used"] = time.time()  # 刷新活跃时间


def close_session(session_id):
    """关闭会话并释放数据库连接。会话不存在时视为已关闭，不报错。"""
    with _sessions_lock:                    # 全局锁内原子地「取出并移除」
        session = _sessions.pop(session_id, None)   # pop 带默认值，取不到返回 None 而非报错
    if not session:                         # 已被关闭或从未存在
        return                              # 幂等：重复关闭不报错
    with session["lock"]:                   # 会话锁内关闭资源
        try:
            session["cursor"].close()       # 关闭游标
        except Exception:
            pass                            # 已关闭等情况直接忽略，保证后续步骤继续执行
        try:
            session["conn"].close()         # 关闭连接（未提交的事务会被驱动隐式回滚）
        except Exception:
            pass                            # 忽略重复关闭等异常


def _reap_idle_sessions():
    """后台线程：回收超时未关闭的会话，避免客户端异常退出后连接泄漏。"""
    while True:                             # 常驻循环
        time.sleep(30)                      # 每 30 秒扫一次
        now = time.time()                   # 取当前时间
        with _sessions_lock:                # 全局锁内筛选，避免遍历时字典被改动
            # 找出「最后使用时间距今超过 TTL」的会话 ID 列表（只做筛选，不在锁内做慢操作）
            stale = [sid for sid, item in _sessions.items() if now - item["last_used"] > SESSION_IDLE_TTL]
        for sid in stale:                   # 逐个关闭（关连接是慢操作，放在锁外做）
            close_session(sid)              # 复用统一的关闭逻辑，释放连接
            print(f"[db] 回收空闲会话 {sid}")   # 打印日志便于排查连接异常


app = Flask("auth_db")                      # 创建 Flask 应用


def _api(func):
    """统一的接口错误处理：业务异常转成 500 + JSON 错误体，避免直接抛 HTML 错误页。"""
    @wraps(func)                            # 保留被装饰函数的名称与文档字符串
    def wrapper(*args, **kwargs):           # 包装原视图函数
        try:
            return jsonify(func(*args, **kwargs))   # 正常返回：把 dict 转成 JSON 响应
        except Exception as exc:            # 任何异常都转成统一 JSON 错误体
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500   # 500 + 错误类型与信息
    return wrapper                          # 返回包装后的函数


@app.route("/db/health", methods=["GET"])
@_api
def db_health():
    """探活：后端服务用它判断数据库服务是否就绪。"""
    return {
        "ok": True,                                          # 服务可用
        "engine": ENGINE,                                    # 当前实际生效的引擎（mysql / sqlite）
        "host": DB_CONFIG.get("host"),                       # MySQL 主机（SQLite 模式下仅供参考）
        "port": DB_CONFIG.get("port"),                       # MySQL 端口
        "database": DB_CONFIG.get("database") if ENGINE == "mysql" else SQLITE_PATH,   # MySQL 显示库名，SQLite 显示文件路径
        "sessions": len(_sessions),                          # 当前活跃会话数，便于观察是否泄漏
    }


@app.route("/db/init", methods=["POST"])
@_api
def db_init():
    """建库建表与内置管理员初始化（幂等）。返回实际生效的引擎信息供后端展示。"""
    engine = init_database()                                 # 执行初始化，拿到实际生效的引擎
    return {
        "ok": True,                                          # 初始化成功
        "engine": engine,                                    # 实际生效的引擎
        "host": DB_CONFIG.get("host"),                       # MySQL 主机
        "port": DB_CONFIG.get("port"),                       # MySQL 端口
        "database": DB_CONFIG.get("database") if engine == "mysql" else SQLITE_PATH,   # 引擎对应的库名或文件路径
    }


@app.route("/db/session/open", methods=["POST"])
@_api
def db_session_open():
    """开启事务会话。"""
    return {"ok": True, "session_id": open_session()}        # 返回新会话 ID


@app.route("/db/session/execute", methods=["POST"])
@_api
def db_session_execute():
    """在会话中执行 SQL，返回列名与结果行。"""
    data = request.get_json(silent=True) or {}               # 读 JSON 请求体；silent=True 让非法/空体返回 None 再兜底成 {}
    session_id = data.get("session_id") or ""                # 会话 ID，缺失时空串（后续会因找不到会话而报错）
    sql = data.get("sql") or ""                              # 要执行的 SQL
    args = data.get("args")                                  # SQL 参数列表，可为 None
    if not sql:                                              # SQL 为空属于调用方错误
        raise ValueError("缺少 sql 参数")                     # 抛异常，由 _api 转成 500 JSON
    columns, rows, rowcount, wrote = execute_on_session(session_id, sql, args)   # 真正执行
    return {"ok": True, "columns": columns, "rows": rows, "rowcount": rowcount, "wrote": wrote}   # 返回列名、行、影响行数、是否写过


@app.route("/db/session/commit", methods=["POST"])
@_api
def db_session_commit():
    """提交会话事务。"""
    data = request.get_json(silent=True) or {}               # 读 JSON 请求体
    return {"ok": True, "wrote": commit_session(data.get("session_id") or "")}   # 提交并回传是否写过库


@app.route("/db/session/rollback", methods=["POST"])
@_api
def db_session_rollback():
    """回滚会话事务。"""
    data = request.get_json(silent=True) or {}               # 读 JSON 请求体
    rollback_session(data.get("session_id") or "")           # 执行回滚
    return {"ok": True}                                      # 只回传成功标志


@app.route("/db/session/close", methods=["POST"])
@_api
def db_session_close():
    """关闭会话并释放数据库连接。"""
    data = request.get_json(silent=True) or {}               # 读 JSON 请求体
    close_session(data.get("session_id") or "")              # 关闭会话（幂等）
    return {"ok": True}                                      # 只回传成功标志


if __name__ == "__main__":
    threading.Thread(target=_reap_idle_sessions, daemon=True).start()   # 启动守护线程做空闲会话回收，主进程退出时自动结束
    print(f"数据库服务已启动： http://127.0.0.1:{DB_SERVICE_PORT}")       # 打印监听地址，便于确认端口
    app.run(host=HOST, port=DB_SERVICE_PORT, threaded=True)             # 启动开发服务器；threaded=True 支持并发请求
