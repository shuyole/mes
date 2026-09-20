// 工单进度交互：拖动进度条、加减完成数、点选状态，立即回写并更新本行（含操作按钮）
const STATUS_BADGE = {
    待生产: 'badge-wait',
    生产中: 'badge-run',
    暂停: 'badge-pause',
    返工: 'badge-rework',
    已完成: 'badge-done'
};

function showToast(text, ok) {
    let el = document.getElementById('hudToast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'hudToast';
        el.className = 'hud-toast';
        document.body.appendChild(el);
    }
    el.textContent = text;
    el.classList.toggle('is-error', !ok);
    el.hidden = false;
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => { el.hidden = true; }, 2200);
}

function inferStatus(done, qty, current) {
    if (qty && done >= qty) return '已完成';
    if (current === '返工') return '返工';
    if (current === '已完成' && done < qty) return '返工';
    if (done <= 0) return current === '暂停' ? '暂停' : '待生产';
    if (current === '暂停') return '暂停';
    return '生产中';
}

function thumbLeft(pct) {
    if (pct <= 0) return '7px';
    if (pct >= 100) return 'calc(100% - 7px)';
    return pct + '%';
}

function paintActions(row, status) {
    if (!row) return;
    const dispatch = row.querySelector('.js-dispatch');
    const finish = row.querySelector('.js-finish');
    const rework = row.querySelector('.js-rework');
    if (dispatch) dispatch.hidden = status !== '待生产';
    if (finish) {
        finish.hidden = status !== '生产中' && status !== '暂停' && status !== '返工';
        finish.textContent = status === '返工' ? '完成返工' : '强制完工';
    }
    if (rework) rework.hidden = status !== '已完成';
}

function paintBar(ctl, pct) {
    const fill = ctl.querySelector('.progress-fill');
    const thumb = ctl.querySelector('.progress-thumb');
    const pctEl = ctl.querySelector('.progress-pct');
    if (fill) fill.style.width = pct + '%';
    if (thumb) thumb.style.left = thumbLeft(pct);
    if (pctEl) pctEl.textContent = Math.round(pct) + '%';
}

function paintProgress(ctl, data, quiet) {
    const qty = Number(data.quantity);
    const done = Number(data.completed_qty);
    const pct = data.progress == null ? (qty ? Math.round(done * 100 / qty) : 0) : Number(data.progress);
    const status = data.status;
    ctl.dataset.qty = String(qty);
    ctl.dataset.done = String(done);
    ctl.dataset.progress = String(pct);
    ctl.dataset.status = status;
    const fill = ctl.querySelector('.progress-fill');
    const thumb = ctl.querySelector('.progress-thumb');
    const pctEl = ctl.querySelector('.progress-pct');
    const input = ctl.querySelector('.progress-input');
    const track = ctl.querySelector('.progress-track');
    const minus = ctl.querySelector('.progress-step[data-delta="-1"]');
    const plus = ctl.querySelector('.progress-step[data-delta="1"]');
    if (fill) fill.style.width = pct + '%';
    if (thumb) thumb.style.left = thumbLeft(pct);
    if (pctEl) pctEl.textContent = pct + '%';
    if (input && document.activeElement !== input) {
        input.max = String(qty);
        input.value = String(done);
    }
    if (track) {
        track.setAttribute('aria-valuemax', '100');
        track.setAttribute('aria-valuenow', String(pct));
    }
    if (minus) minus.disabled = done <= 0;
    if (plus) plus.disabled = done >= qty;
    const lit = (status === '已完成' || pct >= 100) ? 7 : Math.ceil(pct / 100 * 7);
    ctl.querySelectorAll('.progress-stations > *').forEach((dot, index) => {
        dot.classList.toggle('on', index < lit);
        dot.classList.toggle('now', index === lit - 1 && status === '生产中' && lit < 7);
    });
    const row = ctl.closest('tr');
    if (row) {
        row.dataset.status = status;
        const qtyCell = row.querySelector('[data-qty-cell]');
        if (qtyCell) qtyCell.textContent = done + '/' + qty;
        const doneCell = row.querySelector('[data-done-cell]');
        if (doneCell) doneCell.textContent = String(done);
        const stationCell = row.querySelector('[data-station-cell]');
        if (stationCell && data.current_station !== undefined) stationCell.textContent = data.current_station || '-';
        paintActions(row, status);
    }
    const statusCtl = row ? row.querySelector('.status-ctl') : null;
    if (statusCtl) paintStatus(statusCtl, status);
    if (!quiet) {
        ctl.classList.add('is-pulse');
        setTimeout(() => ctl.classList.remove('is-pulse'), 380);
    }
}

