/* settings.js —— 设置页脚本：点击「修改登录密码」弹出改密弹窗并提交 */

/* ===== 模块概述 =====
本脚本比 forgot_password / register 多一层弹窗管理，分为三块：
1. 弹窗工具模块：setMsg() 写消息并切换样式类，openModal() 打开弹窗（清消息→重置表单→
   显示遮罩→聚焦旧密码框），closeModal() 关闭弹窗。
2. 事件绑定模块：openBtn 点击打开、cancelBtn 点击关闭、点击遮罩空白处关闭、按 Esc 关闭——
   三种关闭路径。
3. 改密提交模块：收集 old_password / new_password / confirm，前端仅做密码一致预检，
   调 /api/change_password。成功显示消息 + 重置表单 + 1200ms 后关弹窗；
   失败显示后端文案。catch 中判断 err.status===401 时跳 /login（三个脚本中唯一处理 401 跳转的）。
与前两者的差异：有弹窗生命周期管理、有 401 登录失效跳转、成功后只关弹窗不跳页、
finally 额外移除 is-busy 样式类。整体用 IIFE 包裹。
*/
(function () {
    "use strict";

    // ── 模块1：弹窗工具 ──
    // 取弹窗相关的 DOM 元素：遮罩、打开按钮、取消按钮、表单、消息框、提交按钮
    const mask = document.getElementById('changePwdMask');
    const openBtn = document.getElementById('openChangePwdBtn');
    const cancelBtn = document.getElementById('changePwdCancel');
    const form = document.getElementById('changePwdForm');
    const msgEl = document.getElementById('changePwdMsg');
    const submitBtn = document.getElementById('changePwdSubmit');

    /** 显示弹窗内提示消息，type 为 error / success */
    function setMsg(text, type) {
        if (!msgEl) return;
        msgEl.textContent = text || '';
        msgEl.className = 'modal-msg' + (type ? ' ' + type : '');
    }

    function openModal() {
        if (!mask) return;
        setMsg('');
        if (form) form.reset();
        mask.classList.add('open');
        const oldInput = document.getElementById('cpOld');
        if (oldInput) oldInput.focus();
    }

    function closeModal() {
        if (mask) mask.classList.remove('open');
    }

    // ── 模块2：事件绑定 ──
    if (openBtn) openBtn.addEventListener('click', openModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
    // 点击遮罩空白处或按 Esc 关闭
    if (mask) {
        mask.addEventListener('click', (e) => {
            if (e.target === mask) closeModal();
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeModal();
    });

    // ── 模块3：改密提交 ──
    if (form) {
        form.onsubmit = async (e) => {
            e.preventDefault();

            // 收集三个字段，密码不 strip
            const old_password = form.old_password.value;
            const new_password = form.new_password.value;
            const confirm = form.confirm.value;

            // 前端唯一校验：两次新密码一致；其余规则交给后端
            if (new_password !== confirm) {
                setMsg('两次输入的新密码不一致', 'error');
                return;
            }

            // 禁用按钮 + busy 样式，防重复提交并给视觉反馈
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.classList.add('is-busy');
            }
            setMsg('正在提交...');

            try {
                const res = await apiPost('/api/change_password', { old_password, new_password, confirm });
                if (res.ok) {
                    // 成功：显示成功消息，重置表单，延时关弹窗（不跳页，用户仍留在设置页）
                    setMsg(res.message || '密码修改成功。', 'success');
                    form.reset();
                    setTimeout(closeModal, 1200);
                } else {
                    // 失败（旧密码错/新旧相同等）：显示后端文案
                    setMsg(res.message || res.error || '修改失败', 'error');
                }
            } catch (err) {
                // 登录已失效（401）：直接跳回登录页
                if (err.status === 401) {
                    window.location.href = '/login';
                    return;
                }
                // 其它网络错误
                setMsg(err.message || '网络错误，请稍后重试', 'error');
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.classList.remove('is-busy');
                }
            }
        };
    }
})();
