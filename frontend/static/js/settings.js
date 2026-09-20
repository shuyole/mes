/* settings.js —— 基础数据配置页专属脚本 */
(function () {
    "use strict";

    function validIp(ip) {
        return /^(\d{1,3}\.){3}\d{1,3}$/.test(ip.trim());
    }

    async function initSettingsPage() {
        // 用户信息
        const user = window.getCurrentUser ? await getCurrentUser() : null;
        if (user) {
            const accEl = document.getElementById("currentAccount");
            if (accEl) accEl.textContent = user.username;
            const roleEl = document.getElementById("currentRoleLabel");
            if (roleEl) roleEl.textContent = user.role_label;

            const memOnly = document.querySelector('[data-member-only]');
            if (memOnly) memOnly.style.display = user.is_admin ? 'none' : '';
        }

        // 设备状态
        apiGet('/api/plc_status').then(data => {
            const plcBadge = document.getElementById("plcStatusBadge");
            if (plcBadge) {
                plcBadge.className = 'badge ' + (data.connected ? 'badge-done' : 'badge-alarm');
                plcBadge.textContent = data.connected ? '在线' : '离线（本地仿真可用）';
            }
            const lineBadge = document.getElementById("lineStatusBadge");
            if (lineBadge) {
                lineBadge.className = 'badge ' + (data.running ? 'badge-run' : 'badge-idle');
                lineBadge.textContent = data.running ? '运行中' : '停止';
            }
            const ipInput = document.getElementById("plcIpInput");
            if (ipInput && data.ip) ipInput.value = data.ip;
            const portInput = document.getElementById("plcPortInput");
            if (portInput && data.port) portInput.value = data.port;
            const addrReadonly = document.getElementById("plcAddrReadonly");
            if (addrReadonly && data.ip) addrReadonly.textContent = `${data.ip}:${data.port}`;
        }).catch(() => {});

        // 基础数据
        apiGet('/api/config').then(data => {
            if (!data.ok) return;
            const cfgFront = document.getElementById("cfgFrontendPort");
            if (cfgFront && data.frontend_port) cfgFront.textContent = data.frontend_port;
            const cfgBack = document.getElementById("cfgBackendPort");
            if (cfgBack && data.backend_port) cfgBack.textContent = data.backend_port;

            // 数据库角标：按后端实际生效的引擎渲染，避免静态文案误导
            const dbBadge = document.getElementById("dbStatusBadge");
            if (dbBadge && data.db_engine) {
                const isMysql = data.db_engine === "mysql";
                dbBadge.className = "badge " + (isMysql ? "badge-done" : "badge-idle");
                dbBadge.textContent = isMysql
                    ? `已连接 MySQL · ${data.db_host || ""}/${data.db_name || ""}`
                    : "已连接 SQLite（本地兜底）";
            }

            const prodBody = document.getElementById("settingsProductsBody");
            if (prodBody && data.products) {
                prodBody.innerHTML = data.products.map(p => `
                    <tr>
                        <td>${p.code}</td>
                        <td>${p.name}</td>
                        <td>${p.model || '-'}</td>
                        <td>${p.cycle_time || 24}s</td>
                    </tr>
                `).join('');
            }

            const stBody = document.getElementById("settingsStationsBody");
            if (stBody && data.station_defs) {
                stBody.innerHTML = data.station_defs.map(s => `
                    <tr>
                        <td>${s.code}</td>
                        <td>${s.name}</td>
                        <td>${s.full_name || s.name}</td>
                        <td>${s.role || '-'}</td>
                        <td>${s.cycle_sec || 3}s</td>
                        <td>HR${s.plc_address || 10}</td>
                    </tr>
                `).join('');
            }
        }).catch(() => {});

        // PLC 配置表单
        var plcForm = document.getElementById("plcConfigForm");
        if (plcForm) {
            var ipInput = document.getElementById("plcIpInput");
            var portInput = document.getElementById("plcPortInput");
            var plcSubmit = document.getElementById("plcSaveSubmit");

            plcForm.onsubmit = async (e) => {
                e.preventDefault();
                if (ipInput && !validIp(ipInput.value)) {
                    ipInput.setCustomValidity("请输入正确的 IPv4 地址");
                    ipInput.reportValidity();
                    return;
                }
                var port = parseInt(portInput && portInput.value, 10);
                if (!port || port < 1 || port > 65535) {
                    if (portInput) {
                        portInput.setCustomValidity("端口必须是 1~65535 之间的数字");
                        portInput.reportValidity();
                    }
                    return;
                }

                if (plcSubmit) {
                    plcSubmit.classList.add("is-busy");
                    plcSubmit.textContent = "保存并重连中...";
                    plcSubmit.disabled = true;
                }

                try {
                    const res = await apiPost('/api/plc/config', {
                        ip: ipInput.value.trim(),
                        port: port,
                        reconnect: 1
                    });
                    const msgEl = document.getElementById('settingsMsg');
                    if (msgEl) {
                        msgEl.textContent = res.message || (res.ok ? '保存成功' : res.error);
                        msgEl.style.display = '';
                    }
                    if (window.showToast) showToast(res.message || '配置已保存', res.ok);
                } catch (err) {
                    if (window.showToast) showToast('保存失败，请重试', false);
                } finally {
                    if (plcSubmit) {
                        plcSubmit.classList.remove("is-busy");
                        plcSubmit.textContent = "保存通讯参数";
                        plcSubmit.disabled = false;
                    }
                }
            };
        }

        // 修改密码弹窗
        var openBtn = document.getElementById("openChangePwdBtn");
        var mask = document.getElementById("changePwdMask");
        var pwdForm = document.getElementById("changePwdForm");
        var cancelBtn = document.getElementById("changePwdCancel");
        var pwdSubmit = document.getElementById("changePwdSubmit");
        var msgEl = document.getElementById("changePwdMsg");

        if (openBtn && mask && pwdForm) {
            function showMsg(text, type) {
                if (!msgEl) return;
                msgEl.textContent = text;
                msgEl.className = "modal-msg" + (type ? " " + type : "");
            }

            function openPwdModal() {
                showMsg("", "");
                pwdForm.reset();
                mask.classList.add("open");
                var oldInput = document.getElementById("cpOld");
                if (oldInput) oldInput.focus();
            }

            function closePwdModal() {
                mask.classList.remove("open");
            }

            openBtn.onclick = openPwdModal;
            if (cancelBtn) cancelBtn.onclick = closePwdModal;
            mask.onclick = function (e) {
                if (e.target === mask) closePwdModal();
            };

            pwdForm.onsubmit = async (e) => {
                e.preventDefault();
                var oldPwd = (document.getElementById("cpOld") || {}).value || "";
                var newPwd = (document.getElementById("cpNew") || {}).value || "";
                var confirmPwd = (document.getElementById("cpConfirm") || {}).value || "";

                if (!oldPwd) { showMsg("请输入旧密码。", "error"); return; }
                if (newPwd.length < 6) { showMsg("新密码至少 6 位。", "error"); return; }
                if (newPwd !== confirmPwd) { showMsg("两次输入的新密码不一致。", "error"); return; }
                if (newPwd === oldPwd) { showMsg("新密码不能与旧密码相同。", "error"); return; }

                if (pwdSubmit) {
                    pwdSubmit.classList.add("is-busy");
                    pwdSubmit.textContent = "提交中...";
                    pwdSubmit.disabled = true;
                }
                try {
                    const res = await apiPost("/api/change_password", {
                        old_password: oldPwd,
                        new_password: newPwd,
                        confirm: confirmPwd
                    });
                    if (res && res.ok) {
                        closePwdModal();
                        if (typeof showToast === "function") {
                            showToast(res.message || "密码修改成功", true);
                        }
                    } else {
                        showMsg((res && res.message) || "修改失败，请重试。", "error");
                    }
                } catch (err) {
                    showMsg("网络错误，请稍后重试。", "error");
                } finally {
                    if (pwdSubmit) {
                        pwdSubmit.classList.remove("is-busy");
                        pwdSubmit.textContent = "确认修改";
                        pwdSubmit.disabled = false;
                    }
                }
            };
        }
    }

    if (window.registerPage) {
        window.registerPage('settings', initSettingsPage);
    }
})();
