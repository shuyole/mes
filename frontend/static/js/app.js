// ============================================================================
// MES 全局基础交互与现代化控制引擎 (app.js)
// 包含：顶栏时钟、跨端口 API 代理、Web Audio 音频反馈、Toast 消息中心、
//       工位深度诊断抽屉、仿真倍速调节、大屏全屏模式、全局快捷键系统。
// ============================================================================

// ── 1. 顶栏时钟 ─────────────────────────────────────────────────────────────
function updateClock() {
    const now = new Date();
    const el = document.getElementById('clock');
    if (el) el.textContent = now.toLocaleTimeString('zh-CN', { hour12: false });
}
updateClock();
setInterval(updateClock, 1000);

// ── 2. 会话失效统一处理与 API 前缀代理 ──────────────────────────────────────────
const nativeFetch = window.fetch.bind(window);
window.fetch = function (url, options) {
    if (typeof url === 'string' && url.startsWith('/api/')) {
        url = (window.API_BASE || '') + url;
    }
    options = options || {};
    options.credentials = 'include';
    return nativeFetch(url, options).then(res => {
        if (res.status === 401 && !url.includes('/api/me') && !url.includes('/api/login')) {
            window.location.hash = '#/login';
        }
        return res;
    });
};

// 心跳检测：每 5 秒静默探活
setInterval(() => { fetch('/api/ping').catch(() => {}); }, 5000);

// 统一的 JSON POST 请求
function postJSON(url, data) {
    return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data || {})
    }).then(res => res.json());
}

// ── 3. 轻量级 Web Audio 工业音效发生器 (零外部音频依赖，完全离线运行) ──────────
let audioCtx = null;
let isAudioMuted = localStorage.getItem('mes_audio_muted') === '1';

function getAudioContext() {
    if (!audioCtx) {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (AudioContext) audioCtx = new AudioContext();
    }
    if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume();
    }
    return audioCtx;
}

/**
 * 播放系统合成音效
 * @param {'click'|'success'|'alarm'|'finish'} type 音效类型
 */
function playAudio(type) {
    if (isAudioMuted) return;
    try {
        const ctx = getAudioContext();
        if (!ctx) return;

        if (type === 'click') {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(800, ctx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(400, ctx.currentTime + 0.05);
            gain.gain.setValueAtTime(0.08, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.05);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.05);
        } else if (type === 'success' || type === 'finish') {
            const freqs = [523.25, 659.25, 783.99];
            freqs.forEach((f, i) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'triangle';
                osc.frequency.setValueAtTime(f, ctx.currentTime + i * 0.08);
                gain.gain.setValueAtTime(0.12, ctx.currentTime + i * 0.08);
                gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.08 + 0.25);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(ctx.currentTime + i * 0.08);
                osc.stop(ctx.currentTime + i * 0.08 + 0.25);
            });
        } else if (type === 'alarm') {
            const now = ctx.currentTime;
            [880, 587].forEach((f, i) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'sawtooth';
                osc.frequency.setValueAtTime(f, now + i * 0.15);
                gain.gain.setValueAtTime(0.15, now + i * 0.15);
                gain.gain.exponentialRampToValueAtTime(0.01, now + i * 0.15 + 0.14);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(now + i * 0.15);
                osc.stop(now + i * 0.15 + 0.14);
            });
        }
    } catch (e) {}
}

function toggleAudioMute() {
    isAudioMuted = !isAudioMuted;
    localStorage.setItem('mes_audio_muted', isAudioMuted ? '1' : '0');
    updateAudioBtnUI();
    showToast(isAudioMuted ? '提示音效已静音' : '工业音效反馈已开启', 'info');
    if (!isAudioMuted) playAudio('click');
}

function updateAudioBtnUI() {
    const btn = document.getElementById('audioToggleBtn');
    if (btn) {
        if (isAudioMuted) {
            btn.innerHTML = `<svg class="nav-svg-icon" viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><line x1="23" y1="9" x2="17" y2="15"></line><line x1="17" y1="9" x2="23" y2="15"></line></svg><span>静音</span>`;
            btn.classList.remove('active');
        } else {
            btn.innerHTML = `<svg class="nav-svg-icon" viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path></svg><span>音效</span>`;
            btn.classList.add('active');
        }
    }
}

// ── 4. Toast 浮动消息通知中心 ───────────────────────────────────────────────
function getToastContainer() {
    let box = document.getElementById('toastContainer');
    if (!box) {
        box = document.createElement('div');
        box.id = 'toastContainer';
        box.className = 'toast-container';
        document.body.appendChild(box);
    }
    return box;
}

