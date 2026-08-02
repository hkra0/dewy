// 环境视图：动态指标卡片、实时数据、浇水与切灯。
import { t } from './i18n.js';
import { showToast } from './ui.js';
import { state, getViewerKey, getWaterKey } from './state.js';
import { apiGet, apiWater, apiWaterPost } from './api.js';
import { switchHistType } from './navigation.js';
import { fetchAllData } from './refresh.js';

let lightToggleInProgress = false;
let optimisticLightStatus = null;

export function renderDynamicCards(nodeData, globalData) {
    const container = document.getElementById('dynamic-cards');

    if (!nodeData) {
        container.innerHTML = `<div class="card full-width">${t('no_data_node')}</div>`;
        return;
    }

    const formatVal = (v, unit) => (v !== undefined && v !== null) ? `${v} ${unit}` : '--';
    let html = '';

    if (nodeData.temperature !== undefined) {
        html += `<div class="card"><div class="card-title">` + t('temp') + `</div><div class="card-value" style="color: var(--metric-temp);">${formatVal(nodeData.temperature, '℃')}</div></div>`;
    }
    if (nodeData.humidity !== undefined) {
        html += `<div class="card"><div class="card-title">` + t('humidity') + `</div><div class="card-value" style="color: var(--metric-hum);">${formatVal(nodeData.humidity, '%')}</div></div>`;
    }
    if (nodeData.soil_moisture !== undefined) {
        html += `<div class="card"><div class="card-title">` + t('soil_moisture') + `</div><div class="card-value" style="color: var(--accent);">${formatVal(nodeData.soil_moisture, '%')}</div></div>`;
    }
    if (nodeData.pressure !== undefined) {
        html += `<div class="card"><div class="card-title">` + t('pressure') + `</div><div class="card-value" style="color: var(--metric-pres);">${formatVal(nodeData.pressure, 'hPa')}</div></div>`;
    }

    // Light Status (global for now, or you can attach to specific node)
    // Use optimistic status if available to prevent polling from reverting manual toggles
    if (state.currentDevice === 'main') {
        const effectiveStatus = optimisticLightStatus || globalData.light_status;
        if (effectiveStatus && effectiveStatus !== '--') {
            const color = effectiveStatus === 'ON' ? 'var(--metric-light-on)' : 'var(--text-muted)';
            html += `<div class="card" id="light-card" style="cursor: pointer;" onclick="toggleLight()"><div class="card-title">` + t('light_title') + `</div><div class="card-value" id="light-status" style="color: ${color};">${effectiveStatus}</div></div>`;
        } else if (globalData.light_status) {
            const color = globalData.light_status === 'ON' ? 'var(--metric-light-on)' : 'var(--text-muted)';
            html += `<div class="card" id="light-card" style="cursor: pointer;" onclick="toggleLight()"><div class="card-title">${t('light_title')}</div><div class="card-value" id="light-status" style="color: ${color};">${globalData.light_status}</div></div>`;
        }
    }

    container.innerHTML = html;

    // Power System Health is rendered in System Tab.

    // Hardware Actions (Camera / Water)
    const hasKey = !!getViewerKey();
    const hasWaterKey = !!getWaterKey();
    const nodeInfo = state.availableNodes[state.currentDevice] || {};
    const hasCamera = nodeInfo.sensors && ('camera' in nodeInfo.sensors);
    const hasPump = nodeInfo.actuators && ('pump' in nodeInfo.actuators);

    if (hasKey && hasCamera) {
        document.getElementById('camera-block').classList.remove('hidden');
        const pBtn = document.getElementById('hist-photos');
        if (pBtn) pBtn.classList.remove('hidden');
    } else {
        document.getElementById('camera-block').classList.add('hidden');
        const pBtn = document.getElementById('hist-photos');
        if (pBtn) pBtn.classList.add('hidden');
        if (state.currentHistType === 'photos') switchHistType('24h');
    }

    if (hasWaterKey && hasPump) {
        document.getElementById('water-block').classList.remove('hidden');
    } else {
        document.getElementById('water-block').classList.add('hidden');
    }
}

