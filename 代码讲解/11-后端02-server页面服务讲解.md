# 11 · 后端代码讲解（二）：server.py —— 前端页面服务（6021 端口）

> 文件位置：`backend/server.py`（约 824 行）
> 启动：`python server.py`
> 一句话定位：**浏览器直接访问的网站**。负责渲染 HTML 页面、接收传统表单 POST、生成验证码图片；
> 自己不管 PLC 和仿真线程，需要实时数据时通过 HTTP 调 8080 的 api_server。

---

## 1. 应用初始化（第 1~66 行）

```python
app = Flask("wodeserver",
            template_folder=frontend/Templates,
            static_folder=frontend/static)
app.secret_key = config.json 里的 secret_key（两服务相同）
app.config["TEMPLATES_AUTO_RELOAD"] = True     # 改 HTML 刷新即生效
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0    # CSS/JS 不缓存，改完刷新即生效
BACKEND_BASE_URL = "http://127.0.0.1:8080"
```

模板/静态目录显式指定绝对路径，不受启动时所在目录影响。

### _backend_request(path, method, payload)：服务端内部调用 8080

这是本文件最关键的「桥」：

1. 取浏览器发来的原始 `Cookie` 头，原样带到对 8080 的请求里——两个服务 secret_key 和
   .epoch 相同，后端据此识别出同一个登录会话，权限判断与浏览器直连完全一致；
2. POST 时把 payload 序列化成 JSON；
3. 用 urllib 请求，**超时仅 3 秒**，任何异常都返回 None（8080 没启动时页面不能跟着 500）。

围绕它有 4 个兜底封装：`_offline_line()`（工位全部离线的假快照）、`_backend_line()`、
`_backend_virtual()`、`_backend_plc_status()`——后端不可达时页面照样能渲染。
`_backend_base_url()` 生成给浏览器 JS 用的接口地址：主机名沿用当前访问的主机，端口固定 8080。

---

## 2. 全局机制：403 页面、模板公共变量、验证码（第 138~251 行）

### 2.1 @app.errorhandler(403)

权限装饰器 abort(403) 时统一渲染 `forbidden.html` 并保持 403 状态码。

### 2.2 @app.context_processor inject_auth()

向**所有模板**自动注入公共变量，省去每个视图重复传参：

- 用户与权限：username、account、role、is_admin、role_label、scope（admin/member）；
- 环境信息：db_engine / db_engine_label（MySQL or SQLite）、frontend_port、backend_port、
  `api_base`（JS 调 8080 的地址前缀）、root_admin；
- 主数据：plan（节拍课件数据）、process_steps、station_defs（7 工位）、products（4 产品）。

模板里随处可见的 `{{ is_admin }}`、`{% for station in station_defs %}` 都来自这里。

### 2.3 验证码 /captcha（PIL/Pillow 绘图）

- `_gen_captcha_code()`：字符集特意去掉 0/O、1/l/I 等易混淆字符，生成 4 位随机码存进 session。
- `captcha_image()`：当场用 Pillow 画一张 120×44 的 PNG：
  深色底、3 条干扰线、30 个干扰点、逐个字符随机颜色和偏移、优先用 consola.ttf 等系统字体、
  最后轻微模糊。每次刷新 `<img src="/captcha?t=时间戳">` 就换一张新码。

---

## 3. 三个公开页面（无需登录）

### 3.1 /login（GET+POST，第 254~285 行）

- GET 渲染 login.html；
- POST 校验顺序：**先验证码**（不区分大小写，错了不查库）→ 再 `verify_login()` 校验账号密码：
  code=-2 提示账号或密码错误，其他 code（如停用）显示后端原因；
  通过则 `sign_in(user)` 写 session、记登录日志、303 重定向到首页。

### 3.2 /register（GET+POST，第 288~332 行）

服务端逐条校验（前端校验可绕过，必须再做一次）：

1. 账号 `[A-Za-z0-9_]{3,20}`；
2. 账号不能是 admin（忽略大小写）；
3. 学号 `[A-Za-z0-9]{4,20}`（后续找回密码的凭据）；
4. 密码至少 6 位；两次输入一致；账号未被注册。

