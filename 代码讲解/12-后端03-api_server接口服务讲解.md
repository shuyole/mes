# 12 · 后端代码讲解（三）：api_server.py —— 接口服务 + PLC 通讯 + 产线仿真（8080）

> 文件位置：`backend/api_server.py`（约 1632 行，全项目最大的文件）
> 启动：`python api_server.py`
> 一句话定位：**系统的运行时大脑**。提供全部 `/api/*` JSON 接口，维护 Modbus TCP 通讯，
> 并在后台线程里持续推进真实/虚拟两条产线的仿真。

---

## 1. 应用初始化与全局状态（第 1~93 行）

```python
app = Flask("mes_api")                 # 纯 JSON 服务，不挂模板和静态目录
app.secret_key = 与 server.py 相同      # 共用会话
CORS(app, origins="*", supports_credentials=True)   # 跨端口(6021→8080)且要带 Cookie
```

### 两把锁

- `plc_lock = Lock()`：pymodbus 客户端非线程安全，同一时刻只允许一个线程读/写 PLC；
- `line_lock = RLock()`：仿真线程与 HTTP 请求都会读写产线状态，用**可重入锁**
  （持锁函数内部可能再调用需要同一把锁的函数）保证不会读到推进到一半的中间状态。

### PLC_STATE：PLC 运行时缓存字典

由读写函数和轮询线程共同维护，供 `/api/plc_status` 与 HMI 页面展示：
connected（连接状态）、last_read_value/time、last_write_value/time、error_msg、
total_reads/total_writes、registers（地址→值快照）、last_fail_ts（失败时间戳，用于冷却）。

### 两条产线 + 两份内存数据

- `LINE`：真实产线，只有 PLC 在线时才推进，工位指示灯跟着联机状态走；
- `VIRTUAL`：本地虚拟产线，不依赖 PLC 也能演示；
- `VIRTUAL_LOGS / VIRTUAL_RECORDS`：虚拟产线的日志和过站记录，**只存内存**（不写库、不写 PLC），
  新的在前，最多各保留 40/30 条；
- `PLC_REQUIRED_MSG`：未连接 PLC 时控制真实产线的统一报错文案。

---

## 2. 配置与 PLC 地址管理（第 96~134 行）

- `save_config()`：把 CONFIG 写回 config.json（utf-8、缩进 2），重启后地址不丢。
- `apply_plc_address(ip, port, reconnect=True)`：
  校验 IP 非空、端口是 1~65535 的数字 → 更新 PLC_CONFIG/CONFIG → save_config()
  → `virtual_plc_manager.ensure_virtual_plc_for_ip(ip)`：本机回环地址自动拉起虚拟 PLC，
  其他 IP 自动停掉虚拟 PLC → 需要重连时在锁内把 connected 置 False、清空冷却和寄存器快照，
  下一轮轮询即按新地址连接。返回 `(bool, 提示文案)`。

---

## 3. 工单进度的纯业务函数（第 137~297 行）

- `line_run_text(state)`：把产线状态拼成顶栏同款一句话（当前工单｜产品｜进度｜节拍｜工位）。
- `update_order_progress(order_id, **fields)`：动态拼 `UPDATE ... SET k=%s ...`。
  列名来自内部关键字（非外部输入），值走占位符绑定；fields 为空不执行 SQL。
- `ORDER_STATUSES = (待生产, 生产中, 暂停, 返工, 已完成)`：状态白名单。
- `_order_view(order)`：把数据库工单行整理成前端进度控件需要的字典，
  统一钳制完成数不超过计划量、已完成强制 100%、其余按存储的 progress 或完成数反推百分比。
- `apply_manual_progress(...)`：**教学用手动改进度的核心**（progress.js 拖拽/加减/切状态最终调它）：
  - 支持三种输入：绝对完成数 completed_qty、相对增减 delta（在接口层换算）、百分比 progress；
  - 处理五种状态联动：100%→已完成；已完成但数量不满→返工（按 rework_qty 退回件数，默认 1）；
    有完成数还是待生产→自动转生产中；返工/生产中满量又自动收敛回已完成；
  - 根据完成数推算当前所处工位（按 7 工位均分映射到 STATION_DEFS）；
  - 同步停掉内存里对应产线、写开始/完成时间戳；若正好是当前产线上的单且标记完成，
    调 `finish_current_order()` 做停线收尾，否则只更新数据库；最后重新查库返回最新视图。

