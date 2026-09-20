/* register.js —— 注册页脚本 */

/* ===== 模块概述 =====
本脚本只有一个表单提交模块，是三个表单脚本中最简的：
- 收集 username / display_name / student_id / password / confirm 五个字段
- 前端仅做"两次密码一致"预检，其余格式校验全部交给后端 /api/register
- 成功后显示提示并 900ms 跳转 /login（注册成功不自动登录，需手动登录）
- 失败显示 res.error（不刷新验证码，因为注册接口不需要验证码）
- catch 分支兜网络错误（本接口不返回 401）
与 forgot_password.js 的差异：没有验证码模块、没有 #captchaImg 相关逻辑、
catch 不刷新验证码、跳转后用户需手动登录。整体用 IIFE 包裹。
*/
(function () {
    "use strict";

    initParticles();

    // ── 唯一模块：表单提交 ──
    const form = document.getElementById('registerForm');
    const errEl = document.getElementById('registerError');
    const okEl = document.getElementById('registerOk');

    if (form) {
        form.onsubmit = async (e) => {
            e.preventDefault();
            if (errEl) errEl.style.display = 'none';
            if (okEl) okEl.style.display = 'none';

            // 收集五个字段，账号/显示名/学号做 strip，密码不 strip
            const username = form.username.value.trim();
            const display_name = form.display_name.value.trim();
            const student_id = form.student_id.value.trim();
            const password = form.password.value;
            const confirm = form.confirm.value;

            // 前端唯一校验：两次密码一致；其余规则交给后端
            if (password !== confirm) {
                if (errEl) {
                    errEl.textContent = '两次输入的密码不一致';
                    errEl.style.display = '';
                }
                return;
            }

            // 禁用按钮防重复提交
            const submitBtn = form.querySelector('.register-submit');
            if (submitBtn) submitBtn.disabled = true;

            try {
                const res = await apiPost('/api/register', {
                    username,
                    display_name,
                    student_id,
                    password,
                    confirm
                });
                if (res.ok) {
                    // 成功：显示提示，延时跳转登录页（不自动登录）
                    if (okEl) {
                        okEl.textContent = '注册成功，正在跳转登录页...';
                        okEl.style.display = '';
                    }
                    setTimeout(() => { window.location.href = '/login'; }, 900);
                } else if (errEl) {
                    // 失败（账号已存在/格式不合法等）：显示后端文案
                    errEl.textContent = res.error || '注册失败';
                    errEl.style.display = '';
                }
            } catch (err) {
                // catch 兜网络错误（本接口不返回 401）
                if (errEl) {
                    errEl.textContent = err.message || '网络错误，请稍后重试';
                    errEl.style.display = '';
                }
            } finally {
                if (submitBtn) submitBtn.disabled = false;
            }
        };
    }
})();
