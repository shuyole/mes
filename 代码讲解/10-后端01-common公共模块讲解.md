# 10 · 后端代码讲解（一）：common.py —— 三个服务共用的基础模块

> 文件位置：`backend/common.py`（约 834 行）
> 被谁用：`db_server.py`（6060）、`api_server.py`（8080）、`static_server.py`（6021）
> 三个后端进程都 `from common import ...`。
> 一句话定位：**全项目的「地基」**——路径常量、配置加载、业务常量（7 工位/产品/计划/工艺）、
> 会话与权限装饰器、用户/工单/日志等业务函数，以及**把 SQL 通过 HTTP 转发给 6060 数据库服务**的客户端。
> 重要变化：本文件已不再 `import pymysql` / `import sqlite3`，也不再持有任何数据库连接。

---

## 1. 文件顶部：路径与配置（第 1~109 行）

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

- 内置一份默认配置：host=0.0.0.0、前端 6021、后端 8080、数据库服务 127.0.0.1:6060、secret_key、
  database（type=auto，默认连 localhost MySQL，root/123456/mes_db）、plc（127.0.0.1:502）。
- 配置文件存在时：顶层键直接覆盖；`database`、`plc` 两个**子字典做二级合并**
  （只覆盖文件里写了的字段），所以 config.json 可以只写一两行。
- 文件缺失或字段不全不报错，默认值兜底。

加载后展开成全局变量供业务代码直接 import：

| 全局变量 | 含义 |
|---|---|
| `CONFIG` / `CONFIG_PATH` | 合并后的完整配置 / config.json 绝对路径（改 PLC 地址要写回它） |
| `DB_CONFIG` | 数据库连接参数（charset 固定 utf8mb4）；现在由 6060 数据库服务展开使用，本模块只透传 |
| `PLC_CONFIG` | PLC 的 ip/port（port 强制 int，防止 JSON 读成字符串） |
| `FRONTEND_PORT` / `BACKEND_PORT` | 6021 / 8080 |
| `ROOT_ADMIN_USERNAME` | `"admin"`，唯一能删除/保护其他管理员的内置账号 |
| `DB_ENGINE` | `"mysql"` 初值；`init_db()` 把 6060 数据库服务探测到的实际引擎回写到这里，仅供 `/api/config` 展示 |
| `DB_SERVICE_HOST` / `DB_SERVICE_PORT` / `DB_SERVICE_URL` | 数据库服务地址：读 config.json 的 `db_service.host/port`，默认 `127.0.0.1:6060` |
| `DB_SERVICE_TIMEOUT` | 单次调用数据库服务的超时秒数（默认 10），避免请求线程被无响应的服务无限挂住 |

---

## 2. 会话代次与仿真倍速（第 112~159 行）

- `_load_session_epoch()`：读 `data/.epoch`（16 字节随机十六进制）。文件不存在就生成并写盘，
  写完还回读一次（防止多个服务首次同时启动各写一份）。**各后端进程读到同一个值，
  才能互相承认对方签发的登录 Cookie**；删掉这个文件重启，所有会话立即失效。
- `SESSION_EPOCH`：模块加载时读出的代次值，是会话指纹三要素之一。
- 用户短缓存：`_user_cache` + `_user_cache_lock`，TTL 3 秒。页面每 2~3 秒轮询一次，
  若每次都查 users 表压力太大，命中缓存直接返回副本（`dict(...)` 防止调用方改缓存）。
- `SIMULATION_SPEED` + 一把锁 + `get_sim_speed()/set_sim_speed(speed)`：
  全局仿真倍速（1/2/5/10x，也接受 0.5~20 之间的值），仿真线程每个循环读取它决定 sleep 时长。

---

## 3. 工业主数据：工位、产品、节拍（第 161~392 行）

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

## 4. 数据库访问：SQL 经 HTTP 转发给 6060 数据库服务（第 394~577 行）

> 本节是本次架构调整的重点：**数据库驱动、连接、SQL 方言兼容全部搬到了 `db_server.py`**，
> common.py 只留「客户端」——把 SQL 包成 JSON 发给 6060，再把结果行还原成 dict/tuple。
> 因此 routes/ 与 core/ 里的业务代码完全不用改，仍然照写 `with db_cursor(True) as cursor:`。

### 4.1 小工具

- `_as_int(value)`：把 SUM 聚合结果转 int。空表 SUM 是 None，MySQL 下还可能是 Decimal，统一归零。
- `json_safe(rows)`：把查询结果转成 jsonify 能序列化的普通 dict 列表
  （Decimal→int；datetime→"YYYY-MM-DD HH:MM:SS"；date→"YYYY-MM-DD"）。
  数据库服务侧已经转换过一次（见 13 号文档），这里是本进程的二次兜底。

### 4.2 客户端基础设施：DBServiceError / _db_request() / db_service_alive()

- `DBServiceError(RuntimeError)`：数据库服务不可达或返回 `ok=false` 时抛出的统一异常，
  调用方仍按「数据库报错」处理，业务层的 try/except 完全不需要知道背后是一次 HTTP 调用。
- `_db_request(path, payload=None, method="POST", timeout=DB_SERVICE_TIMEOUT)`：
  用 `urllib.request` 请求 `DB_SERVICE_URL + path`，请求体是 JSON；
  服务返回 HTTP 错误码时优先读响应体里的 `error` 说明，连不上则抛出带地址的 `DBServiceError`。
- `db_service_alive(timeout=1.0)`：GET `/db/health` 探活，启动时用它判断 6060 是否就绪。

### 4.3 RemoteCursor：长得和数据库游标一样的远程游标

`RemoteCursor(dict_mode=False)` 在客户端重新实现了「游标」这套接口：

