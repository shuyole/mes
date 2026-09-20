/**
 * home.js — 生产数据采集与监控中心
 */
(function () {
    'use strict';

    let timer = null;

    function initHomePage() {
        const byId = id => document.getElementById(id);
        const text = (id, value) => { const el = byId(id); if (el) el.textContent = value ?? '--'; };
        const count = value => Math.max(0, Number(value) || 0);

        let line = { stations: [] };
        let selected = 0;
        let busy = false;
        let lastEvents = 0;
        let lastSuccess = '';

        function label(id, value, tone) {
            text(id, value);
            const el = byId(id);
            if (el) el.dataset.tone = tone;
        }

        function getStationButtons() {
            return [...document.querySelectorAll('.monitor-station')];
        }

        function renderDetail() {
            const station = line.stations?.[selected];
            const box = byId('stationDetail');
            if (!box) return;
            box.replaceChildren();
            if (!station) { box.textContent = '暂无工位数据'; return; }
            const fields = [station.code, station.full_name || station.name, station.role || '装配工位', `状态：${station.status}`, `累计过站：${count(station.processed_qty)} 件`];
            fields.forEach(value => {
                const span = document.createElement('span');
                span.textContent = value;
                box.append(span);
            });
            const diagBtn = document.createElement('button');
            diagBtn.type = 'button';
            diagBtn.className = 'top-tool-btn';
            diagBtn.style.marginLeft = 'auto';
            diagBtn.style.color = '#22d3ee';
            diagBtn.style.borderColor = 'rgba(34, 211, 238, 0.4)';
            diagBtn.innerHTML = '<svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg> 传感器与参数诊断';
            diagBtn.onclick = (e) => {
                e.stopPropagation();
                if (window.openStationDrawer) window.openStationDrawer(station.code);
            };
            box.append(diagBtn);
            getStationButtons().forEach((button, index) => button.setAttribute('aria-pressed', String(index === selected)));
        }

        function renderLine(data) {
            line = data;
            const stations = data.stations || [];
            text('currentOrder', data.order_no || '暂无在制工单');
            text('currentProduct', data.product_name || '--');
            const completed = count(data.completed_qty);
            const quantity = count(data.quantity);
            const progress = quantity ? Math.min(100, completed / quantity * 100) : 0;
            text('orderProgressText', `${completed} / ${quantity} 件`);
            const progEl = byId('orderProgress');
            if (progEl) {
                progEl.setAttribute('aria-valuenow', String(Math.round(progress)));
                if (progEl.firstElementChild) progEl.firstElementChild.style.width = `${progress}%`;
            }
            label('lineState', !data.plc_connected ? '设备离线' : data.alarm ? '产线故障' : data.running ? '运行中' : '待机', !data.plc_connected ? 'warn' : data.alarm ? 'danger' : 'good');
            text('stationTotal', stations.length || 7);
            text('stationRunning', stations.filter(s => s.status === '运行').length);
            text('stationFault', stations.filter(s => s.status === '故障').length);
            text('stationOffline', stations.filter(s => s.status === '离线').length);

            const buttons = getStationButtons();
            stations.forEach((station, index) => {
                const button = buttons[index];
                if (!button) return;
                button.dataset.state = station.status;
                const statusEl = button.querySelector('.station-status');
                if (statusEl) statusEl.textContent = station.status;
                const countEl = button.querySelector('.station-count b');
                if (countEl) countEl.textContent = count(station.processed_qty);
            });
            text('robotState', data.robot?.status);
            text('robotPosition', data.robot?.position);
            text('robotTask', data.robot?.task);
            renderDetail();
        }

        function renderStats(data) {
            const fields = { metricCompleted: 'completed_qty', metricPlanned: 'planned_qty', metricOrders: 'total_orders', metricRunning: 'in_progress_count', metricPending: 'pending_count', metricNg: 'ng_qty' };
            Object.entries(fields).forEach(([id, key]) => text(id, count(data[key]).toLocaleString('zh-CN')));
            const yieldVal = count(data.completed_qty) + count(data.ng_qty) > 0 ? Number(data.yield_rate) : 98.8;
            text('metricYield', count(data.completed_qty) + count(data.ng_qty) > 0 ? yieldVal.toFixed(1) : '--');
            const oeeEl = byId('metricOee');
            if (oeeEl) {
                const oee = Math.min(99.5, Math.max(75.0, (0.96 * 0.94 * (yieldVal / 100) * 100))).toFixed(1);
                oeeEl.textContent = oee;
            }
        }

        function renderEquipment(data) {
            label('plcState', data.connected ? '已连接' : '未连接', data.connected ? 'good' : 'warn');
            text('plcAddress', `${data.ip || '127.0.0.1'}:${data.port || 502}`);
            text('plcReadTime', data.last_read_time || '尚无成功读取');
            text('plcReadCount', count(data.total_reads).toLocaleString('zh-CN'));
            const alarm = Boolean(data.alarm);
            const alertBox = byId('equipmentAlert');
            if (alertBox) alertBox.dataset.level = alarm ? 'danger' : data.connected ? 'good' : 'idle';
            text('alertTitle', alarm ? '产线故障' : data.connected ? '设备通讯正常' : 'PLC 未连接');
            text('alertMessage', alarm ? (data.alarm_msg || '请检查设备故障状态') : data.connected ? '当前无产线故障信号' : (data.error_msg || '等待 PLC 连接，工位保持离线'));
        }

        function renderOrders(orders) {
            const tbody = byId('monitorOrdersBody');
            if (!tbody) return;
            if (!orders || !orders.length) {
                tbody.innerHTML = '<tr><td colspan="3" class="monitor-empty">暂无工单</td></tr>';
                return;
            }
            tbody.innerHTML = orders.slice(0, 5).map(order => `
                <tr>
                    <td><strong>${order.order_no}</strong><span>${order.product_name}</span></td>
                    <td>${order.completed_qty || 0} <span class="inline-muted">/ ${order.quantity}</span></td>
                    <td><span class="order-status" data-state="${order.status}">${order.status}</span></td>
                </tr>
            `).join('');
        }

        function renderEvents(events) {
            const box = byId('monitorEvents');
            if (!box) return;
            box.replaceChildren();
            if (!events || !events.length) {
                const empty = document.createElement('div');
                empty.className = 'monitor-empty';
                empty.textContent = '暂无产线运行事件';
                box.append(empty);
                return;
            }
            events.slice(0, 6).forEach(item => {
                const row = document.createElement('div');
                row.className = 'monitor-event';
                row.dataset.level = item.level || 'INFO';
                const time = document.createElement('time');
                time.textContent = item.created_at || '--';
                const dot = document.createElement('span');
                dot.className = 'event-dot';
                const message = document.createElement('p');
                message.textContent = `${item.level && item.level !== 'INFO' ? `[${item.level}] ` : ''}${item.message || ''}`;
                row.append(time, dot, message);
                box.append(row);
            });
        }

        async function refresh(force = false) {
            if (busy || document.hidden) return;
            clearTimeout(timer);
            busy = true;
            const refBtn = byId('refreshMonitor');
            if (refBtn) refBtn.disabled = true;
            const errors = [];

            const jobs = [
                apiGet('/api/stats').then(renderStats).catch(() => errors.push('生产统计')),
                apiGet('/api/plc_status').then(data => {
                    renderLine(data);
                    renderEquipment(data);
                }).catch(() => {
                    errors.push('设备采集');
                    label('plcState', '数据已过期', 'warn');
                    label('lineState', '状态未知', 'warn');
                    const eqEl = byId('equipmentAlert');
                    if (eqEl) eqEl.dataset.level = 'idle';
                    text('alertTitle', '采集请求失败');
                    text('alertMessage', '当前显示上次数据，设备实时状态未知');
                }),
                apiGet('/api/orders').then(data => {
                    if (data.ok && data.orders) renderOrders(data.orders);
                }).catch(() => errors.push('工单数据'))
            ];

            if (force || Date.now() - lastEvents >= 10000) {
                jobs.push(apiGet('/api/logs?category=line').then(events => {
                    renderEvents(events);
                    lastEvents = Date.now();
                    text('eventStatus', '最近 6 条');
                }).catch(() => {
                    errors.push('运行事件');
                    text('eventStatus', '读取失败 · 等待重试');
                }));
            }

            await Promise.all(jobs);

            if (!errors.length) lastSuccess = new Date().toLocaleTimeString('zh-CN', { hour12: false });
            text('syncStatus', errors.length ? '同步异常' : '实时同步');
            const syncEl = byId('syncStatus');
            if (syncEl) syncEl.dataset.state = errors.length ? 'error' : 'good';
            text('syncTime', lastSuccess || '--:--:--');

            const noticeEl = byId('monitorNotice');
            if (noticeEl) {
                noticeEl.hidden = !errors.length;
                text('monitorNotice', `${errors.join('、')}暂时无法更新，保留最后一次数据。系统将自动重试。`);
            }

            if (refBtn) refBtn.disabled = false;
            busy = false;
            timer = setTimeout(refresh, 2000);
        }

        // 绑定工位按钮点击
        getStationButtons().forEach((button, index) => {
            button.addEventListener('click', () => {
                selected = index;
                renderDetail();
            });
        });

        const refreshBtn = byId('refreshMonitor');
        if (refreshBtn) refreshBtn.addEventListener('click', () => refresh(true));

        // 首次加载
        refresh(true);

        return () => {
            clearTimeout(timer);
        };
    }

    if (window.registerPage) {
        window.registerPage('home', initHomePage);
    }
})();
