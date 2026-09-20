# 修改密码功能 + 前端 HTML/CSS/JS 模块化 实施计划

## 一、需求与已确认决策

1. **新增修改密码功能**：独立页面 `/change_password`（旧密码 + 新密码 + 确认新密码），
   顶栏用户区提供入口；所有登录用户只能改自己的密码。走 6021 传统表单 POST，与登录/注册风格一致。
2. **模块化范围**：全部 15 个在用模板 + 新增的修改密码页 = **16 个页面模板**，
   每个模板配同名 CSS、同名 JS。不含 `_widgets.html`（Jinja 宏库）、
   `plc_monitor.html`（路由已 302 废弃）、`test.html`（无路由孤儿页）。
3. **目录结构**：
   - `static/css/`：全局 `app.css`、`console.css` 保留；新增各页面同名 CSS；
     `monitor.css` 重命名为 `home.css`（首页专属样式归位）。
   - `static/js/`（新建目录）：全局 `app.js`、`form.js`、共享控件 `progress.js` 移入；
     原有 `home.js/line.js/orders.js/production.js/hmi.js` 移入；新增各页面同名 JS。

## 二、仓库现状结论

- 后端：`server.py` 已有 /login、/register、/forgot_password、/logout 与用户管理
  （manage_user_action 的 reset 仅管理员重置他人为 123456），**没有用户自助改密路由**。
  会话指纹 `session_signature = sha256(.epoch + 用户名 + 密码哈希)` 存在 session["sign"]，
  改密码后指纹会变——必须在改密成功后重新 `sign_in(user)` 刷新指纹，否则下一跳被判定会话失效踢回登录页。
- 前端：18 个模板中 login/register/forgot_password 各含约 250 行内联 `<style>`
  和一份近似的粒子 canvas 内联 `<script>`；station_st01.html 含大段 st01-* 内联样式
  与轮询内联 IIFE；base.html 底部有 updateTopbarStatus 内联脚本；alarms.html 用内联 onclick；
  settings/users/recipes/forbidden 无专属 JS；monitor.css 仅首页引用。
- 8 个 JS 当前在 `static/` 根目录，模板以 `url_for('static', filename='xxx.js')` 引用。
- `tests/check_ui.py` 只断言 console.css 与 .app-shell，不依赖 JS 路径，迁移不影响它。

## 三、文件变更清单

### 后端（1 个文件）

- `backend/server.py`
  - 新增 `GET/POST /change_password`（@login_required）：
    旧密码用 `check_password_hash` 核验 → 新密码 ≥6 位 → 两次一致 → 新密码不得与旧密码相同
    → UPDATE users.password_hash → `invalidate_user_cache()` → `add_log` →
    **重新 sign_in(user) 刷新会话指纹** → 303 回本页并带 message 成功提示；
    各失败分支渲染页面带回 error。
  - 新增白名单无需调整（该页要求登录）。

### 模板（16 个，改 15 + 新建 1）

| 模板 | CSS（同名） | JS（同名） | 本次处理 |
|---|---|---|---|
| base.html | css/base.css（新，母版专属微调） | js/base.js（新，抽离顶栏 3s 轮询） | 抽内联 JS、更新全部静态引用路径、顶栏加「修改密码」入口 |
| home.html | css/home.css（monitor.css 改名） | js/home.js（迁移） | 更新引用 |
| line.html | css/line.css（新） | js/line.js（迁移） | 更新引用 |
| orders.html | css/orders.css（新） | js/orders.js（迁移）+js/progress.js（迁移） | 更新引用 |
| production.html | css/production.css（新） | js/production.js（迁移）+js/progress.js | 更新引用 |
| hmi.html | css/hmi.css（新） | js/hmi.js（迁移） | 更新引用 |
| station_st01.html | css/station_st01.css（新，抽内联） | js/station_st01.js（新，抽内联 IIFE） | 抽离内联 style/script |
| settings.html | css/settings.css（新） | js/settings.js（新，提交反馈/交互增强） | 更新引用 |
| users.html | css/users.css（新） | js/users.js（新，页面交互增强） | 更新引用 |
| recipes.html | css/recipes.css（新） | js/recipes.js（新，卡片初始化/入场） | 更新引用 |
| alarms.html | css/alarms.css（新） | js/alarms.js（新，内联 onclick 改为事件绑定） | 抽离内联 onclick |
| forbidden.html | css/forbidden.css（新） | js/forbidden.js（新，倒计时返回首页） | 更新引用 |
| login.html | css/login.css（新，抽内联 250 行） | js/login.js（新，粒子动画+验证码点击刷新） | 抽离内联 style/script |
| register.html | css/register.css（新，抽内联） | js/register.js（新，粒子+表单增强） | 抽离内联 |
| forgot_password.html | css/forgot_password.css（新，抽内联） | js/forgot_password.js（新，粒子） | 抽离内联 |
| **change_password.html（新建）** | css/change_password.css（新，复用登录科技风） | js/change_password.js（新，粒子+两次一致性前端校验） | 全新页面 |

