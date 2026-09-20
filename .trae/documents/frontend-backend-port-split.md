# 前后端端口分离方案

## Context

当前项目是单个 Flask app 绑定两个端口（5001 普通用户端 + 6021 管理端），通过 `ROUTE_SCOPES` + `enforce_port_scope()` 按端口隔离功能。用户要求改为：

- **前端 6021**：页面渲染 + 表单提交，管理员和成员共用，按角色区分权限
- **后端 8080**：所有 `/api/*` JSON 接口 + PLC 轮询/产线仿真线程
- **数据库 3306**：MySQL（已有，不变）

取消端口隔离，改为纯角色权限控制。

## 文件变更清单

### 1. 新建 `backend/common.py` — 共享模块

提取两个 app 都需要的代码：

| 内容 | 原位置 (server.py) |
|---|---|
| `BASE_DIR`, `FRONTEND_DIR` | L24-26 |
| `load_config()`, `CONFIG`, `PLC_CONFIG` | L29-116 |
| `DB_ENGINE`, `SQLITE_PATH` | L142-144 |
| `detect_engine()`, `get_db_connection()`, `db_cursor()` | L339-387 附近 |
| `init_db()` | 数据库建表逻辑 |
| `SESSION_EPOCH`, `session_signature()` | L159, L921-928 |
| `login_required`, `admin_required`, `is_admin()` | L931-988 |
| `get_user()`, `verify_login()`, `sign_in()` | 用户认证函数 |
| `add_log()`, `fetch_logs()` | 日志函数 |
| `STATION_DEFS`, `PRODUCTS` | 静态数据 |
| `_as_int()` 等工具函数 | 数值转换等 |
| `order_stats()` | 工单统计（页面和API共用） |
| `USER_CACHE_TTL`, `_user_cache` | 用户缓存 |

`SESSION_EPOCH` 改为从 `data/.epoch` 文件读取（不存在时自动生成），确保两个进程用同一个值。

### 2. 新建 `backend/api_server.py` — 后端 API 服务 (8080)

从 server.py 提取以下内容：

| 内容 | 原位置 |
|---|---|
| `PLC_STATE`, `LINE`, `VIRTUAL`, `VIRTUAL_LOGS`, `VIRTUAL_RECORDS` | L257-305 |
| `plc_lock`, `line_lock`, `PLC_RETRY_COOLDOWN` | L161-169 |
| `make_line_state()` | L280-298 |
| `snapshot_line()` | 产线快照函数 |
| `poll_plc_status()`, `line_simulator()` | L1646-1669 |
| PLC 读写函数 (`read_from_plc`, `write_plc_map` 等) | PLC 通讯函数 |
| `_advance_line_locked()`, `_run_jobs()` | 产线推进逻辑 |
| 所有 `/api/*` 路由 (11个) | L1709, L2217, L2284-2512 |
| `virtual_plc` 导入 | 虚拟PLC |

**CORS 配置**：
```python
from flask_cors import CORS
CORS(app, origins=["http://127.0.0.1:6021", "http://localhost:6021"],
     supports_credentials=True)
```

**API 路由列表**（全部移到后端）：
- `/api/login` POST
- `/api/ping`
- `/api/plc_status`
- `/api/line`
- `/api/virtual`
- `/api/line/command` POST (admin)
- `/api/orders/<id>/progress` POST
- `/api/plc/write` POST (admin)
- `/api/plc/config` POST (admin)
- `/api/logs`
- `/api/stats`

启动：`init_db()` → 启动 PLC 轮询 + 产线仿真线程 → `app.run(port=8080)`

### 3. 修改 `backend/server.py` — 前端页面服务 (6021)

**删除**：
- `ROUTE_SCOPES` (L129-137)
- `port_scope()` (L172-185)
- `enforce_port_scope` before_request 钩子 (L193-208)
- `USER_PORT`, `ADMIN_PORT` 双端口逻辑 (L124-125)
- 所有 `/api/*` 路由
- `PLC_STATE`, `LINE`, `VIRTUAL` 等全局状态
- `poll_plc_status()`, `line_simulator()` 及相关函数
- `plc_lock`, `line_lock`

**保留**（从 `common.py` 导入）：
- Flask app 实例（template_folder + static_folder 指向 frontend/）
- 所有页面路由（16个）：
  - `/login` GET+POST, `/register` GET+POST, `/logout`
  - `/` (home), `/orders` GET+POST, `/production`
  - `/hmi` (admin_required), `/line`, `/virtual`
  - `/plc_monitor` (admin_required), `/settings` GET+POST (admin_required)
  - `/users` GET+POST (admin_required), `/recipes`, `/alarms`
  - `/update_status/<id>/<status>`, `/delete_order/<id>`