function showToast(message, type = 'info', duration = 3000) {
    const box = getToastContainer();
    const item = document.createElement('div');
    item.className = `toast-item ${type}`;

    let iconSvg = '';
    if (type === 'success') {
        iconSvg = `<svg class="nav-svg-icon" style="color:var(--green);" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`;
        playAudio('success');
    } else if (type === 'error') {
        iconSvg = `<svg class="nav-svg-icon" style="color:var(--red);" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`;
        playAudio('alarm');
    } else if (type === 'warning') {
        iconSvg = `<svg class="nav-svg-icon" style="color:var(--amber);" viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`;
        playAudio('click');
    } else {
        iconSvg = `<svg class="nav-svg-icon" style="color:var(--cyan);" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`;
        playAudio('click');
    }

    item.innerHTML = `${iconSvg}<div>${message}</div>`;
    box.appendChild(item);

    requestAnimationFrame(() => {
        item.classList.add('show');
    });

    setTimeout(() => {
        item.classList.remove('show');
        setTimeout(() => item.remove(), 320);
    }, duration);

    item.addEventListener('click', () => {
        item.classList.remove('show');
        setTimeout(() => item.remove(), 200);
    });
}

// ── 5. 仿真倍速切换控制器 ───────────────────────────────────────────────────
function setSimSpeed(speed) {
    postJSON('/api/simulation/speed', { speed: speed }).then(res => {
        if (res.ok) {
            document.querySelectorAll('.speed-btn').forEach(btn => {
                btn.classList.toggle('active', parseFloat(btn.dataset.speed) === parseFloat(speed));
            });
            showToast(`仿真运行倍速已调整为 ${speed}x`, 'info');
        } else {
            showToast(res.error || '调整倍速失败', 'error');
        }
    }).catch(err => {
        showToast('请求超时，请检查服务状态', 'error');
    });
}

// ── 6. 全屏车间大屏模式 (SCADA Big Screen) ──────────────────────────────────
function toggleFullscreen() {
    const isFull = document.body.classList.toggle('scada-fullscreen');
    playAudio('click');
    const btn = document.getElementById('fullscreenToggleBtn');
    if (btn) {
        if (isFull) {
            btn.innerHTML = `<svg class="nav-svg-icon" viewBox="0 0 24 24"><polyline points="4 14 10 14 10 20"></polyline><polyline points="20 10 14 10 14 4"></polyline><line x1="14" y1="10" x2="21" y2="3"></line><line x1="3" y1="21" x2="10" y2="14"></line></svg><span>退出全屏</span>`;
            showToast('已进入车间大屏展示模式 (按 F 或 Esc 退出)', 'info');
            if (document.documentElement.requestFullscreen && !document.fullscreenElement) {
                document.documentElement.requestFullscreen().catch(() => {});
            }
        } else {
            btn.innerHTML = `<svg class="nav-svg-icon" viewBox="0 0 24 24"><polyline points="15 3 21 3 21 9"></polyline><polyline points="9 21 3 21 3 15"></polyline><line x1="21" y1="3" x2="14" y2="10"></line><line x1="3" y1="21" x2="10" y2="14"></line></svg><span>大屏模式</span>`;
            showToast('已退出大屏展示模式', 'info');
            if (document.exitFullscreen && document.fullscreenElement) {
                document.exitFullscreen().catch(() => {});
            }
        }
    }
}

