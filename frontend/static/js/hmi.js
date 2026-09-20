// 上位机：PLC 控制、寄存器写入与状态轮询
(function () {
    'use strict';

    let timer = null;

    window.sendCommand = function (command) {
        if (window.playAudio) {
            if (command === 'alarm') window.playAudio('alarm');
            else if (command === 'start') window.playAudio('click');
            else if (command === 'reset') window.playAudio('success');
        }
        apiPost('/api/line/command', { command }).then(data => {
            const msg = data.message || data.error || '';
            const cmdMsg = document.getElementById('cmdMsg');
            if (cmdMsg) cmdMsg.textContent = msg;
            if (window.showToast) {
                showToast(msg, command === 'alarm' ? false : true);
            }
        }).catch(() => {});
    };

    window.writeRegister = function () {
        const addrEl = document.getElementById('regAddr');
        const valEl = document.getElementById('regVal');
        if (!addrEl || !valEl) return;
        apiPost('/api/plc/write', {
            address: Number(addrEl.value),
            value: Number(valEl.value)
        }).then(data => {
            const cmdMsg = document.getElementById('cmdMsg');
            if (cmdMsg) cmdMsg.textContent = data.ok ? '写入成功' : (data.error || '写入失败');
        }).catch(() => {});
    };

    function savePlcAddr(reconnect) {
        const ipEl = document.getElementById('plcIp');
        const portEl = document.getElementById('plcPort');
        const msg = document.getElementById('plcAddrMsg');
        const saveBtn = document.getElementById('plcSaveBtn');
        const connectBtn = document.getElementById('plcConnectBtn');
        if (!ipEl || !portEl) return;
        if (saveBtn) saveBtn.disabled = true;
        if (connectBtn) connectBtn.disabled = true;
        apiPost('/api/plc/config', {
            ip: ipEl.value.trim(),
            port: Number(portEl.value),
            reconnect: reconnect ? 1 : 0
        }).then(data => {
            const text = data.message || data.error || '';
            if (msg) {
                msg.textContent = text;
                msg.classList.toggle('is-error', !data.ok);
            }
            const cmd = document.getElementById('cmdMsg');
            if (cmd) cmd.textContent = text;
            if (data.ok) {
                if (data.ip) ipEl.value = data.ip;
                if (data.port) portEl.value = data.port;
                ipEl.dataset.saved = data.ip;
                portEl.dataset.saved = String(data.port);
                markPlcAddrDirty();
            }
        }).catch(() => {
            if (msg) {
                msg.textContent = '保存失败，请检查网络后重试';
                msg.classList.add('is-error');
            }
        }).finally(() => {
            if (saveBtn) saveBtn.disabled = false;
            if (connectBtn) connectBtn.disabled = false;
        });
    }

    function markPlcAddrDirty() {
        const ipEl = document.getElementById('plcIp');
        const portEl = document.getElementById('plcPort');
        const saveBtn = document.getElementById('plcSaveBtn');
        if (!ipEl || !portEl || !saveBtn) return;
        const dirty = ipEl.value.trim() !== (ipEl.dataset.saved || '') || String(portEl.value) !== String(portEl.dataset.saved || '');
        saveBtn.classList.toggle('is-dirty', dirty);
    }

    function bindPlcAddrEditor() {
        const ipEl = document.getElementById('plcIp');
        const portEl = document.getElementById('plcPort');
        const saveBtn = document.getElementById('plcSaveBtn');
        const connectBtn = document.getElementById('plcConnectBtn');
        if (!ipEl || !portEl) return;
        ipEl.dataset.saved = ipEl.value.trim();
        portEl.dataset.saved = String(portEl.value);
        ['input', 'change'].forEach(type => {
            ipEl.addEventListener(type, markPlcAddrDirty);
            portEl.addEventListener(type, markPlcAddrDirty);
        });
        const onEnter = event => {
            if (event.key === 'Enter') {
                event.preventDefault();
                savePlcAddr(false);
            }
        };
        ipEl.addEventListener('keydown', onEnter);
        portEl.addEventListener('keydown', onEnter);
        if (saveBtn) saveBtn.addEventListener('click', () => savePlcAddr(false));
        if (connectBtn) connectBtn.addEventListener('click', () => savePlcAddr(true));
        markPlcAddrDirty();
    }

    function renderLeds(stations) {
        const box = document.getElementById('stationLeds');
        if (!box) return;
        box.innerHTML = (stations || []).map(station => {
            const color = station.status === '运行' ? '#22d3ee' : station.status === '完成' ? '#34d399' : station.status === '故障' ? '#f87171' : '#475569';
            const extra = station.status === '运行' ? 'active' : station.status === '离线' ? 'offline' : '';
            return `<div class="station ${extra}" onclick="openStationDrawer('${station.code}')" style="cursor:pointer;" title="点击查看工位遥测与传感器诊断">
                <div class="led" style="background:${color};box-shadow:0 0 8px ${color};"></div>
                <h3>${station.full_name || station.name}</h3>
                <p>${station.name} · ${station.status}</p>
            </div>`;
        }).join('');
    }

    function refresh() {
        apiGet('/api/plc_status').then(data => {
            const connected = data.connected;
            const dot = document.getElementById('statusDot');
            if (dot) dot.style.background = connected ? '#34d399' : '#f87171';
            const sText = document.getElementById('statusText');
            if (sText) {
                sText.textContent = connected ? '已连接' : '未连接';
                sText.style.color = connected ? '#34d399' : '#f87171';
            }

            const redLight = document.getElementById('andonRed');
            const yellowLight = document.getElementById('andonYellow');
            const greenLight = document.getElementById('andonGreen');
            if (redLight && yellowLight && greenLight) {
                const hasAlarm = Boolean(data.alarm);
                const isRunning = Boolean(data.running);
                if (hasAlarm) {
                    redLight.style.background = '#ef4444';
                    redLight.style.boxShadow = '0 0 10px #ef4444';
                    yellowLight.style.background = '#422006';
                    yellowLight.style.boxShadow = 'none';
                    greenLight.style.background = '#052e16';
                    greenLight.style.boxShadow = 'none';
                } else if (isRunning) {
                    redLight.style.background = '#451a1a';
                    redLight.style.boxShadow = 'none';
                    yellowLight.style.background = '#422006';
                    yellowLight.style.boxShadow = 'none';
                    greenLight.style.background = '#22c55e';
                    greenLight.style.boxShadow = '0 0 10px #22c55e';
                } else {
                    redLight.style.background = '#451a1a';
                    redLight.style.boxShadow = 'none';
                    yellowLight.style.background = '#eab308';
                    yellowLight.style.boxShadow = '0 0 8px #eab308';
                    greenLight.style.background = '#052e16';
                    greenLight.style.boxShadow = 'none';
                }
            }

            const orderEl = document.getElementById('hmiOrder');
            if (orderEl) orderEl.textContent = data.order_no || '空闲';

            const robEl = document.getElementById('robotStatus');
            if (robEl && data.robot) {
                robEl.textContent = `${data.robot.status} · ${data.robot.position} · ${data.robot.task}`;
            }

            const regs = data.registers || {};
            const hr0 = document.getElementById('hr0');
            if (hr0) hr0.textContent = regs['0'] ?? data.last_read_value ?? '--';
            const hr1 = document.getElementById('hr1');
            if (hr1) hr1.textContent = regs['1'] ?? '--';
            const hr2 = document.getElementById('hr2');
            if (hr2) hr2.textContent = regs['2'] ?? '--';
            const rw = document.getElementById('rwCount');
            if (rw) rw.textContent = `${data.total_reads}/${data.total_writes}`;

            const reg0 = document.getElementById('reg0');
            if (reg0) reg0.textContent = regs['0'] ?? '--';
            const reg1 = document.getElementById('reg1');
            if (reg1) reg1.textContent = regs['1'] ?? '--';
            const reg2 = document.getElementById('reg2');
            if (reg2) reg2.textContent = regs['2'] ?? '--';
            const reg4 = document.getElementById('reg4');
            if (reg4) reg4.textContent = regs['4'] ?? '--';
            const reg5 = document.getElementById('reg5');
            if (reg5) reg5.textContent = regs['5'] ?? '--';
            const reg6 = document.getElementById('reg6');
            if (reg6) reg6.textContent = regs['6'] ?? '--';

            const lr = document.getElementById('lastRead');
            if (lr) lr.textContent = data.last_read_time || '--';
            const err = document.getElementById('errMsg');
            if (err) err.textContent = data.error_msg || '--';

            const ipBox = document.getElementById('plcIp');
            const portBox = document.getElementById('plcPort');
            if (ipBox && document.activeElement !== ipBox && data.ip) ipBox.value = data.ip;
            if (portBox && document.activeElement !== portBox && data.port) portBox.value = data.port;

            const addr = document.getElementById('plcAddr');
            if (addr && data.ip) addr.textContent = `${data.ip}:${data.port}`;

            renderLeds(data.stations);
        }).catch(() => {});
    }

    function initHmiPage() {
        bindPlcAddrEditor();
        refresh();
        timer = setInterval(refresh, 1500);

        return () => {
            if (timer) clearInterval(timer);
        };
    }

    if (window.registerPage) {
        window.registerPage('hmi', initHmiPage);
    }
})();
