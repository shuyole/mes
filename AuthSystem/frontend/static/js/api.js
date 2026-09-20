/**
 * api.js — 接口调用封装层
 * 前端页面服务（6031）与后端接口服务（8090）端口不同，因此这里指向后端的完整地址；
 * 两个端口同主机，浏览器会一并带上后端签发的会话 Cookie，登录态可跨端口识别。
 */

// 后端接口服务的基地址；用立即执行函数算出结果后赋给全局常量 API_BASE
const API_BASE = (() => {
  const host = window.location.hostname || '127.0.0.1';   // 取当前页面主机名；极端场景（如 file:// 打开）为空时退回 127.0.0.1
  return `http://${host}:8090`;                            // 后端端口固定 8090，与前端页面端口 6031 区分开
})();

/**
 * 统一请求封装：自动处理认证、JSON 解析与错误
 * @param {string} path - 接口路径（如 /api/me）
 * @param {object} options - fetch 选项（method、body 等）
 * @returns {Promise<object>} - 解析后的 JSON 对象
 */
async function api(path, options = {}) {                   // options 缺省为空对象；async 让函数始终返回 Promise
  // credentials: include 是跨端口调用能带上 Cookie 的关键
  const config = { credentials: 'include', ...options };   // 先铺上「带凭证」的默认值，再让调用方传入的选项覆盖同名键
  if (options.body) {                                      // 只有带请求体时才需要声明 Content-Type
    config.headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };   // 声明请求体是 JSON，并允许调用方追加自定义请求头
  }

  const resp = await fetch(API_BASE + path, config);       // 发请求：完整地址 = 8090 基地址 + 接口路径
  const ct = resp.headers.get('content-type') || '';       // 读响应类型，用于区分返回的是 JSON 还是图片等
  // 非 JSON 响应（如验证码图片）直接返回原始响应
  if (!ct.includes('application/json')) {                  // 用 includes 而不是全等，兼容 "application/json; charset=utf-8" 这类写法
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);  // 非 JSON 且状态码失败：抛出带状态码的错误
    return resp;                                           // 正常则把原始 Response 交给调用方自己处理（可直接当图片用）
  }

  const data = await resp.json();                          // JSON 响应：解析成对象

  // 401 表示未登录或登录已失效，抛出的错误带上状态码，由调用方决定是否跳回登录页
  if (resp.status === 401) {                               // 未登录 / 会话失效统一走异常分支
    const err = new Error(data.error || '未登录或登录已失效');   // 错误文案优先用后端返回的 error 字段，没有则用默认文案
    err.status = 401;                                      // 把状态码挂在错误对象上，调用方可据此决定是否跳登录页
    throw err;                                             // 抛出，交给调用方的 catch 处理
  }
  return data;                                             // 其余状态（200/400/403/500）原样返回，由调用方看返回体的 ok 字段判断
}

/** GET 请求 */
async function apiGet(path) {                              // GET 不需要请求体，直接复用 api
  return api(path);                                        // 返回 api 的 Promise
}

/** POST 请求（JSON 请求体） */
async function apiPost(path, body) {                       // body 传 JavaScript 对象，由本函数负责序列化
  return api(path, { method: 'POST', body: JSON.stringify(body || {}) });   // 序列化成 JSON 字符串；body 为空时发送 {}
}

window.API_BASE = API_BASE;   // 额外挂到 window 上，保证任何脚本（含内联写法）都能通过 window.API_BASE 取到
window.apiGet = apiGet;       // 暴露 GET 封装，供各页面脚本调用
window.apiPost = apiPost;     // 暴露 POST 封装，供各页面脚本调用
