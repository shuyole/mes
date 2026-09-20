/* login.js —— 登录页脚本 */
(function () {            // IIFE：定义匿名函数并立即执行，把内部变量隔离起来不污染全局；末尾 L70 的 })(); 闭合并调用
    "use strict";        // 开启严格模式：禁止未声明变量等易错写法，让错误更早暴露

    initParticles();     // 调用 particles.js 提供的全局函数，在 #particles-bg 画布上启动粒子背景动画

    // ===== 验证码模块 =====
    // 图形验证码：初始加载一次，点击图片可刷新（由后端 8090 端口生成）
    const captchaImg = document.getElementById('captcha-img');   // 按 id 取验证码 <img> 元素，存为常量
    function refreshCaptcha() {                                  // 定义刷新验证码函数（此时不执行，调用才执行）
        if (captchaImg) captchaImg.src = `${API_BASE}/api/captcha?t=${Date.now()}`;   // 给 img 赋地址触发浏览器自动下载图片；API_BASE 指向 8090；?t=毫秒时间戳让每次 URL 不同以绕过缓存
    }
    if (captchaImg) {                  // 防御：只有图片元素存在才绑定，避免该脚本被误用到别的页面时报错
        refreshCaptcha();              // 进页面立即加载第一张验证码
        captchaImg.addEventListener('click', refreshCaptcha);   // 点击图片时再次执行刷新函数换新图（传函数引用，不加括号）
    }

    // ===== 取表单与错误提示元素 =====
    const form = document.getElementById('loginForm');    // 取登录表单 <form id="loginForm">
    const errEl = document.getElementById('loginError');  // 取红色错误提示框（初始 display:none 隐藏）

    if (form) {                       // 防御：表单存在才绑定提交事件
        form.onsubmit = async (e) => {   // 给 submit 事件绑定异步处理函数，点「进入系统」时触发；async 才能用 await
            /* 拦截浏览器原生表单提交，改用 fetch 异步提交：
               不拦截时浏览器会整页刷新、把表单 POST 后跳转，无法在当前页做精细控制；
               拦截后页面不刷新，好处——
               1. 无白屏闪烁：失败时只在原地显示错误，背景粒子、已填账号都保留，不用整页重画；
               2. 可局部更新：成功跳转 / 失败换验证码 / 错误文案都由 JS 精确控制 DOM；
               3. 可控制请求：用 JSON 请求体、自动带 Cookie、能 await 拿响应并按 ok/401 分流；
               4. 可防重复提交：请求期间先禁用按钮，请求结束在 finally 恢复，传统刷新做不到；
               5. 异常可捕获：断网、超时、401 都能在 catch 里兜底提示，传统方式只能看到浏览器错误页；
               6. 体验接近单页应用（SPA），交互连续。 */
            e.preventDefault();        // 阻止表单默认的整页刷新提交，改由下面 fetch 异步发请求
            if (errEl) errEl.style.display = 'none';   // 每次提交先隐藏上次的错误，避免旧提示残留

            // ===== 收集表单字段 =====
            const username = form.username.value.trim();   // 取账号输入框值并去掉首尾空格（form.username 靠 name 属性定位）
            const password = form.password.value;          // 取密码值，故意不 trim：首尾空格可能是密码的一部分
            const captcha = form.captcha.value.trim();     // 取验证码值并去空格

            // ===== 防重复提交 =====
            const submitBtn = form.querySelector('.login-submit');   // 按类名取提交按钮
            if (submitBtn) submitBtn.disabled = true;    // 请求发出前禁用按钮，网络慢时连点也只发一次

            // ===== 发请求并处理结果 =====
            try {                                        // try/catch/finally：捕获网络与 401 异常，并保证按钮最终恢复
                const res = await apiPost('/api/login', { username, password, captcha });   // 核心：POST 到 8090/api/login，请求体为三字段 JSON；await 等待响应，res 是后端返回的对象（{username} 是 ES6 属性简写）
                if (res.ok) {                            // 后端返回 ok:true 表示登录成功
                    // 登录成功：进入系统主页
                    window.location.href = '/home';      // 整页跳转到前端服务的 /home（随后由 home 页调 /api/me 验证登录态）
                } else {                                 // 业务失败（HTTP 正常但 ok:false）：如验证码错 400、账号停用 403，api.js 不抛异常
                    if (errEl) {                         // 防御：错误框存在才操作
                        errEl.textContent = res.error || '登录失败';   // 显示后端错误文案，后端没给则用默认文案
                        errEl.style.display = '';        // 恢复显示（去掉 none），错误框出现
                    }
                    refreshCaptcha();                    // 旧验证码已提交过，换一张新图让用户用新码重试
                }
            } catch (err) {                              // 处理 api.js 抛出的异常：典型是 401 账号密码错误，以及断网/服务未启动
                // 账号密码错误时后端返回 401，会走到这里
                if (errEl) {                             // 防御：错误框存在才操作
                    errEl.textContent = err.message || '网络错误，请稍后重试';   // 401 时 message 是后端 error 文案；网络异常时用默认提示
                    errEl.style.display = '';            // 显示错误框
                }
                refreshCaptcha();                        // 同样换新验证码
            } finally {                                  // 无论成功、失败还是异常都会执行
                if (submitBtn) submitBtn.disabled = false;   // 恢复按钮可点击，让用户能再次尝试（成功跳转时页面即将卸载，无副作用）
            }
        };   // 结束 onsubmit 处理函数
    }          // 结束 if (form)
})();          // 结束 IIFE 并立即调用
