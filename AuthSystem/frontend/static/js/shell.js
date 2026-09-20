/**
 * shell.js —— 主页/设置页共用的外壳脚本
 * 负责：页面登录守卫、顶栏用户信息与时钟、侧边栏底部信息、退出登录。
 * 未登录或会话失效时（/api/me 返回 401）直接跳回登录页。
 */
(function () {
    "use strict";

    let _user = null;

    /** 退出登录：清空后端会话后回到登录页 */
    async function logout() {
        try {
            await apiPost('/api/logout', {});
        } catch (e) {
            // 退出失败也照常跳转
        }
        window.location.href = '/login';
    }

    /** 顶栏时钟：每秒刷新一次 */
    function startClock() {
        const el = document.getElementById('clock');
        if (!el) return;
        const pad = (n) => String(n).padStart(2, '0');
        function tick() {
            const d = new Date();
            el.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
        }
        tick();
        setInterval(tick, 1000);
    }

    /** 把用户信息渲染到顶栏、侧边栏底部以及各页面的可选占位符 */
    function renderUser(user) {
        const name = user.display_name || user.username;

        const nameEl = document.getElementById('userName');
        if (nameEl) nameEl.textContent = name;

        const chip = document.getElementById('roleChip');
        if (chip) {
            chip.textContent = user.role_label;
            chip.className = 'role-chip ' + (user.is_admin ? 'admin' : 'member');
        }

        const footer = document.querySelector('.sidebar-footer');
        if (footer) {
            footer.innerHTML = `<strong>无线充柔性线</strong>${user.is_admin ? '管理员权限' : '操作员权限'}`;
        }

        // 页面上的可选占位符：存在才填充，不存在就跳过
        const values = {
            statAccount: user.username,
            statRole: user.role_label,
            statStatus: '启用',
            statSession: '有效',
            infoUsername: user.username,
            infoDisplayName: name,
            infoRole: user.role_label,
            currentAccount: user.username,
            currentRoleLabel: user.role_label,
        };
        Object.keys(values).forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.textContent = values[id];
        });
    }

    /** 页面启动：绑定时钟与退出按钮，校验登录态后渲染信息 */
    async function boot() {
        startClock();

        const logoutLink = document.getElementById('logoutLink');
        if (logoutLink) logoutLink.addEventListener('click', logout);

        try {
            _user = await apiGet('/api/me');
        } catch (err) {
            window.location.href = '/login';
            return;
        }
        renderUser(_user);
        // 通知页面脚本：外壳已就绪，用户信息已可用
        document.dispatchEvent(new CustomEvent('shell:ready', { detail: _user }));
    }

    window.getShellUser = () => _user;
    window.shellLogout = logout;

    boot();
})();