---

## 4. Modbus TCP 读写层（第 300~441 行）

### 4.1 版本兼容封装

- `_modbus_read(client, address, count)`：pymodbus 不同版本从站参数名不同
  （slave=1 关键字有的版本不接受），两种调用写法依次尝试；
- `_modbus_write(client, address, value)`：同样 try/except 兼容两种 write_register 签名；
- `plc_client()`：每次都 new 一个 ModbusTcpClient（不在此连接），
  避免长连接被对端断开后残留坏状态。

### 4.2 连接冷却机制

- `PLC_RETRY_COOLDOWN = 5` 秒；
- `_plc_in_cooldown()`：未连接且距上次失败不足 5 秒时直接返回，避免 PLC 离线时
  每个 HTTP 请求、每个仿真节拍都卡在 TCP 连接超时上；
- `_mark_plc_disconnected(message)`：在锁内记失败时间戳、置离线、存错误信息；
- `_close_modbus(client)`：关连接并吞掉关闭异常，避免掩盖真正的读写错误。

### 4.3 写：write_plc_map(values) / write_to_plc(value, address=0)

一次连接批量写多个保持寄存器（减少连接开销），成功后更新 PLC_STATE 的最近写值/时间/
累计写次数；冷却期、连接失败、写入异常都返回 False。单寄存器写是它的便捷封装
（地址 0 约定为产线启停命令字）。

### 4.4 读：read_from_plc(address=0, count=1)

连接 → 读保持寄存器 → 成功则更新 connected、最近读值/时间、累计读次数、
registers 快照（逐地址写入）；count=1 返回单值，count>1 返回列表；
冷却期/连接失败/Modbus isError 一律返回 None。

---

## 5. 产线状态快照（第 444~519 行）

- `_copy_line(state)`：持锁状态下把产线字典复制成可 JSON 化的普通字典
  （stations/robot 逐元素浅拷贝），并顺手算出整体 progress 百分比。
- `_freeze_offline(data)`：PLC 未连接时把所有工位强制改成「离线」、机器人显示离线，
  页面上灯不再闪烁——没有硬件时绝不假装设备在动。
- `snapshot_line(state=LINE, plc_gate=False)`：锁内复制 → 补 plc_connected 和 mode
  （real/virtual）→ plc_gate=True 且未联机时走冻结逻辑。
- `snapshot_virtual()`：虚拟产线快照，额外附带内存里的最近 20 条日志、30 条过站记录，
  并强制 plc_connected=True（虚拟页永远可演示）。
- `reset_stations(keep_qty, state)`：工位与机器人恢复初始（空闲/HOME/清报警）；
  keep_qty=True 时保留各工位累计过站数（换单复位场景）。
- `_remember_virtual(kind, payload)`：虚拟日志/记录插入内存列表头部并截断到 40 条。

---

## 6. 工单下发、推进与完工（第 529~623 行）

### 6.1 start_line_order(order, state, write_plc=True)

把工单下发到某条产线：真实产线要求 PLC 已连接；正在执行别的单则拒绝。
持锁设置工单信息、复位工位、ST01 置「运行」、机器人切到上料动作；
锁外再写寄存器 `{0:1 运行, 1:1 ST01, 2:已完成数, 6:1 机械臂运行}` 并记日志
（虚拟产线只记内存，不写 PLC/数据库）。

### 6.2 完工收尾

- `_finish_line_state(state)`：持锁把内存产线收成「本工单完成」（停线、机器人回 HOME、
  工位标完成），返回需要落库的快照；
- `_persist_finish(payload)`：**在锁外执行**——更新工单为已完成 100%、写日志、
  写一组完工寄存器（HR0=2、HR1=7、产量/合格/不良、HR6=0）；
- `finish_current_order(expected_id)`：可选地校验「产线上确实是这一单」再收尾，
  避免误完成别的单。

### 6.3 过站记录

`record_station_pass(station, ok, order_id, order_no)`：向 work_records 插一条
（合格 1 件或不良 1 件）；没有在制工单时跳过，不产生无主记录。

---

## 7. 仿真主循环（第 656~826 行）

### 7.1 为什么要 jobs 队列

`_run_jobs(jobs)` 依次执行推迟到锁外的 I/O 任务（写库、写 PLC、写日志），单个失败只打印不影响后续。
**所有慢 I/O 都不能在持有 line_lock 时做**，否则会卡住页面轮询，所以用 functools.partial
把「要做什么」收集成 jobs，解锁后统一执行。

