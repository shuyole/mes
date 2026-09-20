// 下单排产：工单创建 + 状态筛选 + 搜索 + 规格联动 + 范例填充
(function () {
    'use strict';

    let currentFilter = 'all';

    const PRODUCTS_MAP = {
        'WC-10W': { power: '10W', coils: 1, desc: '基础便携式Qi无线充，单线圈配置，工装治具定位快速，标准测试电压 9V/1.1A' },
        'WC-15W': { power: '15W', coils: 2, desc: '主流Qi2磁吸对齐无线充，双线圈+环形磁组装配，精密自动点胶，测试电压 9V/1.67A' },
        'WC-20W': { power: '20W', coils: 3, desc: '高功率多线圈立式底座无线充，多线圈重叠激光焊与独立测温，测试电压 12V/1.67A' }
    };

    function updateProductSpec() {
        const select = document.getElementById('selectProductCode');
        const specText = document.getElementById('productSpecText');
        if (!select || !specText) return;
        const val = select.value;
        const spec = PRODUCTS_MAP[val] || { power: '15W', coils: 2, desc: '标准无线充电发射器' };
        specText.innerHTML = `<span style="color:var(--cyan); font-weight:600;">[功率 ${spec.power} | 线圈数: ${spec.coils}]</span> ${spec.desc}`;
    }

    window.fillSampleOrder = function () {
        const d = new Date();
        const ymd = d.toISOString().slice(0, 10).replace(/-/g, '');
        const rand = Math.floor(100 + Math.random() * 900);
        const orderNo = `WC${ymd}-${rand}`;
        const inputOrderNo = document.getElementById('inputOrderNo');
        if (inputOrderNo) inputOrderNo.value = orderNo;
        const selectProduct = document.getElementById('selectProductCode');
        if (selectProduct) {
            const keys = Object.keys(PRODUCTS_MAP);
            selectProduct.value = keys[Math.floor(Math.random() * keys.length)];
            updateProductSpec();
        }
        const inputQty = document.getElementById('inputQuantity');
        if (inputQty) inputQty.value = [10, 15, 20, 30][Math.floor(Math.random() * 4)];
        const selectPriority = document.getElementById('selectPriority');
        if (selectPriority) selectPriority.value = String(Math.floor(Math.random() * 3) + 1);
        const inputRemark = document.getElementById('inputRemark');
        if (inputRemark) {
            const remarks = ['出口高标准样单', 'Qi2认证测试批次', '立式双工位急件', '电商首批试产订单'];
            inputRemark.value = remarks[Math.floor(Math.random() * remarks.length)];
        }
        if (window.showToast) showToast('已自动填入范例工单参数', true);
    };

    window.exportOrdersCSV = function () {
        window.open(`${API_BASE}/api/export/orders`, '_blank');
    };

    function applyFilter() {
        const searchBox = document.getElementById('searchBox');
        const keyword = (searchBox ? searchBox.value || '' : '').toLowerCase();
        document.querySelectorAll('.order-row').forEach(row => {
            const okStatus = currentFilter === 'all' || row.dataset.status === currentFilter;
            const okSearch = !keyword || (row.dataset.search || '').toLowerCase().includes(keyword);
            row.style.display = okStatus && okSearch ? '' : 'none';
        });
    }

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

    async function loadOrders(isAdmin) {
        const tbody = document.getElementById('ordersTableBody');
        const empty = document.getElementById('ordersEmpty');
        try {
            const data = await apiGet('/api/orders');
            if (!data.ok) throw new Error(data.error || '获取工单失败');

            const inputOrderNo = document.getElementById('inputOrderNo');
            if (inputOrderNo && data.default_order_no) inputOrderNo.value = data.default_order_no;
            const inputDueDate = document.getElementById('inputDueDate');
            if (inputDueDate && data.today) inputDueDate.value = data.today;

            const orders = data.orders || [];
            if (!orders.length) {
                if (tbody) tbody.innerHTML = '';
                if (empty) empty.style.display = '';
                return;
            }
            if (empty) empty.style.display = 'none';

            const priMap = { 3: '紧急', 2: '加急', 1: '普通' };
            tbody.innerHTML = orders.map(order => {
                const pri = order.priority || 1;
                const isRework = order.status === '返工';
                const finishLabel = isRework ? '完成返工' : '强制完工';
                const hideDispatch = order.status !== '待生产';
                const hideFinish = !['生产中', '暂停', '返工'].includes(order.status);
                const hideRework = order.status !== '已完成';

                return `
                    <tr class="order-row" data-status="${order.status}" data-order-id="${order.id}" data-admin="${isAdmin ? '1' : '0'}" data-search="${order.order_no} ${order.product_name}">
                        <td class="priority-${pri}">${priMap[pri] || '普通'}</td>
                        <td class="mono-cell">${order.order_no}</td>
                        <td>${order.product_name}</td>
                        <td data-qty-cell>${order.completed_qty || 0}/${order.quantity}</td>
                        <td class="progress-cell">${renderProgressCtl(order)}</td>
                        <td>${renderStatusCtl(order)}</td>
                        <td>${order.due_date || '-'}</td>
                        <td class="order-actions">
                            ${isAdmin ? `<button type="button" class="btn btn-sm btn-green js-dispatch" onclick="dispatchOrder(${order.id})" ${hideDispatch ? 'hidden' : ''}>下发产线</button>` : ''}
                            <button type="button" class="btn btn-sm js-finish" ${hideFinish ? 'hidden' : ''}>${finishLabel}</button>
                            <button type="button" class="btn btn-sm btn-amber js-rework" ${hideRework ? 'hidden' : ''}>返工</button>
                            <button type="button" class="btn btn-sm btn-red" onclick="deleteOrder(${order.id}, '${order.order_no}')">删除</button>
                        </td>
                    </tr>
                `;
            }).join('');

            applyFilter();
        } catch (e) {
            if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="empty" style="color:var(--red);">加载失败: ${e.message}</td></tr>`;
        }
    }

    window.dispatchOrder = async function (id) {
        try {
            const res = await apiPost(`/api/orders/${id}/dispatch`, {});
            if (res.ok) {
                if (window.showToast) showToast(res.message || '已成功下发到产线', true);
                await loadOrders(window.isCurrentAdmin ? isCurrentAdmin() : false);
            } else {
                if (window.showToast) showToast(res.error || '下发失败', false);
            }
        } catch (e) {
            if (window.showToast) showToast(e.message || '下发失败', false);
        }
    };

    window.deleteOrder = async function (id, orderNo) {
        if (!confirm(`确认删除工单 ${orderNo} 吗？`)) return;
        try {
            const res = await apiDelete(`/api/orders/${id}`);
            if (res.ok) {
                if (window.showToast) showToast('工单已删除', true);
                await loadOrders(window.isCurrentAdmin ? isCurrentAdmin() : false);
            } else {
                if (window.showToast) showToast(res.error || '删除失败', false);
            }
        } catch (e) {
            if (window.showToast) showToast(e.message || '删除失败', false);
        }
    };

    function initOrdersPage() {
        const user = window.getCurrentUser ? window.getCurrentUser() : null;
        const isAdmin = user && user.is_admin;

        if (isAdmin) {
            const adminEl = document.getElementById('orderHintAdmin');
            if (adminEl) adminEl.style.display = '';
            const memEl = document.getElementById('orderHintMember');
            if (memEl) memEl.style.display = 'none';
        } else {
            const adminEl = document.getElementById('orderHintAdmin');
            if (adminEl) adminEl.style.display = 'none';
            const memEl = document.getElementById('orderHintMember');
            if (memEl) memEl.style.display = '';
        }

        const selectProduct = document.getElementById('selectProductCode');
        if (selectProduct) {
            selectProduct.addEventListener('change', updateProductSpec);
            updateProductSpec();
        }

        // 筛选按钮
        document.querySelectorAll('#orderFilterGroup .filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('#orderFilterGroup .filter-btn').forEach(item => item.classList.remove('active'));
                btn.classList.add('active');
                currentFilter = btn.dataset.filter;
                applyFilter();
            });
        });

        // 搜索框
        const searchBox = document.getElementById('searchBox');
        if (searchBox) searchBox.addEventListener('input', applyFilter);

        // 表单提交
        const form = document.getElementById('orderForm');
        if (form) {
            form.onsubmit = async (e) => {
                e.preventDefault();
                const submitBtn = document.getElementById('btnSubmitOrder');
                if (submitBtn) submitBtn.disabled = true;

                const payload = {
                    order_no: form.order_no.value.trim(),
                    product_code: form.product_code.value,
                    quantity: parseInt(form.quantity.value, 10) || 1,
                    priority: parseInt(form.priority.value, 10) || 1,
                    due_date: form.due_date.value || null,
                    remark: form.remark.value.trim()
                };

                try {
                    const res = await apiPost('/api/orders', payload);
                    if (res.ok) {
                        if (window.showToast) showToast(res.message || '工单创建成功', true);
                        form.remark.value = '';
                        await loadOrders(isAdmin);
                    } else {
                        if (window.showToast) showToast(res.error || '创建失败', false);
                    }
                } catch (err) {
                    if (window.showToast) showToast(err.message || '网络错误', false);
                } finally {
                    if (submitBtn) submitBtn.disabled = false;
                }
            };
        }

        loadOrders(isAdmin);
    }

    if (window.registerPage) {
        window.registerPage('orders', initOrdersPage);
    }
})();