- 模板热重载配置（`TEMPLATES_AUTO_RELOAD`, `SEND_FILE_MAX_AGE_DEFAULT`）
- 403 错误处理器

**修改页面路由中的实时数据获取**：
`/`, `/hmi`, `/line` 原来调用 `snapshot_line()` 读内存状态，改为通过 `urllib.request` 调后端 `http://127.0.0.1:8080/api/line` 获取（后端不可达时返回空状态兜底）。

```python
import urllib.request
def _fetch_line_from_backend():
    """从后端 API 获取产线实时状态，后端不可达时返回空状态。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/api/line", timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return make_empty_line_state()
```

**admin 路由保护**：原来靠 `ROUTE_SCOPES` + 端口隔离，现在直接用 `@admin_required` 装饰器。涉及的路由：`hmi_page`, `plc_monitor`, `settings`, `users_page`。

**启动**：只绑 6021，不再开 5001。

### 4. 修改 `frontend/Templates/base.html` — 注入 API_BASE

在 `<script src="app.js">` 之前加一行：
```html
<script>window.API_BASE = '{{ api_base }}';</script>
```

前端 app 通过 `context_processor` 注入 `api_base = "http://127.0.0.1:8080"`。

`login.html` 和 `register.html` 是独立页面，同样加这行（硬编码或从 config 读）。

### 5. 修改 `frontend/static/app.js` — fetch 包装器

修改 `window.fetch` 包装器（L27-34），对 `/api/` 开头的 URL 自动加 `API_BASE` 前缀和 `credentials: 'include'`：

```javascript
const nativeFetch = window.fetch.bind(window);
window.fetch = function (url, options) {
    if (typeof url === 'string' && url.startsWith('/api/')) {
        url = (window.API_BASE || '') + url;
    }
    options = options || {};
    options.credentials = 'include';
    return nativeFetch(url, options).then(res => {
        if (res.status === 401) window.location.href = '/login';
        return res;
    });
};
```

这样所有 JS 文件的 `fetch('/api/...')` 和 `postJSON('/api/...')` 都自动指向 8080，无需逐个修改。

### 6. 修改 `backend/config.json`

```json
{
  "host": "0.0.0.0",
  "frontend_port": 6021,
  "backend_port": 8080,
  "secret_key": "mes_secret_key_2026",
  "database": { ...不变 },
  "plc": { ...不变 }
}
```

删除 `port` 和 `admin_port`，新增 `frontend_port` 和 `backend_port`。

### 7. 修改 `start.bat`

同时启动两个服务：
```bat
start "MES-Backend" /D "%~dp0backend" python api_server.py
start "MES-Frontend" /D "%~dp0backend" python server.py
```

### 8. 安装依赖

```
pip install flask-cors
```

## 关键设计决策

1. **Session 共享**：两个 Flask app 使用同一个 `secret_key`（从 config.json 读），浏览器 cookie 跨端口共享（现代浏览器不按端口隔离 cookie）。`SESSION_EPOCH` 存在 `data/.epoch` 文件中，两个进程读同一个值。

2. **前端获取实时状态**：`/`, `/hmi`, `/line` 三个页面路由需要产线快照，通过 `urllib.request` 调后端 `http://127.0.0.1:8080/api/line`（3秒超时，失败返回空状态）。页面加载后 JS 继续轮询后端 API 刷新。

3. **admin 权限**：不再用端口隔离，全部靠 `@admin_required` 装饰器。`/hmi`, `/plc_monitor`, `/settings`, `/users` 这四个路由加 `@admin_required`。

4. **settings POST 更新 PLC 配置**：前端 form POST 写 config.json 后，后端不会自动感知。改用前端 JS 调后端 `/api/plc/config` API（已有此接口），后端收到后更新内存中的 PLC_CONFIG 并重连。

## 验证方案

1. 启动两个服务，确认 6021 和 8080 都在监听
2. 浏览器打开 `http://127.0.0.1:6021/login`，用 admin/ADMIN 登录
3. 验证页面正常渲染（home, orders, hmi, line, users, settings）
4. 打开浏览器控制台 Network，确认 `/api/ping` 等请求打到 8080
5. 验证 admin 专属页面：admin 可访问 `/hmi`，普通 member 被拒 403
6. 验证 PLC 状态轮询：hmi 页面 `/api/plc_status` 返回数据
7. 验证产线控制：`/api/line/command` 正常响应
8. 用普通 member 账号登录，验证只能看到普通页面