function paintStatus(ctl, status) {
    ctl.dataset.status = status;
    const btn = ctl.querySelector('.status-btn');
    if (!btn) return;
    btn.textContent = status;
    btn.className = 'badge status-btn ' + (STATUS_BADGE[status] || 'badge-idle');
    ctl.querySelectorAll('.status-menu button').forEach(item => {
        item.classList.toggle('active', item.dataset.status === status);
    });
}

function saveProgress(ctl, payload) {
    ctl._seq = (ctl._seq || 0) + 1;
    const seq = ctl._seq;
    return postJSON('/api/orders/' + ctl.dataset.id + '/progress', payload).then(data => {
        if (seq !== ctl._seq) return;
        if (!data || !data.ok) {
            showToast((data && data.error) || '进度更新失败', false);
            return;
        }
        paintProgress(ctl, data, true);
        showToast(data.message || '进度已更新', true);
        if (typeof applyFilter === 'function') applyFilter();
    }).catch(() => {
        if (seq !== ctl._seq) return;
        showToast('网络异常，进度未保存', false);
    });
}

function qtyFromPointer(track, event, rect) {
    const ctl = track.closest('.progress-ctl');
    const qty = Number(ctl.dataset.qty) || 0;
    const box = rect || track.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - box.left) / Math.max(box.width, 1)));
    const pct = ratio * 100;
    return { ctl, done: Math.round(ratio * qty), qty, pct };
}

function previewQty(ctl, done, pct) {
    const qty = Number(ctl.dataset.qty) || 0;
    const clamped = Math.min(Math.max(done, 0), qty);
    const shown = pct == null ? (qty ? clamped * 100 / qty : 0) : Math.min(100, Math.max(0, pct));
    paintBar(ctl, shown);
    // 拖动过程中也同步刷新数量输入框和表格单元格，让数字跟着滑块实时走
    const input = ctl.querySelector('.progress-input');
    if (input && document.activeElement !== input) {
        input.value = String(clamped);
    }
    const row = ctl.closest('tr');
    if (row) {
        const qtyCell = row.querySelector('[data-qty-cell]');
        if (qtyCell) qtyCell.textContent = clamped + '/' + qty;
        const doneCell = row.querySelector('[data-done-cell]');
        if (doneCell) doneCell.textContent = String(clamped);
    }
}

function closeStatusMenus(except) {
    document.querySelectorAll('.status-ctl').forEach(ctl => {
        if (ctl === except) return;
        const menu = ctl.querySelector('.status-menu');
        const btn = ctl.querySelector('.status-btn');
        if (menu) menu.hidden = true;
        if (btn) btn.setAttribute('aria-expanded', 'false');
        ctl.classList.remove('open');
    });
}

function ctlFromRow(row) {
    return row ? row.querySelector('.progress-ctl') : null;
}

