/* recipes.js —— 工艺配方节拍页专属脚本 */
(function () {
    "use strict";

    function initAnimation() {
        var targets = document.querySelectorAll(".js-rise");
        if (!targets.length) return;

        if (!("IntersectionObserver" in window)) {
            Array.prototype.forEach.call(targets, function (el) { el.classList.add("in"); });
            return;
        }

        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add("in");
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.08 });

        Array.prototype.forEach.call(targets, function (el, idx) {
            el.style.transitionDelay = Math.min(idx * 60, 360) + "ms";
            observer.observe(el);
        });
    }

    async function initRecipesPage() {
        try {
            const data = await apiGet('/api/config');
            if (!data.ok) return;

            const plan = data.plan;
            if (plan) {
                const hint = document.getElementById('taktHint');
                if (hint) {
                    hint.textContent = `客户需求 ${plan.demand_per_day} 件/天。额定上班 ${plan.shift_hours} 小时，午餐 ${plan.lunch_min} 分钟 + 休息 ${plan.rest_min} 分钟，每班净可用 ${plan.net_sec_shift} 秒；每天 ${plan.shifts} 班共 ${plan.net_sec_day} 秒。`;
                }
                const formula = document.getElementById('taktFormula');
                if (formula) {
                    formula.innerHTML = `节拍 = ${plan.net_sec_day} ÷ ${plan.demand_per_day} = <b>${plan.takt_sec} 秒/件</b>`;
                }
            }

            const products = data.products || [];
            const prodBody = document.getElementById('recipesProductsBody');
            if (prodBody) {
                prodBody.innerHTML = products.map(product => `
                    <tr>
                        <td class="mono-cell">${product.code}</td>
                        <td>
                            <strong>${product.name}</strong>
                            <div class="product-desc">${product.desc || product.model || ''}</div>
                        </td>
                        <td><span class="cyan-text">${product.power || '15W'}</span> / ${product.coils || 2}线圈</td>
                        <td class="mono-cell">${product.cycle_time || 24} 秒</td>
                    </tr>
                `).join('');
            }

            const stations = data.station_defs || [];
            const stBody = document.getElementById('recipesStationsBody');
            if (stBody) {
                stBody.innerHTML = stations.map(station => `
                    <tr>
                        <td><strong class="cyan-text">${station.code}</strong></td>
                        <td>
                            <div>${station.name}</div>
                            <span class="station-role-sub">${station.role || ''}</span>
                        </td>
                        <td class="mono-cell">${station.cycle_sec || 3}s</td>
                        <td class="mono-cell">HR${station.plc_address || 10}</td>
                        <td>
                            <button type="button" class="btn btn-sm diag-btn" onclick="openStationDrawer('${station.code}')">🔍 诊断</button>
                        </td>
                    </tr>
                `).join('');
            }
        } catch (e) {
            console.error('加载配方配置失败', e);
        }

        initAnimation();
    }

    if (window.registerPage) {
        window.registerPage('recipes', initRecipesPage);
    }
})();
