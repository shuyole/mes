# 10 · 后端代码讲解（一）：common.py —— 两个服务共用的基础模块

> 文件位置：`backend/common.py`（约 1195 行）
> 被谁用：`server.py`（6021）和 `api_server.py`（8080）都 `from common import ...`。
> 一句话定位：**全项目的「地基」**——路径常量、配置加载、数据库（MySQL/SQLite 双兼容）、
> 建表初始化、会话与权限装饰器、用户/工单/日志数据访问、7 工位与产品主数据，全部在这里。

---

## 1. 文件顶部：路径与配置（第 1~101 行）

### 1.1 五个绝对路径常量

```python
BACKEND_DIR  = backend/ 目录（common.py 所在目录）
PROJECT_DIR  = 项目根目录（backend 的上一级）
FRONTEND_DIR = 根目录/frontend（Templates 与 static）
CONFIG_DIR   = 根目录/config
DATA_DIR     = 根目录/data
```

用 `os.path.abspath(__file__)` 推导，服务从任何工作目录启动都能找到模板、配置和数据库。

### 1.2 load_config()：读取 config.json 并与默认值合并

- 内置一份默认配置：host=0.0.0.0、前端 6021、后端 8080、secret_key、
  database（type=auto，默认连 localhost MySQL，root/123456/mes_db）、plc（127.0.0.1:502）。
- 配置文件存在时：顶层键直接覆盖；`database`、`plc` 两个**子字典做二级合并**
  （只覆盖文件里写了的字段），所以 config.json 可以只写一两行。
- 文件缺失或字段不全不报错，默认值兜底。

加载后展开成全局变量供业务代码直接 import：

| 全局变量 | 含义 |
|---|---|
| `CONFIG` / `CONFIG_PATH` | 合并后的完整配置 / config.json 绝对路径（改 PLC 地址要写回它） |
| `DB_CONFIG` | pymysql.connect 用的连接参数（charset 固定 utf8mb4） |
| `PLC_CONFIG` | PLC 的 ip/port（port 强制 int，防止 JSON 读成字符串） |
| `FRONTEND_PORT` / `BACKEND_PORT` | 6021 / 8080 |
| `ROOT_ADMIN_USERNAME` | `"admin"`，唯一能删除/保护其他管理员的内置账号 |
| `DB_ENGINE` | `"mysql"` 初值，detect_engine() 后改成实际引擎 |
| `SQLITE_PATH` | data/mes.db，MySQL 不可用时的兜底库 |

---

## 2. 会话代次与仿真倍速（第 104~159 行）

- `_load_session_epoch()`：读 `data/.epoch`（16 字节随机十六进制）。文件不存在就生成并写盘，
  写完还回读一次（防止两个进程首次同时启动各写一份）。**两个 Flask 进程读到同一个值，
  才能互相承认对方签发的登录 Cookie**；删掉这个文件重启，所有会话立即失效。
- `SESSION_EPOCH`：模块加载时读出的代次值，是会话指纹三要素之一。
- 用户短缓存：`_user_cache` + `_user_cache_lock`，TTL 3 秒。页面每 2~3 秒轮询一次，
  若每次都查 users 表压力太大，命中缓存直接返回副本（`dict(...)` 防止调用方改缓存）。
- `SIMULATION_SPEED` + 一把锁 + `get_sim_speed()/set_sim_speed(speed)`：
  全局仿真倍速（1/2/5/10x，也接受 0.5~20 之间的值），仿真线程每个循环读取它决定 sleep 时长。

---

## 3. 工业主数据：工位、产品、节拍（第 161~353 行）

### 3.1 STATION_DEFS：7 个工位的完整定义（全项目最重要的常量）

每个工位一个字典，字段非常「工业」：

- `code` ST01…ST07、`name` 中文名、`full_name` 带工号的全称（如「自动上料工作站 (OP10)」）、
  `step` 工艺序号、`tone` 主题色名、`cycle_sec` 单件节拍秒数、
  `plc_address` 寄存器地址（10~16）、`role` 职能（上料/装配/锁附/打标/检测/下料）。
- `sensors`：3 个传感器信号点表（名称 + DI 引脚，如 DI0.0 载具定位到位光电）。
- `params`：3 条关键工艺参数（实测值 + 标准/公差，如真空度 -82.5kPa，标准 <-75.0kPa）。
- `qc_criteria`：该工位的质量判定标准文字。

派生出 `STATION_COUNT = 7`、`LAST_STATION_NAME = "自动下料"`。

### 3.2 PRODUCTS：4 种无线充产品

code（WC-10W / WC-15W / WC-MAG / WC-PAD）、名称、型号、整线理论节拍、功率、线圈数、简介。
工单页下拉框、配方页表格、设置页主数据都从这里取。

### 3.3 PLAN 与 PROCESS_STEPS

- `PLAN`：课件用节拍计算数据——客户需求 145 件/天、双班、每班净可用 27000 秒，
  算出 Takt Time = 54000 ÷ 145 = **372 秒/件**，配方页直接展示这条公式。