### 7.2 _advance_line_locked(jobs, state, write_plc, persist)：推进一拍

调用方必须已持锁。逻辑：

1. 未运行/报警/无工单 → 直接返回；
2. 当前工位节拍百分比 += `100/cycle_sec`（ST01 节拍 3 秒就约每拍涨 33%），机器人移到该工位；
3. 单件未满 100% → 本拍结束；
4. 满 100% → 该工位 processed_qty+1、状态「完成」，写一条过站记录
   （persist=True 写库，False 写虚拟内存）；最后一个工位每第 17 件模拟一次不良；
5. 不是最后工位 → station_index+1，下一工位置运行，写 HR1，记日志；
6. 是最后工位 → 合格数或不良数 +1，更新工单进度（最多先记 99%）、写产量寄存器，
   工位序列归零重新开始；全部数量完成则 `_finish_line_state` + 落库完工，
   否则 ST01 重新置运行继续下一件。

### 7.3 _mirror_virtual_to_line()：虚拟画面镜像到真实产线

PLC 在线但真实产线没有在制工单时，读 LINE 的页面（看板/HMI/ST01）会显示空闲。
此函数把 VIRTUAL 的工位/机器人/产量/报警**画面字段**复制给 LINE，但**不复制 running/order_id**，
保证真实产线既不会被误推进、也不会误写库，视觉上又能与虚拟仿真联动。

### 7.4 line_simulator() 守护线程

`while True`：按全局倍速 sleep（0.8 秒 ÷ 倍速，下限 0.06 秒）→ 持锁：

- PLC 在线：推进真实产线（写 PLC + 落库）；推进虚拟产节拍（写 PLC、不落库）；镜像到 LINE；
- PLC 离线：只推进虚拟产线（不写 PLC、不落库）。

解锁后 `_run_jobs` 执行本拍收集的所有 I/O。

---

## 8. PLC → 产线反向控制通道（第 829~949 行）

### 8.1 HR0 边沿触发 _apply_plc_register_control(registers)

模块级 `_LAST_HR0` 记录上一次读到的 HR0，只在值**跳变**时动作（避免与产线自己写的 HR0 打架）；
首次读到只建立基线不动作：

| 跳变 | 动作 |
|---|---|
| 任意 → 3 | 虚拟产线注入急停故障（报警、停线、当前工位标故障） |
| 3 → 0/1 | 撤销故障字：清报警、复位工位；若到 1 则继续运行 |
| 1 → 0 | 暂停（机器人待机） |
| 0/其他 → 1 | 有在制工单就继续；没有就自动下发一单 3 件的虚拟演示工单 VIR-HHMMSS |

这样在 HMI/上位机一侧写 HR0，也能反过来操控虚拟产线，形成寄存器↔产线双向联动。

### 8.2 poll_plc_status() 守护线程

每 2 秒：`read_from_plc(0, 8)` 读 0~7 号寄存器刷新 PLC_STATE →
连接成功时把寄存器快照交给 `_apply_plc_register_control` 处理边沿。
接口层（/api/plc_status）只读缓存不直接连 PLC，避免 HMI 轮询和仿真写寄存器互相阻塞。

---

## 9. HTTP 接口清单（第 952 行起）

### 9.1 登录与会话

| 方法 路径 | 权限 | 作用 |
|---|---|---|
| POST /api/login | 公开 | JSON 登录（Postman/第三方用），参数错误 400(code=-1)、账号密码错 401(-2)、停用 403(-3)，成功下发同样的 session Cookie |
| GET /api/ping | 登录 | 会话探活心跳，不查库，前端每 5 秒打一次 |

### 9.2 工单与统计

| 方法 路径 | 权限 | 作用 |
|---|---|---|
| POST /api/orders/<id>/progress | 登录 | 手动改进度（completed_qty/delta/progress/status/rework_qty），404 工单不存在、400 状态非法，最终走 apply_manual_progress |
| GET /api/stats | 登录 | 总览统计（只要数字不含明细）+ 产线快照 + PLC 摘要 + 当前倍速 |
| GET /api/logs?category=line | 登录 | 最近 30 条日志，可按类别过滤 |
| POST /api/demo/seed_orders | 登录 | 一键插入 3 笔标准教学演示工单（车载/磁吸/旗舰） |
| GET /api/export/orders | 登录 | 导出全部工单 CSV（带 `\ufeff` BOM，Excel 打开不乱码，文件名带时间戳） |
| GET /api/export/trace | 登录 | 导出最近 500 条过站质量追溯 CSV |

