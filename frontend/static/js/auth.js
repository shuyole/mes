/**
 * auth.js — 登录状态管理
 * 提供用户信息缓存、角色判断、登出等功能。
 */

// 当前用户信息缓存
let _currentUser = null;

/**
 * 获取当前登录用户信息（有缓存）
 * @param {boolean} force - 强制刷新
 * @returns {Promise<object|null>} - 用户信息对象或 null
 */
async function getCurrentUser(force = false) {
  if (_currentUser && !force) return _currentUser;
  try {
    const data = await apiGet('/api/me');
    if (data.ok) {
      _currentUser = data;
      return _currentUser;
    }
  } catch (e) {
    // 未登录
  }
  _currentUser = null;
  return null;
}

/**
 * 清除用户缓存
 */
function clearUserCache() {
  _currentUser = null;
}

/**
 * 是否已登录
 */
async function isLoggedIn() {
  const user = await getCurrentUser();
  return !!user;
}

/**
 * 是否为管理员
 */
function isCurrentAdmin() {
  return _currentUser && _currentUser.is_admin;
}

/**
 * 退出登录
 */
async function logout() {
  try {
    await apiPost('/api/logout', {});
  } catch (e) {
    // 忽略
  }
  clearUserCache();
  window.location.hash = '#/login';
}

// 导出到全局
window.getCurrentUser = getCurrentUser;
window.clearUserCache = clearUserCache;
window.isLoggedIn = isLoggedIn;
window.isCurrentAdmin = isCurrentAdmin;
window.logout = logout;