- `PROCESS_STEPS`：治具板上的 6 步装配工艺（治具准备→主板→后盖→螺丝→打标→检测）。

### 3.4 make_line_state()：产线运行时状态的初始结构

返回一个「未下发工单」的状态字典：running/alarm/order_id/order_no/product_name/
quantity/completed_qty/ng_qty/station_index（当前工位下标）/piece_progress（当前工位单件百分比）/
stations（7 个工位，每个带 status、processed_qty、current_order_no）/robot（机械臂状态）/last_update。
api_server 用它初始化真实产线 LINE 和虚拟产线 VIRTUAL；前端在 8080 不可达时也用同样结构兜底渲染。

---

## 4. 数据库层：MySQL / SQLite 一套代码兼容（第 386~576 行）

### 4.1 小工具

- `_as_int(value)`：把 SUM 聚合结果转 int。空表 SUM 是 None，MySQL 下还可能是 Decimal，统一归零。
- `json_safe(rows)`：把查询结果转成 jsonify 能序列化的普通 dict 列表
  （Decimal→int；datetime→"YYYY-MM-DD HH:MM:SS"；date→"YYYY-MM-DD"）。

### 4.2 引擎探测与建连

- `detect_engine()`：
  - config 写死 `sqlite` → 直接用 SQLite，确保 data 目录存在；
  - 写死 `mysql` → 连不上直接抛异常（不静默降级）；
  - 默认 `auto` → 先试连 MySQL（**不带库名**、connect_timeout=3 秒），连上就用 MySQL，
    连不上自动回退 SQLite 并打印原因。
- `get_db_connection()`：SQLite 用 `check_same_thread=False`（后台仿真线程也要写库）、
  `row_factory=sqlite3.Row`（可按列名取值）、timeout=10；MySQL 返回 pymysql 连接。
- `ensure_database()`：MySQL 模式下执行 `CREATE DATABASE IF NOT EXISTS ... utf8mb4`，首次部署自动建库。

### 4.3 SQL 方言兼容：prepare_sql() 与 CompatCursor

业务代码**统一只写 MySQL 语法**，到 SQLite 由这一层自动改写：

| MySQL 写法 | SQLite 改写 |
|---|---|
| 反引号 `` ` `` 包标识符 | 直接删除 |
| `%s` 占位符 | 改成 `?` |
| `INT AUTO_INCREMENT PRIMARY KEY` | `INTEGER PRIMARY KEY AUTOINCREMENT` |
| `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | `TEXT DEFAULT (datetime('now','localtime'))`（修正 UTC 问题） |
| `DATE_SUB(CURDATE(), INTERVAL 6 DAY)` | `date('now','-6 days')` |

`CompatCursor` 是游标适配器：
- `execute()` 先过一遍 `prepare_sql()`，并通过 SQL 前缀判断本次是否为写操作
  （INSERT/UPDATE/DELETE/REPLACE），在 `self.wrote` 打标记；
- `fetchone/fetchall` 把 sqlite3.Row / dict / 元组统一成 dict（dict_mode=True 时）。

### 4.4 db_cursor() 上下文管理器（全项目访问数据库的统一入口）

用法固定为 `with db_cursor(True) as cursor:`，它负责：

1. 建连接、包一层 CompatCursor（MySQL 且 dict_cursor=True 时用 DictCursor）；
2. 块内正常结束 → `commit()`；抛异常 → `rollback()` 后重新抛出；
3. **仅当本次事务包含写操作**，提交后调用 `sync_to_project_files()` 导出 JSON 快照；
4. finally 里必定关闭游标和连接，防止连接泄漏。

### 4.5 表结构升级与 upsert

- `ensure_column(cursor, table, column, definition)`：列不存在才 `ALTER TABLE ADD COLUMN`，
  两种库查询列的方式不同（SQLite 用 PRAGMA table_info，MySQL 用 SHOW COLUMNS LIKE）。
  作用：老版本数据库平滑升级，可重复执行。
- `upsert(cursor, table, unique_col, data)`：按唯一列「存在则更新、不存在则插入」。
  SQLite 用 `ON CONFLICT ... DO UPDATE SET excluded.x`，
  MySQL 用 `ON DUPLICATE KEY UPDATE ... VALUES(x)`。值全部走参数绑定，无注入风险。

---

## 5. 项目文件双向同步（第 579~693 行）

为了「换数据库不丢教学数据」，项目维护了一套 JSON 镜像：

- 快照目录 `data/sync/`，6 个文件：users / production_orders / work_records /
  production_logs / line_stations / products 各一个 `.json`。
- `sync_to_project_files()`：写库事务提交后触发，整表 SELECT 导出。
  - 用线程本地变量 `_SYNC_GUARD` + 进程锁防重入（导出内部读库不能再次触发出导）；
  - 先写 `.tmp` 临时文件再 `os.replace` 原子替换，避免读到写一半的 JSON；
  - 任何异常只打印告警，不影响主业务。
- `sync_from_project_files()`：启动时若发现 `data/.last_db` 记录的库签名
  （host:database）与当前不一致（说明切换了数据库），就把 JSON 用 `REPLACE INTO` 回填新库，幂等。
