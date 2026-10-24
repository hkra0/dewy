import { apiWater } from './api.js';
import { state, nodeCaps, getWaterKey } from './state.js';
import { t } from './i18n.js';

let generation = 0;
let cursor = 0;
let busy = false;
let online = false;
let uploadNode = null;
const uploadErrors = new Map();

function renderFeedback(data, node) {
    const feedback = document.getElementById('maintenance-feedback');
    const job = data.job;
    const result = data.device.update_result || {};
    const errorCode = job?.error_code || (result.status === 'rolled_back' ? 'rolled_back' :
        result.status === 'failed' ? 'device_rejected' : null);
    let message = uploadErrors.get(node) || '';
    if (!message && job?.status === 'failed') {
        message = t('maint_error_' + (errorCode || 'transfer_failed'));
        if (job.error) message += `\n${job.error}`;
    } else if (!message && !job && errorCode) message = t('maint_error_' + errorCode);
    const reason = job?.device_error || (errorCode === 'rolled_back' ? result.code : null);
    if (message && reason) message += `\n${t('maint_reason_' + reason)}`;
    feedback.textContent = message;
    feedback.classList.toggle('hidden', !message);
}

export function refreshMaintenance() {
    const gen = ++generation;
    cursor = 0;
    online = false;
    busy = uploadNode === state.currentDevice;
    const card = document.getElementById('cfg-maintenance-card');
    if (!card) return;
    const visible = state.currentTab === 'settings' && nodeCaps().maintenance && !!getWaterKey();
    card.classList.toggle('hidden', !visible);
    document.getElementById('maintenance-log').textContent = '';
    document.getElementById('maintenance-file').value = '';
    document.getElementById('maintenance-upload').disabled = true;
    document.getElementById('maintenance-status').textContent = t('maint_connecting');
    document.getElementById('maintenance-progress').value = 0;
    document.getElementById('maintenance-feedback').textContent = '';
    document.getElementById('maintenance-feedback').classList.toggle('hidden', true);
    if (visible) poll(gen, state.currentDevice);
}

async function poll(gen, node) {
    try {
        const res = await apiWater(`/api/maintenance/${encodeURIComponent(node)}?after=${cursor}`);
        if (gen !== generation) return;
        if (res.status === 404) return;
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        if (gen !== generation) return;
        online = data.online;
        busy = uploadNode === node || ['sending', 'rebooting', 'verifying'].includes(data.job?.status);
        const job = data.job;
        document.getElementById('maintenance-status').textContent =
            `${t(online ? 'maint_online' : 'maint_offline')} · ${data.device.board || '—'} · ${data.device.build || '—'}` +
            (job ? `\n${t('maint_' + job.status)} (${job.sent}/${job.size})${job.error ? ': ' + job.error : ''}` : '');
        document.getElementById('maintenance-progress').value = job?.size ? Math.round(job.sent / job.size * 100) : 0;
        document.getElementById('maintenance-upload').disabled = busy || !online;
        renderFeedback(data, node);
        const log = document.getElementById('maintenance-log');
        // Server restart resets the cursor; next poll starts from zero.
        if (data.cursor < cursor) { cursor = 0; log.textContent = ''; }
        else cursor = data.cursor;
        if (data.logs.length) {
            const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
            log.textContent = (log.textContent + data.logs.map(line =>
                `[${new Date(line.time * 1000).toLocaleTimeString()}] ${line.text}\n`).join(''))
                .split('\n').slice(-301).join('\n');
            if (atBottom) log.scrollTop = log.scrollHeight;
        }
    } catch (error) {
        if (gen !== generation) return;
        document.getElementById('maintenance-status').textContent = error.message;
        document.getElementById('maintenance-upload').disabled = true;
    }
    if (gen === generation) setTimeout(() => poll(gen, node), 2000);
}

export async function uploadFirmware() {
    if (busy || !online || !getWaterKey()) return;
    const file = document.getElementById('maintenance-file').files[0];
    const label = document.getElementById('maintenance-status');
    if (!file || !file.name.toLowerCase().endsWith('.bin') || file.size < 256 || file.size > 4 * 1024 * 1024) {
        label.textContent = t('maint_select'); return;
    }
    const node = state.currentDevice;
    if (!window.confirm(t('maint_confirm', { node, file: file.name }))) return;
    const gen = generation;
    uploadNode = node;
    uploadErrors.delete(node);
    busy = true;
    document.getElementById('maintenance-upload').disabled = true;
    try {
        const res = await apiWater(`/api/maintenance/${encodeURIComponent(node)}/firmware`, {
            method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file,
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        if (gen === generation) label.textContent = t('maint_sending');
    } catch (error) {
        if (gen === generation) {
            label.textContent = error.message;
            uploadErrors.set(node, t('maint_upload_failed') + '\n' + error.message);
            const feedback = document.getElementById('maintenance-feedback');
            feedback.textContent = uploadErrors.get(node);
            feedback.classList.toggle('hidden', false);
        }
    } finally {
        uploadNode = null;
        // The next status response owns the enabled state and job progress.
    }
}
