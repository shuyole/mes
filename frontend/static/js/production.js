// 生产数据：产量趋势与工位产出分布图表
(function () {
    'use strict';

    let trendChartInstance = null;
    let stationChartInstance = null;

    function renderProgressCtl(order) {
        const qty = order.quantity || 0;
        const done = order.completed_qty || 0;
        const pct = order.status === '已完成' ? 100 : (order.progress != null ? order.progress : (qty ? Math.floor(done * 100 / qty) : 0));
        const st = order.status || '待生产';
        let dots = '';
        for (let n = 0; n < 7; n++) {
            dots += `<span class="${pct >= (n + 1) * 100 / 7 ? 'on' : ''}"></span>`;
        }
        return `
            <div class="progress-ctl" data-id="${order.id}" data-qty="${qty}" data-done="${done}" data-progress="${pct}" data-status="${st}">
                <div class="progress-ctl-row">
                    <button type="button" class="progress-step" data-delta="-1" aria-label="减少完成数" ${done <= 0 ? 'disabled' : ''}>−</button>
                    <div class="progress-track" role="slider" tabindex="0" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" aria-label="拖动调整完成进度">
                        <span class="progress-fill" style="width:${pct}%"></span>
                        <span class="progress-thumb" style="left:${pct}%"></span>
                    </div>
                    <button type="button" class="progress-step" data-delta="1" aria-label="增加完成数" ${done >= qty ? 'disabled' : ''}>+</button>
                </div>
                <div class="progress-meta">
                    <b class="progress-pct">${pct}%</b>
                    <label class="progress-qty-edit">
                        <input class="progress-input" type="number" min="0" max="${qty}" value="${done}" aria-label="已完成数量">
                        <span>/${qty}</span>
                    </label>
                </div>
                <div class="progress-stations" aria-hidden="true">${dots}</div>
            </div>
        `;
    }

    function renderStatusCtl(order) {
        const st = order.status || '待生产';
        const badgeMap = { '待生产': 'badge-wait', '生产中': 'badge-run', '暂停': 'badge-pause', '返工': 'badge-rework', '已完成': 'badge-done' };
        const badgeClass = badgeMap[st] || 'badge-wait';
        return `
            <div class="status-ctl" data-id="${order.id}" data-status="${st}">
                <button type="button" class="badge status-btn ${badgeClass}" aria-haspopup="listbox" aria-expanded="false">${st}</button>
                <div class="status-menu" hidden>
                    <button type="button" data-status="待生产">待生产</button>
                    <button type="button" data-status="生产中">生产中</button>
                    <button type="button" data-status="暂停">暂停</button>
                    <button type="button" data-status="返工">返工</button>
                    <button type="button" data-status="已完成">已完成</button>
                </div>
            </div>
        `;
    }

    function initCharts(trend, stationStats) {
        if (typeof Chart === 'undefined') return;

        const gridColor = 'rgba(34,211,238,0.1)';
        Chart.defaults.color = '#94a3b8';
        Chart.defaults.font.family = "'Consolas', 'Segoe UI', 'Microsoft YaHei', sans-serif";
        Chart.defaults.font.size = 12;
        Chart.defaults.borderColor = gridColor;

        if (trendChartInstance) trendChartInstance.destroy();
        if (stationChartInstance) stationChartInstance.destroy();

        const trendCtx = document.getElementById('trendChart');
        if (trendCtx && trend) {
            trendChartInstance = new Chart(trendCtx, {
                type: 'line',
                data: {
                    labels: trend.map(item => item.day),
                    datasets: [
                        {
                            label: '计划产量',
                            data: trend.map(item => Number(item.planned || 0)),
                            borderColor: '#38bdf8',
                            backgroundColor: 'rgba(56, 189, 248, 0.1)',
                            fill: true,
                            tension: 0.35,
                            borderWidth: 2,
                            pointRadius: 4,
                            pointHoverRadius: 6
                        },
                        {
                            label: '合格产量',
                            data: trend.map(item => Number(item.completed || 0)),
                            borderColor: '#34d399',
                            backgroundColor: 'rgba(52, 211, 153, 0.15)',
                            fill: true,
                            tension: 0.35,
                            borderWidth: 2.5,
                            pointRadius: 4,
                            pointHoverRadius: 6
                        },
                        {
                            label: '不良数量',
                            data: trend.map(item => Number(item.ng_qty || 0)),
                            borderColor: '#f87171',
                            backgroundColor: 'rgba(248, 113, 113, 0.1)',
                            fill: true,
                            tension: 0.35,
                            borderWidth: 2,
                            pointRadius: 4,
                            pointHoverRadius: 6
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    plugins: {
                        legend: {
                            position: 'top',
                            labels: { color: '#e2e8f0', usePointStyle: true, boxWidth: 8 }
                        }
                    },
                    scales: {
                        y: { grid: { color: gridColor }, min: 0 }
                    }
                }
            });
        }

        const stationCtx = document.getElementById('stationChart');
        if (stationCtx && stationStats) {
            stationChartInstance = new Chart(stationCtx, {
                type: 'bar',
                data: {
                    labels: stationStats.map(item => item.station_name),
                    datasets: [
                        {
                            label: '合格过站数',
                            data: stationStats.map(item => Number(item.ok_qty || 0)),
                            backgroundColor: 'rgba(34, 211, 238, 0.75)',
                            borderColor: '#22d3ee',
                            borderWidth: 1,
                            borderRadius: 4
                        },
                        {
                            label: '不良检测数',
                            data: stationStats.map(item => Number(item.ng_qty || 0)),
                            backgroundColor: 'rgba(248, 113, 113, 0.75)',
                            borderColor: '#f87171',
                            borderWidth: 1,
                            borderRadius: 4
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'top',
                            labels: { color: '#e2e8f0', usePointStyle: true, boxWidth: 8 }
                        }
                    },
                    scales: {
                        x: { grid: { display: false } },
                        y: { grid: { color: gridColor }, min: 0 }
                    }
                }
            });
        }
    }

    async function initProductionPage() {
        try {
            const data = await apiGet('/api/production');
            if (!data.ok) return;

            // 统计卡片
            const plannedEl = document.getElementById('prodPlanned');
            if (plannedEl) plannedEl.textContent = data.planned_qty || 0;
            const compEl = document.getElementById('prodCompleted');
            if (compEl) compEl.textContent = data.completed_qty || 0;
            const ngEl = document.getElementById('prodNg');
            if (ngEl) ngEl.textContent = data.ng_qty || 0;
            const yieldEl = document.getElementById('prodYield');
            if (yieldEl) yieldEl.textContent = (data.yield_rate != null ? data.yield_rate : '100.0') + '%';

            // 图表
            initCharts(data.trend || [], data.station_stats || []);

            // 工单表格
            const orders = data.orders || [];
            const ordersBody = document.getElementById('prodOrdersBody');
            const ordersEmpty = document.getElementById('prodOrdersEmpty');
            if (ordersBody) {
                if (!orders.length) {
                    ordersBody.innerHTML = '';
                    if (ordersEmpty) ordersEmpty.style.display = '';
                } else {
                    if (ordersEmpty) ordersEmpty.style.display = 'none';
                    ordersBody.innerHTML = orders.map(order => `
                        <tr>
                            <td class="mono-cell">${order.order_no}</td>
                            <td>${order.product_name}</td>
                            <td>${order.quantity}</td>
                            <td>${renderProgressCtl(order)}</td>
                            <td data-done-cell>${order.completed_qty || 0}</td>
                            <td>${order.ng_qty || 0}</td>
                            <td data-station-cell>${order.current_station || '-'}</td>
                            <td>${renderStatusCtl(order)}</td>
                            <td>${order.created_at || ''}</td>
                        </tr>
                    `).join('');
                }
            }

            // 作业记录表格
            const records = data.records || [];
            const recordsBody = document.getElementById('prodRecordsBody');
            const recordsEmpty = document.getElementById('prodRecordsEmpty');
            if (recordsBody) {
                if (!records.length) {
                    recordsBody.innerHTML = '';
                    if (recordsEmpty) recordsEmpty.style.display = '';
                } else {
                    if (recordsEmpty) recordsEmpty.style.display = 'none';
                    recordsBody.innerHTML = records.map(item => `
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
            }
        } catch (e) {
            console.error('加载生产统计失败', e);
        }

        return () => {
            if (trendChartInstance) {
                trendChartInstance.destroy();
                trendChartInstance = null;
            }
            if (stationChartInstance) {
                stationChartInstance.destroy();
                stationChartInstance = null;
            }
        };
    }

    if (window.registerPage) {
        window.registerPage('production', initProductionPage);
    }
})();
