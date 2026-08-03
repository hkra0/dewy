// 环境视图：动态指标卡片、实时数据、浇水与切灯。
import { t } from './i18n.js';
import { showToast, escapeHtml } from './ui.js';
import { state, getViewerKey, getWaterKey, nodeCaps } from './state.js';
import { apiGet, apiWater, apiWaterPost } from './api.js';
import { extraMetricEntries, metricLabel, metricUnit, metricColor } from './metrics.js';
import { switchHistType } from './navigation.js';
import { fetchAllData } from './refresh.js';

let lightToggleInProgress = false;

// 手动切灯后的乐观状态。存在的理由只有一个：切灯指令走 MQTT，
// 服务端的 light_status 要等下一次轮询才会反映出来，中间这段空窗期
// 不能让卡片弹回旧值。
//
// 因此它**必须会过期**。一经设置就永不清空的话，服务端的真实状态会被
// 永久遮蔽——定时灯控到点关灯、或 manual_override 到期回归定时控制之后，
// 界面仍然显示用户当初点的那个值。
// 两个交还时机：服务端已经追上（提前交还），或超过 TTL（兜底交还）。
let optimisticLightStatus = null;
let optimisticLightUntil = 0;

// 略长于一个轮询周期（refresh.js 是 30s），确保正常情况下
// 至少有一次轮询机会把服务端值带回来。
const OPTIMISTIC_LIGHT_TTL_MS = 35000;

/** 决定这一帧该显示哪个状态，并在条件满足时把控制权交还给服务端。 */
function effectiveLightStatus(serverStatus) {
    if (optimisticLightStatus) {
        const expired = Date.now() > optimisticLightUntil;
        if (expired || serverStatus === optimisticLightStatus) {
            optimisticLightStatus = null;
            optimisticLightUntil = 0;
        } else {
            return optimisticLightStatus;
        }
    }
    return serverStatus;
}

function clearOptimisticLight() {
    optimisticLightStatus = null;
    optimisticLightUntil = 0;
}

// 手动浇水时长的允许范围。必须与 api/routers.py 的 trigger_manual_watering
// 保持一致——服务端仍然会钳制，这里只是提前告知，不是唯一防线。
const WATER_MIN_S = 0.1;
const WATER_MAX_S = 1.0;
const WATER_DEFAULT_S = 0.5;

