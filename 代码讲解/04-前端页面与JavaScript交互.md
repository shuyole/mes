# 04-前端页面与JavaScript交互

本项目前端摒弃了庞大的 Vue、React 或 Node.js 构建链，完全采用纯原生 HTML5、CSS3 和 JavaScript（Vanilla JS）编写，任何初学者用记事本或 VS Code 打开即可直接看懂。

---

## 1. 前端页面清单与作用

| 页面模板 | 访问路由 | 对应功能 |
| :--- | :--- | :--- |
| `frontend/Templates/login.html` | `/login` | 用户登录页：输入账号密码验证码、记住账号 |
| `frontend/Templates/register.html` | `/register` | 账号注册页：填写真实姓名、学号、密码 |
| `frontend/Templates/forgot_password.html` | `/forgot_password` | 找回密码页：学号验证重置新密码 |
| `frontend/Templates/home.html` | `/home` | 控制台主页：登录后的欢迎信息与功能概览 |
| `frontend/Templates/settings.html` | `/settings` | 个人中心页：个人详细资料展示与密码修改 |

---

## 2. 网络请求封装工具 (`frontend/static/js/api.js`)

为了避免在每个 JS 文件里重复编写繁琐的 `fetch` 代码，我们编写了一个简单通用的 `api.js`：

```javascript
// 后端 API 服务的统一根地址
const API_BASE = "http://127.0.0.1:8090";

// 统一的网络请求函数
async function apiRequest(endpoint, method = "GET", body = null) {
    const options = {
        method: method,
        headers: { "Content-Type": "application/json" }
    };
    if (body) {
        options.body = JSON.stringify(body);
    }
    const response = await fetch(API_BASE + endpoint, options);
    return await response.json();
}
```
**初学者学习要点**：
- 它统一配置了 `API_BASE` 为 `8090` 端口。
- 自动将 JS 对象转为 JSON 字符串发送给后端。
- 自动将后端返回的 JSON 字符串解析为 JS 对象。

---

## 3. 页面权限守卫与状态管理 (`frontend/static/js/shell.js`)

在主页 `home.html` 和设置页 `settings.html` 中，我们引入了通用的 `shell.js`，它的作用就像一个小管家：

### 3.1 登录状态检查（页面路由守卫）
```javascript
// 从浏览器本地读取登录信息
const userStr = localStorage.getItem("user");
if (!userStr) {
    // 如果没有登录，强制跳回登录页
    alert("您尚未登录，请先登录！");
    window.location.href = "/login";
} else {
    // 如果已登录，将用户名展示在导航栏上
    const user = JSON.parse(userStr);
    document.getElementById("navUsername").textContent = user.display_name || user.username;
}
```

### 3.2 退出登录
```javascript
function logout() {
    // 清除本地登录状态
    localStorage.removeItem("user");
    // 跳转回登录页
    window.location.href = "/login";
}
```
通过极其通俗直白的原生 `localStorage`，初学者一眼就能搞清楚“登录状态是怎么保持的”。

---

## 4. 表单交互流程（以登录为例）

在 `frontend/static/js/login.js` 中：
1. 监听登录按钮的 `submit` 点击事件：`e.preventDefault()` 阻止表单默认整页刷新跳转。
2. 收集输入框中的 `username`、`password` 和 `captcha`。
3. 调用 `apiRequest('/api/login', 'POST', {...})` 发送给后端。
4. 后端返回 `{ ok: true }` 则记录 `localStorage` 并跳转到 `/home`。
5. 后端返回 `{ ok: false }` 则通过页面的红色消息框提示用户错误原因，并自动刷新图形验证码。