### 静态资源迁移

- 删除 `static/monitor.css`（内容迁入 `static/css/home.css`）；
- `static/` 根下 8 个 JS 移动到 `static/js/`（app/form/home/line/orders/production/progress/hmi）；
- 全局搜索并更新所有 `filename='xxx.js'`、`filename='css/monitor.css'` 引用。

### 不改动

- `api_server.py`、`common.py`、虚拟 PLC、测试脚本、config.json、数据库结构；
- app.css / console.css 内容保持不变（全局样式职责不变）。

## 四、实施步骤（依赖顺序）

1. **后端先行**：server.py 增加 /change_password 路由（含完整服务端校验与指纹刷新）。
2. **建目录与迁移**：新建 static/js/；移动 8 个 JS；monitor.css → css/home.css。
3. **修改密码页**：新建 change_password.html/css/js（独立整页科技风，与登录页同族）。
4. **母版改造**：base.html 顶栏用户区加「修改密码」链接；抽内联轮询到 js/base.js；
   新建 css/base.css；更新 form.js/app.js 引用为 js/ 路径。
5. **业务页批量配套**：为 10 个继承母版的业务页逐一新建同名 CSS/JS 并更新 extra_css/extra_js 引用；
   station_st01、alarms 完成内联抽离。
6. **登录三页抽离**：三页内联 style/script 抽到同名 CSS/JS，粒子动画统一进各自 JS。
7. **全局引用排查**：搜索 `.js'`、`monitor.css`、内联 `<style>`/`<script>` 残留，确保无遗漏。

## 五、每个新 JS/CSS 的真实职责（避免空壳文件）

- 纯展示页也有实际脚本：recipes.js（卡片入场动画+工艺提示）、users.js（行内确认与操作反馈）、
  settings.js（保存按钮 loading 态）、forbidden.js（5 秒倒计时自动返回首页）、
  base.js（顶栏状态轮询）、各页面 CSS 承载页面专属布局微调，类名加页面前缀防污染。
- alarms.js：把 4 个内联 onclick（注入故障/清除/急停/复位）改为 data-action + addEventListener。

## 六、验证

1. `python -m py_compile backend/server.py` 语法检查；
2. 启动 api_server.py 与 server.py，逐页访问 16 个页面路由，确认 200、无 404 静态资源、
   控制台无 JS 报错、样式与改造前一致；
3. 修改密码功能验证：旧密码错误拦截、新密码过短/两次不一致/新旧相同拦截、
   成功后提示且**不被踢下线**（指纹已刷新）、用新密码重新登录成功、旧密码失效；
4. 运行 tests/check_ui.py 冒烟（零横向溢出、零 JS 错误）；
5. 管理员/普通成员各验证一次顶栏入口与权限。

## 七、风险与应对

- **静态路径遗漏导致 404**：迁移后全局 grep 全部 filename= 引用与硬编码 /static/ 路径，逐页打开网络面板核对。
- **改密后被强制登出**：成功分支立即重新 sign_in() 写新指纹（已在步骤 1 处理）。
- **内联 onclick 抽离后 this 上下文丢失**：alarms 改用事件委托 + data 属性传参。
- **三个粒子脚本重复**：保持各自独立（三页互不继承、可单独打开），仅从内联移到同名 JS 文件。
- **讲解文档与结构漂移**：本次完成后同步更新 `代码讲解/` 中引用旧目录/旧文件名的内容与新增页面说明。