// ── 7. 工位深度诊断抽屉 (Station Diagnostic Drawer) ──────────────────────────
function openStationDrawer(stationCode) {
    stationCode = (stationCode || '').toUpperCase();
    if (!stationCode) return;
    playAudio('click');

    const drawer = document.getElementById('stationDrawerMask');
    if (!drawer) return;

    document.getElementById('drawerStationTitle').textContent = `工位诊断 / ${stationCode}`;
    document.getElementById('drawerStationBody').innerHTML = `<div style="text-align:center; padding:40px 0; color:var(--muted);">正在读取工位传感器与参数数据...</div>`;
    drawer.classList.add('open');

    fetch(`/api/line/station/${stationCode}/diagnose`).then(res => res.json()).then(data => {
        if (!data.ok) {
            document.getElementById('drawerStationBody').innerHTML = `<div class="error-msg">${data.error || '获取工位详情失败'}</div>`;
            return;
        }

        const sensorsHtml = (data.sensors || []).map(s => `
            <div class="sensor-card">
                <div>
                    <b>${s.name}</b>
                    <span class="sensor-pin">${s.pin}</span>
                </div>
                <span class="sensor-led ${s.status === 'ON' ? 'on' : ''}">${s.status === 'ON' ? '联通' : '断开'}</span>
            </div>
        `).join('');

        const paramsHtml = (data.params || []).map(p => `
            <div class="param-card">
                <div class="pk">${p.key}</div>
                <div class="pv">${p.value}</div>
                <div class="ps">标准: ${p.standard}</div>
            </div>
        `).join('');

        document.getElementById('drawerStationTitle').innerHTML = `
            <span>${data.full_name || data.name}</span>
            <span class="station-code" style="color:var(--cyan); margin-left:8px;">${data.code}</span>
        `;

        document.getElementById('drawerStationBody').innerHTML = `
            <div>
                <div class="drawer-section-title">
                    <svg class="nav-svg-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                    工位基本概况
                </div>
                <div style="background:rgba(14,24,46,0.6); padding:14px; border-radius:8px; border:1px solid rgba(255,255,255,0.08); font-size:13px; line-height:1.6;">
                    <div><strong>工艺职能：</strong>${data.role} · 理论单件节拍 <b>${data.cycle_sec}s</b></div>
                    <div style="margin-top:4px;"><strong>PLC 保持寄存器：</strong>HR${data.plc_address} (工位指令与状态字)</div>
                    <div style="margin-top:4px;"><strong>当前状态：</strong><span class="badge ${data.status==='运行'?'badge-run':data.status==='故障'?'badge-alarm':'badge-done'}">${data.status}</span> · 累计过站 <b>${data.processed_qty}</b> 件</div>
                    <div style="margin-top:4px; color:var(--muted);"><strong>工艺动作要点：</strong>${data.desc || '无线充精密装配工艺'}</div>
                </div>
            </div>

            <div>
                <div class="drawer-section-title">
                    <svg class="nav-svg-icon" viewBox="0 0 24 24"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
                    实时关键传感器信号 (I/O)
                </div>
                <div class="sensor-matrix">
                    ${sensorsHtml || '<p style="color:var(--muted);">暂无配置传感器</p>'}
                </div>
            </div>

            <div>
                <div class="drawer-section-title">
                    <svg class="nav-svg-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
                    工位关键工艺参数
                </div>
                <div class="param-grid">
                    ${paramsHtml || '<p style="color:var(--muted);">暂无配置参数</p>'}
                </div>
            </div>

            <div>
                <div class="drawer-section-title">
                    <svg class="nav-svg-icon" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
                    品质判定标准
                </div>
                <div style="background:rgba(14,24,46,0.6); padding:12px 14px; border-radius:8px; border:1px solid rgba(255,255,255,0.08); font-size:13px; color:#cbd5e1;">
                    ${data.qc_criteria || '外壳平整无划伤，电气性能指标合格'}
                </div>
            </div>

            <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:8px;">
                <button type="button" class="btn btn-solid" style="flex:1;" onclick="testStationAction('${data.code}')">单步动作自检</button>
                <button type="button" class="btn btn-red" style="flex:1;" onclick="injectStationFault('${data.code}')">模拟此工位故障</button>
            </div>
        `;
    }).catch(() => {
        document.getElementById('drawerStationBody').innerHTML = `<div class="error-msg">读取工位数据失败，请确认后端服务运行中。</div>`;
    });
}

function closeStationDrawer() {
    const drawer = document.getElementById('stationDrawerMask');
    if (drawer) drawer.classList.remove('open');
}

function testStationAction(code) {
    postJSON(`/api/line/station/${code}/test`).then(res => {
        if (res.ok) {
            showToast(res.message || '自检成功', 'success');
        } else {
            showToast(res.error || '自检失败', 'error');
        }
    });
}

function injectStationFault(code) {
    postJSON('/api/line/inject_fault', { station_code: code }).then(res => {
        if (res.ok) {
            showToast(res.message || '故障已注入', 'warning');
            closeStationDrawer();
            if (window.refreshLine) window.refreshLine();
            if (window.fetchStats) window.fetchStats();
        } else {
            showToast(res.error || '故障注入失败', 'error');
        }
    });
}

// ── 8. 一键快速生成排产演示工单 ─────────────────────────────────────────────
function seedDemoOrders() {
    playAudio('click');
    showConfirm('确定要生成 3 笔标准教学示范工单（含车载款、磁吸款、多设备旗舰款）吗？', () => {
        postJSON('/api/demo/seed_orders').then(res => {
            if (res.ok) {
                showToast(res.message || '示范工单生成成功！', 'success');
                setTimeout(() => location.reload(), 800);
            } else {
                showToast(res.error || '生成失败', 'error');
            }
        });
    });
}

// ── 9. 全局确认弹窗 ─────────────────────────────────────────────────────────
const confirmMask = document.getElementById('confirmMask');
let confirmAction = null;

function closeConfirm() {
    if (confirmMask) confirmMask.classList.remove('open');
    confirmAction = null;
}

function showConfirm(message, action) {
    if (!confirmMask) {
        if (confirm(message)) action();
        return;
    }
    document.getElementById('confirmText').textContent = message;
    confirmAction = action;
    confirmMask.classList.add('open');
    const okBtn = document.getElementById('confirmOk');
    if (okBtn) okBtn.focus();
}