通过后插入 users 表：角色固定 **member**、状态启用、密码存 werkzeug 哈希，写日志后跳登录页。

### 3.3 /forgot_password（GET+POST，第 335~383 行）

「账号 + 学号」自助重置：先验验证码 → 账号学号不能为空 → **内置 admin 直接拒绝**
（它没有学号，只能由其他管理员在用户管理页重置）→ 新密码至少 6 位且两次一致 →
账号必须存在、学号必须与注册时一致且非空 → 更新 password_hash，记日志后跳登录页。

### 3.4 /logout（第 386~394 行）

`session.clear()` 后跳回登录页。

### 3.5 /change_password 自助修改密码（GET+POST，@login_required）

登录用户修改**自己的**密码，入口是 base.html 顶栏的「修改密码」链接；
GET 渲染独立页 change_password.html（error/message），POST 校验顺序：

1. 账号只取 `session['username']`（不信任表单传参），用户不存在则清会话跳登录；
2. 旧密码用 `check_password_hash` 核验，错误提示「旧密码不正确」；
3. 新密码长度 ≥ 6；两次输入必须一致；新密码不得与旧密码相同；
4. 全部通过：UPDATE users.password_hash → `invalidate_user_cache()` 作废用户短缓存
   → add_log 写一条「自助修改登录密码」日志。

关键细节：`session_signature = sha256(epoch:username:password_hash)`，密码哈希一变，
旧会话指纹立即失效；所以成功后必须立刻用最新用户记录重新 `sign_in(get_user(username))`
刷新 session，否则下一次请求会被 login_required 判失效踢下线。最后 303 重定向回本页，
成功文案经 `?message=`（url_quote 编码）回显。

---

## 4. 业务页面路由（全部要求登录）

### 4.1 GET / 首页看板（index，第 397~412 行）

`order_stats(order_limit=8)` 拿统计数字 + `_backend_line()` 拿产线快照，渲染 home.html。
首屏之后由 home.js 每 2 秒轮询 8080 自行刷新。

### 4.2 /orders 工单管理（GET+POST，第 415~468 行）

- POST 新建工单：从表单取 product_code（在 PRODUCTS 里查到产品，查不到用第一个兜底）、
  quantity、priority（int 转换失败归零）、due_date、remark、order_no（留空则 next_order_no 自动生成）。
  **数量 ≤ 0 直接不落库**；合法才 INSERT 一条状态「待生产」的工单并写日志，最后 303 重定向回本页
  （PRG 模式，避免刷新重复提交）。
- GET 渲染 orders.html，传入 products、default_order_no、today 与工单统计。

### 4.3 GET /production 品质统计（第 471~518 行）

三条统计查询：

1. work_records 最近 40 条过站明细；
2. 近 7 天按天汇总「计划量/完成量/不良数」（MySQL 的 DATE_SUB/CURDATE，SQLite 自动改写）；
3. 按工位汇总合格/不良数。

聚合结果里有 Decimal 和 date 对象，统一用 json_safe() 转成基础类型再给模板，
production.html 再把它们 `|tojson` 内嵌给 Chart.js 画图。

### 4.4 设备类页面

- `/hmi`（admin）：从 8080 取 PLC 状态，渲染 hmi.html；之后由 hmi.js 轮询。
- `/station_st01`（admin）：渲染 ST01 专用监控页，PLC 地址参数由本服务给，实时数据靠页内 JS 轮询
  `/api/station_st01`。
- `/line`：真实在制追踪页。查 work_records 最近 30 条、fetch_logs 产线日志最近 20 条，
  和产线快照一起渲染 **line.html（mode="real"）**。
- `/virtual`：虚拟产线页。数据来自 `/api/virtual`（自带演示日志和过站记录），
  渲染的是**同一个 line.html，但 mode="virtual"**——一套模板两种用途。
- `/plc_monitor`：旧路由，302 重定向到 /hmi（plc_monitor.html 已不再渲染）。

### 4.5 /settings 系统设置（GET+POST，admin，第 605~647 行）