export async function fetchSensorData() {
    // 无密钥 = 访客路径，设计上什么都不发生：不请求、不提示
    if (!getViewerKey()) return;

    try {
        const res = await apiGet('/api/monitor');

        // 404 是"密钥不对/端点不存在"的统一答复（worker.js 有意不区分），
        // 属于访客路径，必须保持静默；其余失败才是真的连不上。
        if (res.status === 404) return;
        if (!res.ok) { showConnectionLost(); return; }

        const data = await res.json();
        if (data.error) { showConnectionLost(); return; }

        const nodeData = data.nodes ? data.nodes[state.currentDevice] : {};
        renderDynamicCards(nodeData, data);

        // System stats
        if (data.system_health) {
            document.getElementById('sys-temp').innerText = data.system_health.cpu_temperature + ' ℃';
            document.getElementById('sys-ram').innerText = data.system_health.ram_usage_percent + ' %';
            document.getElementById('sys-disk').innerText = data.system_health.disk_usage_percent + ' %';
        }
        if (nodeData && nodeData.voltage != null && nodeData.current != null) {
            const cVal = nodeData.current;
            document.getElementById('power-status').innerText = nodeData.voltage + ' V / ' + (cVal > 0 ? '+' + cVal : cVal) + ' mA';
        } else {
            document.getElementById('power-status').innerText = '-- V / -- mA';
        }
        const time = new Date(data.timestamp * 1000);
        const statusEl = document.getElementById('update-time');
        statusEl.innerText = t('last_synced', { time: time.toLocaleTimeString().toLowerCase() });
        statusEl.style.color = '';
    } catch (e) {
        // fetch 抛异常 = 网络层就没通，与 404 无关，可以放心提示
        console.error(e);
        showConnectionLost();
    }
}

/** 状态栏转为断连提示。数据卡片保留上次数值——
 *  没有这个提示的话，用户无法分辨"数据没变"和"已经断了"。 */
function showConnectionLost() {
    const statusEl = document.getElementById('update-time');
    if (!statusEl) return;
    statusEl.innerText = t('conn_lost');
    statusEl.style.color = '#ef4444';
}

export async function triggerWatering() {
    if (!getWaterKey()) return;
    const btn = document.getElementById('water-btn');
    btn.disabled = true; btn.innerText = t('watering_ing');
    const duration = parseFloat(document.getElementById('water-duration').value) || 0.5;
    try {
        const res = await apiWaterPost('/api/water', { duration, node_id: state.currentDevice });
        if (res.ok) { showToast(t('watering_cmd'), 'success'); setTimeout(() => { btn.innerText = t('water_btn'); btn.disabled = false; fetchAllData(true); }, 2000); }
        else throw new Error('fail');
    } catch (e) { showToast(t('water_fail'), 'error'); setTimeout(() => { btn.innerText = t('water_btn'); btn.disabled = false; }, 2000); }
}

export async function toggleLight() {
    if (state.isCameraSyncing || state.isHDSyncing) return;
    if (lightToggleInProgress) return;
    if (!getWaterKey()) return;
    const statusEl = document.getElementById('light-status');
    if (!statusEl) return;

    lightToggleInProgress = true;

    const currentStatus = optimisticLightStatus || statusEl.innerText.trim();
    const isCurrentlyOn = currentStatus === 'ON';
    const newStatus = isCurrentlyOn ? 'OFF' : 'ON';

    // Pure optimistic update — no server refresh needed
    optimisticLightStatus = newStatus;
    statusEl.innerText = newStatus;
    statusEl.style.color = newStatus === 'ON' ? 'var(--metric-light-on)' : 'var(--text-muted)';
    showToast(newStatus === 'ON' ? t('light_on') : t('light_off'), 'success');

    try {
        const res = await apiWater('/api/light', { method: 'POST' });
        if (!res.ok) {
            if (res.status === 409) throw new Error('camera');
            throw new Error('fail');
        }
    } catch (e) {
        // Revert optimistic state on failure
        optimisticLightStatus = isCurrentlyOn ? 'ON' : null;
        statusEl.innerText = isCurrentlyOn ? 'ON' : 'OFF';
        statusEl.style.color = isCurrentlyOn ? 'var(--metric-light-on)' : 'var(--text-muted)';
        showToast(e.message === 'camera' ? t('cam_capturing') : t('light_fail'), 'error');
    }

    // 1s debounce
    setTimeout(() => { lightToggleInProgress = false; }, 1000);
}
