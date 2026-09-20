/**
 * router.js — SPA Hash 路由器
 * 根据 URL hash 加载对应的页面片段到 #mainContent 区域。
 */

// 路由表：hash → { page: 页面文件名, title: 页面标题, auth: 是否需要登录, admin: 是否需要管理员 }
const ROUTES = {
  '/login':            { page: 'login.html',            title: '系统登录',     auth: false, fullPage: true },
  '/register':         { page: 'register.html',         title: '账号注册',     auth: false, fullPage: true },
  '/forgot_password':  { page: 'forgot_password.html',  title: '找回密码',     auth: false, fullPage: true },
  '/home':             { page: 'home.html',             title: '数据采集与监控', auth: true,  activePage: 'home' },
  '/orders':           { page: 'orders.html',           title: '作业指示排产', auth: true,  activePage: 'orders' },
  '/line':             { page: 'line.html',             title: '在制实时追踪', auth: true,  activePage: 'line' },
  '/virtual':          { page: 'virtual.html',          title: '虚拟仿真产线', auth: true,  activePage: 'virtual' },
  '/production':       { page: 'production.html',       title: '品质追溯分析', auth: true,  activePage: 'production' },
  '/hmi':              { page: 'hmi.html',              title: '设备上位机主控', auth: true,  admin: true, activePage: 'hmi' },
  '/station_st01':     { page: 'station_st01.html',     title: 'ST01 自动上料', auth: true,  admin: true, activePage: 'station_st01' },
  '/alarms':           { page: 'alarms.html',           title: '异常发生管理', auth: true,  activePage: 'alarms' },
  '/recipes':          { page: 'recipes.html',          title: '工艺配方节拍', auth: true,  activePage: 'recipes' },
  '/settings':         { page: 'settings.html',         title: '基础数据配置', auth: true,  activePage: 'settings' },
  '/users':            { page: 'users.html',            title: '用户权限管理', auth: true,  admin: true, activePage: 'users' },
};

// 页面标题映射
const PAGE_TITLES = {
  home: '生产数据采集与监控中心',
  line: '无线充产线 · 在制实时追踪',
  virtual: '数字孪生 · 虚拟仿真产线',
  orders: '作业指示 · 工单排产调度',
  production: '品质管理 · 批次质量追溯',
  recipes: '工艺配方 · 节拍与标准工时',
  hmi: '设备管理 · PLC 与机械臂主控',
  station_st01: 'ST01 自动上料 · PLC 专用监控',
  alarms: '异常发生管理 · 故障告警',
  settings: '系统设置 · 通讯与主数据',
  users: '系统安全 · 操作员账号管理',
};

// 页面初始化函数注册表
const PAGE_INITS = {};

// 页面片段缓存
const _pageCache = {};

// 当前活动的页面清理函数
let _currentCleanup = null;

/**
 * 注册页面初始化函数
 * @param {string} pageName - 页面名称（activePage）
 * @param {function} initFn - 初始化函数，可返回清理函数
 */
function registerPage(pageName, initFn) {
  PAGE_INITS[pageName] = initFn;
}

/**
 * 加载页面片段
 */
async function loadPageFragment(filename) {
  if (_pageCache[filename]) return _pageCache[filename];
  const resp = await fetch(`/Templates/${filename}`);
  if (!resp.ok) throw new Error(`页面加载失败: ${filename}`);
  const html = await resp.text();
  _pageCache[filename] = html;
  return html;
}

/**
 * 导航到指定路由
 */
async function navigate(hash) {
  const path = hash.replace('#', '') || '/home';
  const route = ROUTES[path];

  if (!route) {
    window.location.hash = '#/home';
    return;
  }

  // 清理上一个页面
  if (_currentCleanup) {
    try { _currentCleanup(); } catch (e) { /* ignore */ }
    _currentCleanup = null;
  }

  // 认证检查
  if (route.auth) {
    const user = await getCurrentUser();
    if (!user) {
      window.location.hash = '#/login';
      return;
    }
    // 管理员检查
    if (route.admin && !user.is_admin) {
      window.location.hash = '#/home';
      return;
    }
  }

  // 全页面（登录/注册/找回密码不使用 SPA 壳）
  if (route.fullPage) {
    document.getElementById('appShell').style.display = 'none';
    const fullPageContainer = document.getElementById('fullPageContainer');
    fullPageContainer.style.display = '';
    try {
      const html = await loadPageFragment(route.page);
      fullPageContainer.innerHTML = html;
      document.title = route.title + ' - MES';
      // 执行页面内的 script 标签
      executeScripts(fullPageContainer);
      // 调用页面初始化
      const pageName = path.replace('/', '');
      if (PAGE_INITS[pageName]) {
        const cleanup = PAGE_INITS[pageName]();
        if (typeof cleanup === 'function') _currentCleanup = cleanup;
      }
    } catch (e) {
      fullPageContainer.innerHTML = '<p style="color: red; text-align: center; padding: 40px;">页面加载失败</p>';
    }
    return;
  }

  // SPA 壳内页面
  document.getElementById('appShell').style.display = '';
  document.getElementById('fullPageContainer').style.display = 'none';

  const mainContent = document.getElementById('mainContent');
  document.title = route.title + ' - MES';

  // 更新导航高亮
  updateNavActive(route.activePage);

  // 更新顶栏标题
  const topbarTitle = document.querySelector('.topbar-title');
  if (topbarTitle && PAGE_TITLES[route.activePage]) {
    topbarTitle.textContent = PAGE_TITLES[route.activePage];
  }

  // 更新 body data-page
  document.body.setAttribute('data-page', route.activePage || '');

  try {
    const html = await loadPageFragment(route.page);

    // 渲染页面头部（page-heading）
    const pageHeading = renderPageHeading(route.activePage);
    mainContent.innerHTML = pageHeading + html;

    // 执行页面内的 script 标签
    executeScripts(mainContent);

    // 调用页面初始化
    if (route.activePage && PAGE_INITS[route.activePage]) {
      const cleanup = PAGE_INITS[route.activePage]();
      if (typeof cleanup === 'function') _currentCleanup = cleanup;
    }
  } catch (e) {
    mainContent.innerHTML = '<div class="empty">页面加载失败，请刷新重试。</div>';
  }
}

