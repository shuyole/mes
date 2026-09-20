/* users.js —— 用户权限管理页专属脚本 */
(function () {
    "use strict";

    async function loadUsers() {
        const tbody = document.getElementById('usersTableBody');
        if (!tbody) return;

        try {
            const currentUser = window.getCurrentUser ? await getCurrentUser() : null;
            const myUsername = currentUser ? currentUser.username : '';

            const res = await apiGet('/api/users');
            if (!res.ok) throw new Error(res.error || '获取用户列表失败');

            const users = res.users || [];
            const rootAdmin = res.root_admin || 'admin';

            if (!users.length) {
                tbody.innerHTML = '<tr><td colspan="6" class="empty">暂无账号</td></tr>';
                return;
            }

            tbody.innerHTML = users.map(user => {
                const isMe = user.username === myUsername;
                const isRoot = user.username === rootAdmin;
                const statusBadge = user.status === '启用' ? 'badge-done' : 'badge-alarm';
                const roleLabel = user.role === 'admin' ? '管理员' : '普通成员';

                let actionHtml = '';
                if (isMe) {
                    actionHtml = '<span class="protected-text">当前登录</span>';
                } else if (isRoot) {
                    actionHtml = '<span class="protected-text">内置管理员（受保护）</span>';
                } else {
                    const toggleStatusBtn = user.status === '启用'
                        ? `<button class="btn btn-sm btn-red" onclick="manageUser(${user.id}, 'disable', '停用账号 ${user.username}？')">停用</button>`
                        : `<button class="btn btn-sm btn-green" onclick="manageUser(${user.id}, 'enable')">启用</button>`;

                    const resetBtn = `<button class="btn btn-sm" onclick="manageUser(${user.id}, 'reset', '将 ${user.username} 密码重置为 123456？')">重置密码</button>`;

                    const toggleRoleBtn = user.role === 'admin'
                        ? `<button class="btn btn-sm btn-amber" onclick="manageUserRole(${user.id}, 'member', '将 ${user.username} 降为普通成员？')">降为成员</button>`
                        : `<button class="btn btn-sm btn-green" onclick="manageUserRole(${user.id}, 'admin', '将 ${user.username} 升为管理员？')">升为管理员</button>`;

                    let deleteBtn = '';
                    if (user.role !== 'admin' || myUsername === rootAdmin) {
                        deleteBtn = `<button class="btn btn-sm btn-red" onclick="manageUser(${user.id}, 'delete', '删除账号 ${user.username}？该操作不可恢复。')">删除账号</button>`;
                    }

                    actionHtml = `<div class="user-actions-row">${toggleStatusBtn} ${resetBtn} ${toggleRoleBtn} ${deleteBtn}</div>`;
                }

                return `
                    <tr>
                        <td>${user.username}</td>
                        <td>${user.display_name || '-'}</td>
                        <td>${roleLabel}</td>
                        <td><span class="badge ${statusBadge}">${user.status}</span></td>
                        <td>${user.created_at || '-'}</td>
                        <td>${actionHtml}</td>
                    </tr>
                `;
            }).join('');
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="6" class="empty" style="color:var(--red);">加载失败: ${e.message}</td></tr>`;
        }
    }

    window.manageUser = async function (userId, action, confirmText) {
        if (confirmText && !confirm(confirmText)) return;
        try {
            const res = await apiPost(`/api/users/${userId}`, { action });
            if (res.ok) {
                if (window.showToast) showToast(res.message || '操作成功', true);
                loadUsers();
            } else {
                if (window.showToast) showToast(res.error || '操作失败', false);
            }
        } catch (e) {
            if (window.showToast) showToast(e.message || '网络错误', false);
        }
    };

    window.manageUserRole = async function (userId, role, confirmText) {
        if (confirmText && !confirm(confirmText)) return;
        try {
            const res = await apiPost(`/api/users/${userId}`, { action: 'role', role });
            if (res.ok) {
                if (window.showToast) showToast(res.message || '操作成功', true);
                loadUsers();
            } else {
                if (window.showToast) showToast(res.error || '操作失败', false);
            }
        } catch (e) {
            if (window.showToast) showToast(e.message || '网络错误', false);
        }
    };

    function initUsersPage() {
        loadUsers();
    }

    if (window.registerPage) {
        window.registerPage('users', initUsersPage);
    }
})();
