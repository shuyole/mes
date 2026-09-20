/* forgot_password.js —— 找回密码页脚本 */

/* ===== 模块概述 =====
本脚本分为两块：
1. 验证码模块（captchaImg + refreshCaptcha）：获取 <img> 元素，把 src 指向后端 8090 的
   /api/captcha 接口；初始加载一次，点击图片可刷新。与 login.js 中的逻辑完全一致。
2. 表单提交模块：收集 username / student_id / new_password / confirm / captcha 五个字段，
   前端仅做"两次密码一致"预检，其余校验全部交给后端 /api/forgot_password。
   成功后显示提示并 900ms 跳转 /login；失败显示 res.error 并刷新验证码。
   catch 分支主要兜网络错误（后端 400 不抛异常，只有 401 才抛，本接口不会返回 401）。
与 login.js 的差异：多了成功提示框 #fpOk、跳转目标 /login、后端要求必填验证码。
整体用 IIFE 包裹，避免污染全局。
*/
(function () {
    "use strict";

    initParticles();

    // ── 模块1：验证码 ──
    // 图形验证码：初始加载一次，点击图片可刷新（由后端 8090 端口生成）
    const captchaImg = document.getElementById('captcha-img');
    function refreshCaptcha() {
        if (captchaImg) captchaImg.src = `${API_BASE}/api/captcha?t=${Date.now()}`;
    }
    if (captchaImg) {
        refreshCaptcha();
        captchaImg.addEventListener('click', refreshCaptcha);
    }

    // ── 模块2：表单提交 ──
    const form = document.getElementById('fpForm');
    const errEl = document.getElementById('fpError');
    const okEl = document.getElementById('fpOk');

    if (form) {
        form.onsubmit = async (e) => {
            e.preventDefault();
            if (errEl) errEl.style.display = 'none';
            if (okEl) okEl.style.display = 'none';

            // 收集五个字段，账号/学号/验证码做 strip，密码不 strip
            const username = form.username.value.trim();
            const student_id = form.student_id.value.trim();
            const new_password = form.new_password.value;
            const confirm = form.confirm.value;
            const captcha = form.captcha.value.trim();

            // 前端唯一校验：两次密码一致；其余规则交给后端
            if (new_password !== confirm) {
                if (errEl) {
                    errEl.textContent = '两次输入的密码不一致';
                    errEl.style.display = '';
                }
                return;
            }

            // 禁用按钮防重复提交
            const submitBtn = form.querySelector('.fp-submit');
            if (submitBtn) submitBtn.disabled = true;

            try {
                const res = await apiPost('/api/forgot_password', {
                    username,
                    student_id,
                    new_password,
                    confirm,
                    captcha
                });
                if (res.ok) {
                    // 成功：显示提示，延时跳转登录页
                    if (okEl) {
                        okEl.textContent = '密码重置成功，正在跳转登录页...';
                        okEl.style.display = '';
                    }
                    setTimeout(() => { window.location.href = '/login'; }, 900);
                } else {
                    // 失败（验证码错/学号不匹配等）：显示后端文案并刷新验证码
                    if (errEl) {
                        errEl.textContent = res.error || '重置失败';
                        errEl.style.display = '';
                    }
                    refreshCaptcha();
                }
            } catch (err) {
                // catch 兜网络错误（本接口不返回 401，不会因登录态失效走这里）
                if (errEl) {
                    errEl.textContent = err.message || '网络错误，请稍后重试';
                    errEl.style.display = '';
                }
                refreshCaptcha();
            } finally {
                if (submitBtn) submitBtn.disabled = false;
            }
        };
    }
})();