export function renderDynamicCards(nodeData, globalData) {
    const container = document.getElementById('dynamic-cards');

    if (!nodeData) {
        container.innerHTML = `<div class="card full-width">${t('no_data_node')}</div>`;
        return;
    }

    const caps = nodeCaps();
    const formatVal = (v, unit) => (v !== undefined && v !== null) ? `${v}${unit ? ' ' + unit : ''}` : '--';
    let html = '';

    if (nodeData.temperature !== undefined) {
        html += `<div class="card"><div class="card-title">` + t('temp') + `</div><div class="card-value" style="color: var(--metric-temp);">${formatVal(nodeData.temperature, '℃')}</div></div>`;
    }
    if (nodeData.humidity !== undefined) {
        html += `<div class="card"><div class="card-title">` + t('humidity') + `</div><div class="card-value" style="color: var(--metric-hum);">${formatVal(nodeData.humidity, '%')}</div></div>`;
    }
    if (nodeData.soil_moisture !== undefined) {
        // --metric-soil，不是 --accent：历史曲线的土壤线用的就是 --metric-soil，
        // 同一个指标在两个视图里必须是同一个颜色。
        html += `<div class="card"><div class="card-title">` + t('soil_moisture') + `</div><div class="card-value" style="color: var(--metric-soil);">${formatVal(nodeData.soil_moisture, '%')}</div></div>`;
    }
    if (nodeData.pressure !== undefined) {
        html += `<div class="card"><div class="card-title">` + t('pressure') + `</div><div class="card-value" style="color: var(--metric-pres);">${formatVal(nodeData.pressure, 'hPa')}</div></div>`;
    }

    // 固定四项之外，驱动返回什么就显示什么（照度、CO₂、EC…）。
    // 这些字段事先不可知，所以标签查不到时用字段名本身，而不是不显示——
    // 用户接了传感器却在界面上找不到读数，比标签不好看严重得多。
    for (const [key, value] of extraMetricEntries(nodeData)) {
        const label = escapeHtml(metricLabel(key));
        const unit = metricUnit(key);
        html += `<div class="card"><div class="card-title">${label}</div>`
             + `<div class="card-value" style="color: ${metricColor(key)};">${formatVal(value, unit)}</div></div>`;
    }

    // 补光灯状态。挂在哪个节点上由配置决定（auto_light.node_id/actuator_id），
    // 所以看能力而不是写死 'main'。切灯后的空窗期显示乐观值，
    // 服务端追上或 TTL 到期后自动交还——见 effectiveLightStatus。
    if (caps.light) {
        const status = effectiveLightStatus(globalData.light_status);
        if (status) {
            const color = status === 'ON' ? 'var(--metric-light-on)' : 'var(--text-muted)';
            // role/tabindex 让这张卡片可以 Tab 到达；Enter/Space 由
            // ui.js 的 initKeyboardActivation 统一处理
            html += `<div class="card" id="light-card" role="button" tabindex="0" style="cursor: pointer;" onclick="toggleLight()"><div class="card-title">${t('light_title')}</div><div class="card-value" id="light-status" style="color: ${color};">${status}</div></div>`;
        }
    }

    container.innerHTML = html;

    // Power System Health is rendered in System Tab.

    // Hardware Actions (Camera / Water)
    const hasKey = !!getViewerKey();
    const hasWaterKey = !!getWaterKey();
    const hasCamera = caps.camera;
    const hasPump = caps.pump;

    if (hasKey && hasCamera) {
        document.getElementById('camera-block').classList.remove('hidden');
    } else {
        document.getElementById('camera-block').classList.add('hidden');
    }

    // "照片"子页签跟每日照片开关走，不跟相机走：相机还在、只是不再拍每日照片时，
    // 实时画面要留下，照片栏目要收起。两者判据不同，所以不能合进上面那个分支。
    const hasPhotos = hasKey && caps.daily_photo;
    const pBtn = document.getElementById('hist-photos');
    if (pBtn) pBtn.classList.toggle('hidden', !hasPhotos);
    if (!hasPhotos && state.currentHistType === 'photos') switchHistType('24h');

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
    statusEl.style.color = 'var(--danger)';
}

export async function triggerWatering() {
    if (!getWaterKey()) return;
    const btn = document.getElementById('water-btn');
    const input = document.getElementById('water-duration');

    // 服务端会把时长钳制在 0.1–1.0（api/routers.py 的 trigger_manual_watering），
    // 但静默钳制会骗人：用户填 5 秒，界面回"浇水指令已发送"，实际只浇了 1 秒。
    // 所以在这里先钳制、告知、并把输入框改成真正生效的值。
    const raw = parseFloat(input.value);
    const wanted = Number.isFinite(raw) ? raw : WATER_DEFAULT_S;
    const duration = Math.min(WATER_MAX_S, Math.max(WATER_MIN_S, wanted));
    if (duration !== wanted) {
        showToast(t('water_clamped', { min: WATER_MIN_S, max: WATER_MAX_S }), 'info');
        input.value = duration;
    }

    btn.disabled = true; btn.innerText = t('watering_ing');
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

    // statusEl 里已经是 effectiveLightStatus 的结果，直接读它即可
    const currentStatus = statusEl.innerText.trim();
    const isCurrentlyOn = currentStatus === 'ON';
    const newStatus = isCurrentlyOn ? 'OFF' : 'ON';

    // 乐观更新：只用来填补"指令已发出、服务端还没回报"的空窗期
    optimisticLightStatus = newStatus;
    optimisticLightUntil = Date.now() + OPTIMISTIC_LIGHT_TTL_MS;
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
        // 指令没发出去，服务端状态没变过——直接丢掉乐观值回到服务端真相，
        // 顺手把 DOM 恢复成点击前的样子（下一次轮询会重新渲染这张卡片）。
        // 注意不要在这里写回 currentStatus 作为新的乐观值：那等于用一个
        // 永不过期的值继续遮蔽服务端，正是本次修复要消除的问题。
        clearOptimisticLight();
        statusEl.innerText = currentStatus;
        statusEl.style.color = isCurrentlyOn ? 'var(--metric-light-on)' : 'var(--text-muted)';
        showToast(e.message === 'camera' ? t('cam_capturing') : t('light_fail'), 'error');
    }

    // 1s debounce
    setTimeout(() => { lightToggleInProgress = false; }, 1000);
}