### 9.3 产线与虚拟产线

| 方法 路径 | 权限 | 作用 |
|---|---|---|
| GET /api/line | 登录 | 真实产线快照，未连 PLC 时工位全部冻结离线 |
| GET /api/virtual | 登录 | 虚拟产线快照（含内存日志/记录） |
| POST /api/line/command | **管理员** | 指令 start/stop/reset/alarm；source=virtual 操作虚拟产线不写 PLC；start 可带 order_id 指定工单下发 |

start 指令的分支最复杂：指定 order_id 时查库直接下发这一单；否则有在制单就恢复运行，
没有就取优先级最高的「待生产」工单（虚拟产线无单时自动造一单 VIR 演示单）。
真实产线启动还会把工单置「生产中」、写 started_at。stop/reset/alarm 分别停线、复位清报警、
注入模拟急停，并同步写 HR0（0/0/3）和日志。

### 9.4 PLC

| 方法 路径 | 权限 | 作用 |
|---|---|---|
| GET /api/plc_status | 登录 | PLC_STATE 全字段 + 产线快照 + ip/port。真实产线空闲时合成虚拟产线的运行/报警显示 |
| POST /api/plc/write | **管理员** | 手动写单个寄存器（HMI 调试），返回 ok 与错误信息 |
| POST /api/plc/config | **管理员** | 改 PLC IP/端口并保存到 config.json（reconnect 可控），内部联动虚拟 PLC 子进程 |
| GET/POST /api/simulation/speed | GET 公开/POST 登录 | 读取或设置仿真倍速 |

### 9.5 工位诊断与故障演练

| 方法 路径 | 权限 | 作用 |
|---|---|---|
| GET /api/line/station/<code>/diagnose | 登录（注意未加装饰器的特例*） | 工位深度诊断：静态定义 + 实时状态/过站量 + 传感器按 PLC 与工位运行状态显示 ON/OFF + 工艺参数 |
| POST /api/line/station/<code>/test | 登录 | 单工位动作自检，记一条产线日志并返回成功文案 |
| GET /api/station_st01 | 登录 | ST01 专用监控：HR10~HR17 寄存器、传感器、参数、PLC/产线状态打包 |
| POST /api/line/inject_fault | **管理员** | 在指定工位（默认 ST04）注入故障：报警停线、机器人故障、写 HR0=3、记 ALARM 日志 |
| POST /api/line/clear_fault | 登录 | 一键清除所有「故障」工位与报警、写 HR0=0、记恢复日志 |

> *诊断接口按工位 code 查 STATION_DEFS，找不到返回 404。

---

## 10. 启动块（第 1596~1632 行）

全程 try 兜底，崩溃时把 traceback 写到 `api_crash.log`：

1. `init_db()` 最多重试 6 次、每次间隔 2 秒（MySQL 刚重启可能还没 ready）；
2. 按当前 PLC IP 决定是否自动拉起虚拟 PLC 子进程；
3. 启动两个 daemon 线程：`poll_plc_status`（PLC 轮询）与 `line_simulator`（产线仿真）；
4. `app.run(host=0.0.0.0, port=8080, threaded=True)`。

daemon 线程随主进程退出；两个服务里只有本进程跑这两个线程，避免重复推进产线。

---

## 11. 本文件最值得学习的并发设计

1. **锁的分工**：plc_lock 保护非线程安全的 Modbus 客户端，line_lock（可重入）保护产线内存；
2. **锁内只改内存、锁外才做 I/O**：节拍推进时把写库/写 PLC/记日志收集成 jobs，解锁后再执行，
   界面轮询永远不会被慢 I/O 堵死；
3. **失败冷却**：PLC 离线时 5 秒内不重复尝试连接，把故障成本降到一次 TCP 超时；
4. **真实/虚拟双通道**：两条产线状态同构，PLC 在线时虚拟节拍也写寄存器并镜像画面，
   离线时仿真照常演示，教学演示不受硬件限制；
5. **边沿触发的反向控制**：只认 HR0 的跳变沿，避免「我写的状态被我自己再触发一遍」的回环问题。