- GET：SELECT 1 探一下数据库通不通、从 8080 取 PLC 状态，渲染 settings.html；
- POST：PLC 地址归 8080 管，本服务把表单 `_backend_request("/api/plc/config", POST)` 转发过去，
  8080 负责改内存、写 config.json、重连；返回的提示通过 query 参数 message 回显，303 回本页。

### 4.6 /users 用户管理（GET+POST，admin，第 650~670 行）

GET 列出全部账号；POST 的具体逻辑在 manage_user_action()（见第 6 节），处理完 303 回本页。

### 4.7 /recipes 与 /alarms（第 673~694 行）

- /recipes：纯主数据展示页（产品配方 + 7 工位节拍/寄存器 + Takt Time 公式）；
- /alarms：当前故障/产线/机械臂卡片 + 最近 40 条 WARN/ALARM 日志，
  管理员（scope=admin）可见急停/复位/注入故障/清除故障按钮；按钮以 `data-action`
  标记，由 alarms.js 事件委托经 postJSON 调 8080（模板中不再有内联 onclick）。
- /change_password：见 3.5 节，所有登录用户均可访问，只能改本人密码。

---

## 5. 工单操作的两个 GET 路由（第 764~809 行）

### /update_status/<order_id>/<new_status>

工单列表状态按钮的老入口（真正的精细改进度走 8080 的 JSON 接口，由 progress.js 调用）：

- 状态白名单：只接受 生产中 / 已完成 / 待生产，其他值直接跳回不改数据；
- 「生产中」= 下发产线，**仅管理员**（否则 abort 403），转发 8080
  `/api/line/command` 带 order_id 指定工单启动；
- 「已完成」转发 8080 `/api/orders/<id>/progress`；
- 处理完回到来源页（referrer），没有 referrer 回工单页。

### /delete_order/<order_id>

先问 8080 产线状态：**正在产线上跑的工单不允许删除**（避免仿真线程持有已删除的 order_id）；
否则 DELETE 后写日志并跳回来源页。

---

## 6. manage_user_action()：用户管理五大动作（第 697~761 行）

POST /users 时按表单 action 字段分派，所有分支都有保护条件，返回中文提示语回显：

| action | 行为 | 保护规则 |
|---|---|---|
| disable | 停用账号（status='停用'） | 不能停用管理员；不能操作自己 |
| enable | 重新启用 | 不能操作自己；不能碰内置 admin（非 admin 本人时） |
| reset | 密码重置为 **123456** | 同上 |
| role | 切换 admin/member | 角色值白名单校验 |
| delete | 删除账号 | **只有内置 admin 能删除管理员账号**；不能操作自己 |

额外两条总保护：

- 取目标用户，不存在直接返回；
- 目标是内置 admin 而操作者不是 admin 本人 → 一律拒绝
  （后续被提升的管理员不能动初始管理员，防止管理员互相破坏）。

历史工单和日志里只存用户名文本快照，所以删账号不影响历史记录。

---

## 7. 启动块（第 812~824 行）

- 先 `init_db()`，失败只打印不退出（页面仍能打开排查配置；该函数幂等，两个服务都调）；
- `app.run(host=0.0.0.0, port=6021, threaded=True)`：
  threaded 让每个请求一个线程，避免某个慢请求（如等 8080 的 3 秒超时）卡住整站轮询。

---

## 8. 本文件与其他文件的关系

- **对下**：所有数据库操作都用 common.py 的 db_cursor / order_stats / fetch_logs 等，
  自己不写连接逻辑；
- **对旁**：实时产线/PLC 数据一律向 api_server（8080）要，并转发浏览器 Cookie；
- **对上**：渲染 frontend/Templates 下的 HTML，表单字段 name 与模板 input 的 name 一一对应；
  页面加载后的实时刷新则由 static/js/*.js 直接 fetch 8080，不再经过本服务。
  （2026-09 起前端按页面模块化：每个 HTML 在 static/css、static/js 下各有一个同名文件。）

一条典型链路（设置页改 PLC 地址）：
浏览器表单 POST 6021/settings → server.py 转发到 8080/api/plc/config（带 Cookie）
→ api_server 校验管理员、改内存+config.json、按 IP 决定是否拉起虚拟 PLC
→ 结果原路返回 → server.py 303 带 message 回 /settings 显示提示。
