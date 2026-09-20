/* alarms.js —— 异常发生管理页专属脚本 */
(function () {
    "use strict";

    let timer = null;

    var ACTIONS = {
        alarm: {
            url: "/api/line/command",
            payload: { command: "alarm" },
            sound: "alarm",
            toast: ["模拟急停已下发", "error"]
        },
        reset: {
            url: "/api/line/command",
            payload: { command: "reset" },
            sound: "success",
            toast: ["产线故障已复位", "success"]
        },
        inject: {
            url: "/api/line/inject_fault",
            payload: { station_code: "ST04" },
            sound: null,
            toast: ["已注入 ST04 工位故障模拟", "warn"]
        },
        clear: {
            url: "/api/line/clear_fault",
            payload: {},
            sound: null,
            toast: ["已清除全部工位故障", "success"]
        }
    };

    function refreshData() {
        apiGet('/api/line').then(line => {
            const cardAlarm = document.getElementById('cardAlarm');
            const alarmVal = document.getElementById('alarmVal');
            const alarmMsg = document.getElementById('alarmMsg');
            if (cardAlarm && alarmVal && alarmMsg) {
                if (line.alarm) {
                    cardAlarm.className = 'stat-card red';
                    alarmVal.textContent = '报警';
                    alarmMsg.textContent = line.alarm_msg || '急停 / 互锁故障';
                } else {
                    cardAlarm.className = 'stat-card green';
                    alarmVal.textContent = '正常';
                    alarmMsg.textContent = '无急停 / 互锁故障';
                }
            }

            const lineStateVal = document.getElementById('lineStateVal');
            if (lineStateVal) lineStateVal.textContent = line.running ? '运行' : '停止';
            const lineOrderVal = document.getElementById('lineOrderVal');
            if (lineOrderVal) lineOrderVal.textContent = `工单 ${line.order_no || '空闲'}`;

            if (line.robot) {
                const rState = document.getElementById('robotStateVal');
                if (rState) rState.textContent = line.robot.status || '待机';
                const rSub = document.getElementById('robotSubVal');
                if (rSub) rSub.textContent = `${line.robot.position || 'HOME'} · ${line.robot.task || '空闲'}`;
            }
        }).catch(() => {});

        apiGet('/api/logs?category=alarm').then(logs => {
            const listEl = document.getElementById('alarmLogList');
            if (!listEl) return;
            if (!logs || !logs.length) {
                listEl.innerHTML = '<div class="empty">暂无 WARN / ALARM 记录。产线判定不良或急停后会出现在这里。</div>';
                return;
            }
            listEl.innerHTML = logs.map(item => `
                <div class="log-item"><b>${item.created_at || ''}</b> [${item.level || 'WARN'}] ${item.message || ''}</div>
            `).join('');
        }).catch(() => {});
    }

    function initAlarmsPage() {
        refreshData();
        timer = setInterval(refreshData, 2000);

        return () => {
            if (timer) clearInterval(timer);
        };
    }

    document.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-action]");
        if (!btn) return;
        var cfg = ACTIONS[btn.dataset.action];
        if (!cfg) return;

        if (cfg.sound && window.playAudio) window.playAudio(cfg.sound);

        btn.disabled = true;
        apiPost(cfg.url, cfg.payload).then(function () {
            if (window.showToast) showToast(cfg.toast[0], cfg.toast[1] !== 'error');
            refreshData();
        }).catch(function () {
            if (window.showToast) showToast('操作失败', false);
        }).finally(function () {
            btn.disabled = false;
        });
    });

    if (window.registerPage) {
        window.registerPage('alarms', initAlarmsPage);
    }
})();