if (confirmMask) {
    const okBtn = document.getElementById('confirmOk');
    if (okBtn) {
        okBtn.addEventListener('click', () => {
            const action = confirmAction;
            closeConfirm();
            if (action) action();
        });
    }
    const cancelBtn = document.getElementById('confirmCancel');
    if (cancelBtn) cancelBtn.addEventListener('click', closeConfirm);
    confirmMask.addEventListener('click', event => {
        if (event.target === confirmMask) closeConfirm();
    });
}

// ── 10. 键盘快捷键与全局事件监听 ─────────────────────────────────────────────
document.addEventListener('keydown', event => {
    const activeTag = document.activeElement ? document.activeElement.tagName : '';
    const isInput = activeTag === 'INPUT' || activeTag === 'TEXTAREA' || activeTag === 'SELECT';

    if (event.key === 'Escape') {
        closeConfirm();
        closeStationDrawer();
        if (document.body.classList.contains('scada-fullscreen')) {
            toggleFullscreen();
        }
        return;
    }

    if (confirmMask && confirmMask.classList.contains('open')) {
        if (event.key === 'Enter') {
            event.preventDefault();
            const okBtn = document.getElementById('confirmOk');
            if (okBtn) okBtn.click();
        }
        return;
    }

    if (!isInput) {
        if (event.key === 'f' || event.key === 'F') {
            event.preventDefault();
            toggleFullscreen();
        } else if (event.key === 'm' || event.key === 'M') {
            event.preventDefault();
            toggleAudioMute();
        }
    }
});

// 全局 data-confirm 点击代理
document.addEventListener('click', event => {
    const trigger = event.target.closest('[data-confirm]');
    if (!trigger) return;
    event.preventDefault();
    showConfirm(trigger.dataset.confirm, () => {
        if (trigger.tagName === 'A') {
            window.location.href = trigger.getAttribute('href');
        } else if (trigger.form) {
            trigger.form.requestSubmit(trigger);
        }
    });
});

// 全局工位卡片点击代理：点击监控看板或在制追踪上的任何工位打开诊断抽屉
document.addEventListener('click', event => {
    const stationCard = event.target.closest('.monitor-station, .station-node');
    if (stationCard && !event.target.closest('button.btn')) {
        const codeEl = stationCard.querySelector('.station-code, .node-step');
        let code = codeEl ? codeEl.textContent.trim() : '';
        if (!code && stationCard.dataset.index !== undefined) {
            const idx = parseInt(stationCard.dataset.index) + 1;
            code = `ST0${idx}`;
        }
        if (code) {
            openStationDrawer(code);
        }
    }
});

// 页面加载完成后初始化状态与 UI
document.addEventListener('DOMContentLoaded', () => {
    updateAudioBtnUI();

    fetch('/api/simulation/speed').then(r => r.json()).then(data => {
        if (data.ok && data.speed) {
            document.querySelectorAll('.speed-btn').forEach(btn => {
                btn.classList.toggle('active', parseFloat(btn.dataset.speed) === parseFloat(data.speed));
            });
        }
    }).catch(() => {});
});

// 工位状态通用类
function stationClass(status) {
    if (status === '运行') return 'active';
    if (status === '完成') return 'done';
    if (status === '故障') return 'alarm';
    if (status === '离线') return 'offline';
    return '';
}

function stationStep(station, index) {
    return station.step || String(index + 1).padStart(2, '0');
}

function renderProcessRail(box, stations) {
    if (!box) return;
    box.innerHTML = (stations || []).map((station, index) => {
        const cls = stationClass(station.status);
        const tone = station.tone || 'cyan';
        return `<div class="process-step ${cls}" data-tone="${tone}" onclick="openStationDrawer('${station.code}')">
            <div class="process-thumb"><b>${stationStep(station, index)}</b></div>
            <div class="process-label">${station.name}</div>
        </div>`;
    }).join('');
}

function renderFactoryLine(box, stations) {
    if (!box) return;
    box.classList.add('factory-line');
    box.innerHTML = (stations || []).map((station, index) => {
        const cls = stationClass(station.status);
        const tone = station.tone || 'cyan';
        const title = station.full_name || station.name;
        return `<article class="station-node ${cls}" data-tone="${tone}" onclick="openStationDrawer('${station.code}')" style="cursor:pointer;" title="点击查看工位深度诊断与参数">
            <div class="node-tag">${title}</div>
            <div class="machine v${index + 1}">
                <span class="arm"></span>
                <span class="head"></span>
                <span class="hmi"></span>
                <span class="body"></span>
                <span class="led"></span>
            </div>
            <div class="node-step">${stationStep(station, index)}</div>
            <div class="node-name">${station.name}</div>
            <p class="node-meta">${station.status} · ${station.processed_qty || 0}</p>
        </article>`;
    }).join('<span class="factory-link"></span>');
}
