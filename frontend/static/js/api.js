/**
 * api.js — API 调用封装层
 * 所有与后端的 HTTP 通信统一通过此模块，自动处理认证、错误、JSON 解析。
 */

// 后端 API 地址：与当前页面同一主机，端口 8080
const API_BASE = (() => {
  const host = window.location.hostname || '127.0.0.1';
  return `http://${host}:8080`;
})();

// 导出给全局使用
window.API_BASE = API_BASE;

/**
 * 统一 API 请求封装
 * @param {string} path - API 路径（如 /api/me）
 * @param {object} options - fetch 选项（method, body 等）
 * @returns {Promise<object>} - 解析后的 JSON 对象
 */
async function api(path, options = {}) {
  const url = API_BASE + path;
  const defaults = {
    credentials: 'include', // 始终带 Cookie
    headers: { 'Content-Type': 'application/json' },
  };
  const config = { ...defaults, ...options };
  if (options.headers) {
    config.headers = { ...defaults.headers, ...options.headers };
  }
  // GET 请求不需要 Content-Type
  if (!config.method || config.method === 'GET') {
    delete config.headers['Content-Type'];
  }

  const resp = await fetch(url, config);

  // 非 JSON 响应（如验证码图片）
  const ct = resp.headers.get('content-type') || '';
  if (!ct.includes('application/json')) {
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp;
  }

  const data = await resp.json();

  // 401 未登录：跳转登录页
  if (resp.status === 401) {
    if (!path.includes('/api/me') && !path.includes('/api/login')) {
      window.location.hash = '#/login';
    }
    throw new Error(data.error || '未登录');
  }

  return data;
}

/**
 * GET 请求
 */
async function apiGet(path) {
  return api(path);
}

/**
 * POST 请求（JSON 请求体）
 */
async function apiPost(path, body) {
  return api(path, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * DELETE 请求
 */
async function apiDelete(path) {
  return api(path, { method: 'DELETE' });
}

// 导出到全局
window.api = api;
window.apiGet = apiGet;
window.apiPost = apiPost;
window.apiDelete = apiDelete;