- `_db_signature()/_read_last_db_sig()/_write_last_db_sig()`：签名的计算、读盘、写盘。

---

## 6. init_db()：数据库初始化总入口（第 769~939 行）

执行顺序：

1. `detect_engine()` 探测引擎 → `ensure_database()` 建库；
2. `CREATE TABLE IF NOT EXISTS` 建 6 张表（统一 MySQL 语法，SQLite 自动改写）；
3. 对老库逐列 `ensure_column` 补字段（工单表补 product_code/completed_qty/ng_qty/priority/
   due_date/progress/current_station/started_at/finished_at/remark/created_by；
   日志表补 category；用户表补 student_id）；
4. users 表里没有 admin 时插入内置管理员 **admin / ADMIN**（只建一次，不覆盖改过的密码）；
5. 用 upsert 把代码里的 PRODUCTS 和 STATION_DEFS 同步进 products / line_stations 表，
   并 `DELETE` 掉代码中已不存在的工位，保证库与代码一致；
6. 检测数据库签名变化 → 必要时 JSON 回填 → 再导出一次快照 → 写新签名。

整个函数幂等，两个服务启动时都会安全地各执行一次。

---

## 7. 日志与统计查询（第 942~983、1152~1195 行）

- `add_log(message, order_no="", level="INFO", category="sys")`：往 production_logs 插一条。
  level 取 INFO/WARN/ALARM；category 分 sys（登录等系统事件）和 line（工单/节拍/工位事件）。
  写失败只打印，不打断主流程。
- `fetch_logs(category=None, limit=30, levels=None)`：按类别/级别动态拼 WHERE 查最近日志，
  并把 created_at 统一截成 `HH:MM:SS` 给页面显示。
- `order_stats(include_orders=True, order_limit=None)`：一条聚合 SQL 算出
  总工单数、待生产/生产中/已完成数量、计划总量、累计合格、累计不良，
  并计算**一次合格率** `合格 ÷ (合格+不良)`（保留 1 位小数）；
  需要时再按优先级、创建时间倒序拉工单明细（可限条数，首页只取最近 8 条）。

---

## 8. 会话、登录与权限装饰器（第 986~1128 行）

### 8.1 会话指纹

`session_signature(user) = sha256(f"{SESSION_EPOCH}:{用户名}:{密码哈希}")`，
登录时存进 `session["sign"]`。指纹只依赖 `.epoch` 文件和数据库内容，所以两个进程算出来一致；
改密码或换代会话代次后，旧指纹对不上，会话立即失效。

### 8.2 @login_required

包装任意视图函数，每次请求执行：

1. session 里没有 logged_in → API 请求（路径以 /api/ 开头）返回 401 JSON，页面请求 302 到登录页；
2. 用 `get_user()` 取用户，账号被删 / 被停用 / 指纹不匹配 → 清 session，同样 401 或跳登录；
3. 通过后用数据库里的**最新值**回写 session 的 role/display_name/user_id
   （管理员刚调整过角色，下一次请求立即生效），再调用原视图。

### 8.3 @admin_required

在 login_required 之上再判断 `session["role"] == "admin"`；
非管理员访问 API 或 POST/DELETE → 403 JSON，普通页面 GET → `abort(403)` 渲染 forbidden.html。

### 8.4 用户与登录数据访问

- `is_admin()`：只看 session 里的 role，不再查库（控制类接口高频调用）。
- `invalidate_user_cache()`：改完用户信息后清短缓存。
- `get_user(username)`：缓存优先（TTL 3 秒，返回副本），未命中查库并回填。
- `verify_login(username, password)`：`(user, code, msg)` 三元组——
  成功 code=0；账号密码错误 code=-2；账号停用 code=-3。供网页登录和 API 登录共用。
- `list_users()`：全部用户列表（不返回密码哈希）。
- `sign_in(user)`：登录成功后写 session（logged_in/user_id/username/display_name/role + sign 指纹）。

---

## 9. 工单号生成（第 1131~1149 行）

`next_order_no()` 生成形如 `WC20260920-001` 的单号：
前缀取当天日期，查当天最大流水号 +1（末 3 位），跨天自动从 001 开始；
历史脏数据末三位不是数字则从 001 重新开始。新建工单表单默认就填这个建议单号。

---

## 10. 学习本文件时最该看懂的 5 个设计

1. **双进程共享一套基础设施**：靠同一个 config.json、同一个 secret_key、同一个 .epoch 文件，
   两个 Flask 进程的会话与配置天然互通。
2. **一套 SQL 跑两种数据库**：prepare_sql + CompatCursor 把方言差异关在底层，业务层零分支。
3. **所有数据库访问走 with db_cursor()**：自动提交/回滚/关连接，写操作后自动导出 JSON 快照。
4. **权限是装饰器 + 模板分支双层控制**：后端装饰器是真正的安全边界，模板 {% if %} 只负责界面隐藏。
5. **主数据在代码里、不在数据库里**：STATION_DEFS / PRODUCTS 是唯一事实源，
   每次启动 upsert 进库，改工艺只改代码即可。