- `execute(sql, args)`：首次执行时先 `POST /db/session/open` 拿到 `session_id`，
  再把 `{session_id, sql, args}` 发给 `/db/session/execute`；
  服务端一次性返回 `columns / rows / rowcount / wrote`，本类把结果行缓存在内存里按需消费，
  并累积 `wrote`（本次事务有没有写过库）；
- `fetchone()` / `fetchall()`：从内存缓冲取行；`dict_mode=True` 时按 `columns` 拼成 dict
  （相当于原来 MySQL 的 DictCursor），否则保持元组；
- `close()`：`POST /db/session/close` 释放服务端的会话与数据库连接。

### 4.4 db_cursor() 上下文管理器（全项目访问数据库的统一入口）

用法和事务语义与改造前**完全一样**：

```python
with db_cursor(True) as cursor:          # True：结果行按列名取，返回 dict
    cursor.execute("SELECT * FROM users WHERE username=%s", (name,))
    row = cursor.fetchone()              # {'id': 1, 'username': 'admin', ...}
```

内部流程：

1. 创建一个 `RemoteCursor(dict_mode=dict_cursor)`（此时还没有真正占用数据库连接）；
2. 块内正常结束 → **仅当本次有写操作**才 `POST /db/session/commit`（纯查询省一次网络往返）；
3. 抛异常 → `POST /db/session/rollback` 后把异常继续上抛（避免只写一半的数据残留）；
4. finally 里必定 `POST /db/session/close`，防止数据库连接泄漏。

---

## 5. 已搬到 db_server.py 的数据库实现（原 common.py 第 386~693 行的内容）

下面这些东西**已不在 common.py 里**，全部搬到了数据库服务 `backend/db_server.py`
（详细讲解见 13 号文档）；对照旧版 common.py 或旧讲义时按这张表找新位置：

| 原 common.py 中的东西 | 现在的位置与名字 |
|---|---|
| `detect_engine()`、`get_db_connection()`、`ensure_database()` | `db_server.py` 同名函数，探测结果写入该进程的全局 `ENGINE` |
| `prepare_sql()`、`CompatCursor`（MySQL 语法 → SQLite 方言改写） | `db_server.py` 同名实现，SQLite 降级逻辑仍在这一层 |
| `ensure_column()`、`upsert()` | `db_server.py` 同名函数，建表补列与主数据 upsert 都在服务端执行 |
| `sync_to_project_files()`、`sync_from_project_files()`、`_db_signature()` 等 | `db_server.py` 同名函数，负责 `data/sync/*.json` 快照的导出与换库回填 |
| `init_db()` 的建库建表实现 | 更名为 `db_server.py` 的 `init_database()`；common.py 的 `init_db()` 只是它的 HTTP 调用方 |
| `SQLITE_PATH`（data/mes.db 兜底库路径） | `db_server.py` 的模块级常量 |

结果就是：**全项目只有 6060 这一个进程 import pymysql / sqlite3 并持有数据库连接**。
快照文件的生成时机也随之改变：不再由本进程在提交后触发，而是由数据库服务在
「会话提交且本次有写操作」时导出（见 13 号文档）。

---

## 6. init_db()：向数据库服务请求初始化（第 567~576 行）

`init_db()` 现在只做两件事：向数据库服务发一次 `POST /db/init`，再把返回的引擎名写回模块级
`DB_ENGINE`（供 `/api/config` 展示）。建库、建表、补列、写入 admin / PRODUCTS / STATION_DEFS
基础数据这些事，全部在 6060 进程里由 `init_database()` 完成（原 init_db 的实现，见 13 号文档）。

- 函数仍然幂等，多个服务启动时各调用一次都安全；
- 数据库服务不可达时抛 `DBServiceError`，由调用方按原有重试策略处理（api_server 是最多重试 6 次）；
- `data/sync/*.json` 快照与换库回填也不再由本进程负责，改由数据库服务在提交写事务时触发。

---

## 7. 日志与统计查询（第 579~623、791~834 行）

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

## 8. 会话、登录与权限装饰器（第 625~768 行）

### 8.1 会话指纹

`session_signature(user) = sha256(f"{SESSION_EPOCH}:{用户名}:{密码哈希}")`，
登录时存进 `session["sign"]`。指纹只依赖 `.epoch` 文件和数据库内容，所以各后端进程算出来一致；
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

## 9. 工单号生成（第 770~789 行）

`next_order_no()` 生成形如 `WC20260920-001` 的单号：
前缀取当天日期，查当天最大流水号 +1（末 3 位），跨天自动从 001 开始；
历史脏数据末三位不是数字则从 001 重新开始。新建工单表单默认就填这个建议单号。

---

## 10. 学习本文件时最该看懂的 5 个设计

1. **多进程共享一套基础设施**：靠同一个 config.json、同一个 secret_key、同一个 .epoch 文件，
   各后端进程（6060/8080/6021）的会话与配置天然互通。
2. **数据库只有一个入口**：所有进程都用 `with db_cursor()` 把 SQL 交给 6060 数据库服务，
   驱动、连接、方言兼容（MySQL→SQLite 降级）、快照导出都收在服务端，业务层零分支、零感知。
3. **客户端用法与直连数据库完全一致**：`db_cursor(True)` 里照写 execute/fetchone/fetchall，
   提交/回滚/关连接的语义没变，所以这次改造 routes/ 与 core/ 一行业务代码都不用改。
4. **权限是装饰器 + 模板分支双层控制**：后端装饰器是真正的安全边界，模板 {% if %} 只负责界面隐藏。
5. **主数据在代码里、不在数据库里**：STATION_DEFS / PRODUCTS 是唯一事实源，
   每次启动由数据库服务 upsert 进库，改工艺只改代码即可。