document.addEventListener('click', event => {
    const finish = event.target.closest('.js-finish');
    if (finish) {
        const row = finish.closest('tr');
        const ctl = ctlFromRow(row);
        if (ctl) saveProgress(ctl, { status: '已完成' });
        return;
    }
    const reopen = event.target.closest('.js-rework');
    if (reopen) {
        const row = reopen.closest('tr');
        const ctl = ctlFromRow(row);
        if (ctl) saveProgress(ctl, { status: '返工', rework_qty: 1 });
        return;
    }
    const step = event.target.closest('.progress-step');
    if (step) {
        if (step.disabled) return;
        const ctl = step.closest('.progress-ctl');
        saveProgress(ctl, { delta: Number(step.dataset.delta) });
        return;
    }
    const pick = event.target.closest('.status-menu button');
    if (pick) {
        const statusCtl = pick.closest('.status-ctl');
        const ctl = document.querySelector('.progress-ctl[data-id="' + statusCtl.dataset.id + '"]') || statusCtl;
        closeStatusMenus();
        saveProgress(ctl, { status: pick.dataset.status });
        return;
    }
    const statusBtn = event.target.closest('.status-btn');
    if (statusBtn) {
        const wrap = statusBtn.closest('.status-ctl');
        const open = wrap.classList.contains('open');
        closeStatusMenus();
        if (!open) {
            wrap.classList.add('open');
            wrap.querySelector('.status-menu').hidden = false;
            statusBtn.setAttribute('aria-expanded', 'true');
        }
        return;
    }
    closeStatusMenus();
});

document.addEventListener('change', event => {
    const input = event.target.closest('.progress-input');
    if (!input) return;
    const ctl = input.closest('.progress-ctl');
    saveProgress(ctl, { completed_qty: Number(input.value) });
});

let dragState = null;
let dragFrame = 0;

document.addEventListener('pointerdown', event => {
    const track = event.target.closest('.progress-track');
    if (!track) return;
    event.preventDefault();
    const rect = track.getBoundingClientRect();
    const info = qtyFromPointer(track, event, rect);
    const row = info.ctl.closest('tr');
    dragState = { ...info, track, rect, row };
    track.classList.add('is-dragging');
    if (row) row.classList.add('is-dragging-row');
    try { track.setPointerCapture(event.pointerId); } catch (err) {}
    previewQty(info.ctl, info.done, info.pct);
});

document.addEventListener('pointermove', event => {
    if (!dragState) return;
    event.preventDefault();
    const pending = qtyFromPointer(dragState.track, event, dragState.rect);
    dragState.done = pending.done;
    dragState.pct = pending.pct;
    if (dragFrame) return;
    dragFrame = requestAnimationFrame(() => {
        dragFrame = 0;
        if (!dragState) return;
        previewQty(dragState.ctl, dragState.done, dragState.pct);
    });
});

document.addEventListener('pointerup', endProgressDrag);
document.addEventListener('pointercancel', endProgressDrag);

function endProgressDrag() {
    if (!dragState) return;
    const info = dragState;
    dragState = null;
    if (dragFrame) {
        cancelAnimationFrame(dragFrame);
        dragFrame = 0;
    }
    info.track.classList.remove('is-dragging');
    if (info.row) info.row.classList.remove('is-dragging-row');
    saveProgress(info.ctl, { progress: Math.round(info.pct) });
}

document.addEventListener('keydown', event => {
    const track = event.target.closest('.progress-track');
    if (!track) return;
    const ctl = track.closest('.progress-ctl');
    let delta = 0;
    if (event.key === 'ArrowRight' || event.key === 'ArrowUp') delta = 1;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') delta = -1;
    if (event.key === 'Home') {
        saveProgress(ctl, { completed_qty: 0 });
        event.preventDefault();
        return;
    }
    if (event.key === 'End') {
        saveProgress(ctl, { completed_qty: Number(ctl.dataset.qty) });
        event.preventDefault();
        return;
    }
    if (!delta) return;
    event.preventDefault();
    saveProgress(ctl, { delta: delta });
});

document.querySelectorAll('.progress-ctl').forEach(ctl => {
    paintProgress(ctl, {
        quantity: Number(ctl.dataset.qty),
        completed_qty: Number(ctl.dataset.done),
        progress: Number(ctl.dataset.progress),
        status: ctl.dataset.status
    }, true);
});