/**
 * 渲染页面头部
 */
function renderPageHeading(activePage) {
  const meta = {
    orders:      ['MANUFACTURING / DISPATCH', '作业指示与工单排产', '支持加急、普通工单排入，一键下发产线'],
    line:        ['PRODUCTION / TRACKING', '在制实时追踪 · 数字孪生流水线', '7 大工位工业传感与机械臂协同监视'],
    virtual:     ['ENGINEERING / SIMULATION', '虚拟产线 · 本地多场景仿真', '免硬件独立调试工艺流程与节拍平衡'],
    settings:    ['SYSTEM / MASTER DATA', '系统基础数据与设备通讯', 'Modbus TCP 地址配置与产品主数据'],
    hmi:         ['EQUIPMENT / SCADA CONTROL', '设备管理与 PLC 上位机控制台', '保持寄存器读写、机械臂点位与急停控制'],
    recipes:     ['ENGINEERING / RECIPES', '工艺配方管理与生产节拍', '工序标准工时、Takt Time 与平衡率'],
    production:  ['QUALITY / TRACEABILITY', '品质管理与全流程质量追溯', '一次合格率、不良品分析与记录导出'],
    users:       ['SECURITY / ACCESS CONTROL', '操作员与权限安全管理', '多角色协同、账号启停与密码重置'],
    alarms:      ['OPERATIONS / ALARM CENTER', '异常发生管理与排障 SOP', '故障报警秒级响应、声光警示与处置记录'],
  };
  if (!meta[activePage]) return '';
  const m = meta[activePage];
  return `<header class="page-heading"><div><div class="page-eyebrow">${m[0]}</div><h1>${m[1]}</h1></div><div class="page-context"><b>无线充自动化装配线</b>${m[2]}</div></header>`;
}

/**
 * 更新导航高亮
 */
function updateNavActive(activePage) {
  document.querySelectorAll('.side-link').forEach(link => {
    const href = link.getAttribute('href') || '';
    const linkPage = href.replace('#/', '').replace('/', '');
    link.classList.toggle('active', linkPage === activePage);
  });
}

/**
 * 执行动态插入的 <script> 标签
 */
function executeScripts(container) {
  const scripts = container.querySelectorAll('script');
  scripts.forEach(oldScript => {
    const newScript = document.createElement('script');
    if (oldScript.src) {
      newScript.src = oldScript.src;
    } else {
      newScript.textContent = oldScript.textContent;
    }
    if (oldScript.type) newScript.type = oldScript.type;
    oldScript.parentNode.replaceChild(newScript, oldScript);
  });
}

/**
 * 更新侧边栏：根据用户角色显示/隐藏管理员菜单
 */
async function updateSidebar() {
  const user = await getCurrentUser();
  if (!user) return;

  // 更新用户信息
  const usernameEl = document.querySelector('.user-box b');
  if (usernameEl) usernameEl.textContent = user.display_name || user.username;

  const roleChip = document.querySelector('.role-chip');
  if (roleChip) {
    roleChip.textContent = user.role_label;
    roleChip.className = 'role-chip ' + (user.is_admin ? 'admin' : 'member');
  }

  // 管理员菜单显示/隐藏
  document.querySelectorAll('[data-admin-only]').forEach(el => {
    el.style.display = user.is_admin ? '' : 'none';
  });

  // 侧边栏底部
  const footer = document.querySelector('.sidebar-footer');
  if (footer) {
    footer.innerHTML = `<strong>无线充柔性线</strong>${user.is_admin ? '管理员权限' : '操作员权限'}`;
  }
}

// 初始化路由
function initRouter() {
  window.addEventListener('hashchange', () => navigate(window.location.hash));

  // 首次加载
  if (!window.location.hash) {
    window.location.hash = '#/home';
  } else {
    navigate(window.location.hash);
  }
}

// 导出到全局
window.ROUTES = ROUTES;
window.registerPage = registerPage;
window.navigate = navigate;
window.initRouter = initRouter;
window.updateSidebar = updateSidebar;
