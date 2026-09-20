// 装配产线：标签页切换 + 工位/机械臂/日志定时刷新
(function () {
    'use strict';

    let timer = null;

    function initTabs() {
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(item => item.classList.remove('active'));
                document.querySelectorAll('.tab-panel').forEach(item => item.classList.remove('active'));
                tab.classList.add('active');
                const target = document.getElementById('tab-' + tab.dataset.tab);
                if (target) target.classList.add('active');
            });
        });
    }

    function renderTrace(records) {
        const body = document.getElementById('traceBody');
        const empty = document.getElementById('traceEmpty');
        if (!body) return;
        if (!records || !records.length) {
            body.innerHTML = '';
            if (empty) empty.style.display = '';
            return;
        }
        if (empty) empty.style.display = 'none';
        body.innerHTML = records.map(item => `
            <tr>
                <td>${item.created_at || ''}</td>
                <td>${item.order_no || ''}</td>
                <td>${item.station_name || ''}</td>
                <td>${item.ok_qty || 0}</td>
                <td>${item.ng_qty || 0}</td>
                <td>${item.status || ''}</td>
            </tr>
        `).join('');
    }

    function createInitLinePage(mode) {
        return function() {
            initTabs();
            const isVirtual = mode === 'virtual';
            const lineApi = isVirtual ? '/api/virtual' : '/api/line';

            // 权限元素展示
            const user = window.getCurrentUser ? window.getCurrentUser() : null;
            if (user && !user.is_admin) {
                const memOnly = document.querySelector('[data-member-only]');
                if (memOnly) memOnly.style.display = '';
            }

            function refresh() {
                apiGet(lineApi).then(data => {
                    const orderEl = document.getElementById('lineOrder');
                    if (orderEl) orderEl.textContent = data.order_no || '空闲';
                    const prodEl = document.getElementById('lineProduct');
                    if (prodEl) prodEl.textContent = data.product_name || '等待下发';
                    const progEl = document.getElementById('lineProgress');
                    if (progEl) progEl.textContent = `${data.completed_qty || 0}/${data.quantity || 0}`;
                    const pieceEl = document.getElementById('linePiece');
                    if (pieceEl) pieceEl.textContent = `${data.piece_progress || 0}%`;

                    if (data.robot) {
                        const rState = document.getElementById('robotState');
                        if (rState) rState.textContent = data.robot.status || '待机';
                        const rPos = document.getElementById('robotPos');
                        if (rPos) rPos.textContent = data.robot.position || 'HOME';
                        const rTask = document.getElementById('robotTask');
                        if (rTask) rTask.textContent = data.robot.task || '空闲';
                    }

                    const hint = document.getElementById('lineHint');
                    if (hint && !isVirtual) {
                        hint.textContent = data.plc_connected
                            ? '物理车间已联机，工位随 PLC 状态变化。'
                            : '物理车间未联机，工位保持离线静止。请先到设备管理连接，或打开「虚拟产线」。';
                    }

                    if (window.renderProcessRail) {
                        renderProcessRail(document.getElementById('lineProcess'), data.stations || []);
                    }
                    if (window.renderFactoryLine) {
                        renderFactoryLine(document.getElementById('lineStations'), data.stations || []);
                    }

                    if (data.logs) {
                        const box = document.getElementById('logList');
                        if (box) {
                            if (!data.logs.length) {
                                box.innerHTML = '<div class="empty">产线运行后，这里会记录工单、进度、节拍和当前工位。</div>';
                            } else {
                                box.innerHTML = data.logs.map(item => {
                                    const tag = item.level && item.level !== 'INFO' ? ` [${item.level}]` : '';
                                    return `<div class="log-item"><b>${item.created_at}</b>${tag} ${item.message}</div>`;
                                }).join('');
                            }
                        }
                    }
                    renderTrace(data.records);
                }).catch(() => {});

                if (!isVirtual) {
                    apiGet('/api/logs?category=line').then(logs => {
                        const box = document.getElementById('logList');
                        if (!box) return;
                        if (!logs || !logs.length) {
                            box.innerHTML = '<div class="empty">产线运行后，这里会记录工单、进度、节拍和当前工位。</div>';
                            return;
                        }
                        box.innerHTML = logs.map(item => {
                            const tag = item.level && item.level !== 'INFO' ? ` [${item.level}]` : '';
                            return `<div class="log-item"><b>${item.created_at}</b>${tag} ${item.message}</div>`;
                        }).join('');
                    }).catch(() => {});
                }
            }

            refresh();
            timer = setInterval(refresh, 1500);

            return () => {
                if (timer) clearInterval(timer);
            };
        };
    }

    // 全局指令发送函数
    window.sendCommand = function (command) {
        const mode = window.location.hash.includes('virtual') ? 'virtual' : 'real';
        apiPost('/api/line/command', { command, source: mode }).then(data => {
            const hint = document.getElementById('lineHint');
            if (hint) hint.textContent = data.message || data.error || hint.textContent;
            if (window.showToast) showToast(data.message || `已下发指令: ${command}`, 'info');
        }).catch(() => {});
    };

    window.injectFaultST = function (code = 'ST04') {
        apiPost('/api/line/inject_fault', { station_code: code }).then(res => {
            if (window.showToast) showToast(res.message || `已模拟注入 ${code} 故障`, 'warn');
        }).catch(() => {
            if (window.showToast) showToast('注入故障失败', 'error');
        });
    };

    window.clearFaultST = function () {
        apiPost('/api/line/clear_fault', {}).then(res => {
            if (window.showToast) showToast(res.message || '产线故障已全部清除', 'success');
        }).catch(() => {
            if (window.showToast) showToast('清除故障失败', 'error');
        });
    };

    window.exportTraceCSV = function () {
        window.open(`${API_BASE}/api/export/trace`, '_blank');
    };

    if (window.registerPage) {
        window.registerPage('line', createInitLinePage('real'));
        window.registerPage('virtual', createInitLinePage('virtual'));
    }
})();
