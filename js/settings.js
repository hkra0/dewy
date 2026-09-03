import { t } from './i18n.js';
import { showToast, escapeHtml } from './ui.js';
import { getWaterKey, state } from './state.js';
import { apiWater, apiWaterPost } from './api.js';
import { loadPhotoTimeline } from './timeline.js';

let dualSliderInitialized = false;
let loadedConfig = {};
let wateringSafety = {};

function renderWateringSafety(status = {}) {
    wateringSafety = status;
    const manual = status.manual_stop === true;
    const sensor = status.sensor_interlock === true;
    const label = document.getElementById('pump-safety-status');
    const btn = document.getElementById('pump-emergency-btn');
    const banner = document.getElementById('pump-safety-banner');
    const bannerText = document.getElementById('pump-safety-banner-text');
    const bannerAction = document.getElementById('pump-safety-banner-action');
    const needed = loadedConfig.auto_water?.sensor_recovery_samples ?? 3;

    if (btn) {
        btn.classList.toggle('is-active', manual);
        btn.classList.toggle('is-sensor-locked', sensor);
        btn.setAttribute('aria-pressed', manual ? 'true' : 'false');
        btn.setAttribute('aria-label', t(manual ? 'pump_emergency_release' : 'pump_emergency_stop'));
        btn.disabled = false;
    }

    let statusText = '';
    if (manual && sensor) statusText = t('pump_both_locked');
    else if (manual) statusText = t('pump_manual_stopped');
    else if (sensor) statusText = t('pump_sensor_locked', {
        count: status.recovery_count ?? 0, needed,
    });
    else statusText = t('pump_ready');

    if (label) label.innerText = statusText;
    if (btn) btn.title = statusText;

    if (banner) {
        if (manual || sensor) {
            banner.classList.remove('hidden');
            banner.classList.toggle('is-sensor-only', !manual && sensor);
            if (bannerText) bannerText.innerText = statusText;
            if (bannerAction) {
                // 人工急停允许用户主动解除；传感器联锁由硬件读数回稳后自动清除
                if (manual) {
                    bannerAction.style.display = '';
                    bannerAction.innerText = t('pump_emergency_release');
                    bannerAction.disabled = false;
                } else {
                    bannerAction.style.display = 'none';
                }
            }
        } else {
            banner.classList.add('hidden');
        }
    }
}

export async function togglePumpEmergencyStop() {
    if (!getWaterKey()) return;
    const btn = document.getElementById('pump-emergency-btn');
    const bannerAction = document.getElementById('pump-safety-banner-action');
    const active = wateringSafety.manual_stop !== true;
    if (btn) btn.disabled = true;
    if (bannerAction) bannerAction.disabled = true;
    try {
        const res = await apiWaterPost('/api/water/emergency-stop', {
            active,
            node_id: loadedConfig.auto_water?.node_id || 'main',
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderWateringSafety(data.watering_safety || {});
        if (active && data.watering_safety?.pump_off_sent === false) {
            showToast(t('pump_off_fail'), 'error');
        } else {
            showToast(t(active ? 'pump_stop_set' : 'pump_stop_released'), 'success');
        }
    } catch (e) {
        console.error(e);
        if (btn) btn.disabled = false;
        if (bannerAction) bannerAction.disabled = false;
        showToast(t('pump_stop_fail'), 'error');
    }
}

function initDualSlider() {
    const threshInput = document.getElementById('cfg-water-threshold');
    const targetInput = document.getElementById('cfg-water-target');
    const threshVal = document.getElementById('water-thresh-val');
    const targetVal = document.getElementById('water-target-val');
    const container = document.getElementById('cfg-water-group').querySelector('.dual-slider-container');
    
    function updateSlider() {
        let minVal = parseInt(threshInput.value);
        let maxVal = parseInt(targetInput.value);
        
        if (maxVal - minVal < 5) {
            if (this === threshInput) {
                threshInput.value = maxVal - 5;
                minVal = parseInt(threshInput.value);
            } else {
                targetInput.value = minVal + 5;
                maxVal = parseInt(targetInput.value);
            }
        }
        
        threshVal.innerText = minVal;
        targetVal.innerText = maxVal;
        container.style.setProperty('--track-fill-start', minVal + '%');
        container.style.setProperty('--track-fill-end', maxVal + '%');
    }
    
    if (!dualSliderInitialized && container) {
        threshInput.addEventListener('input', updateSlider);
        targetInput.addEventListener('input', updateSlider);
        dualSliderInitialized = true;
    }
    if (container) updateSlider.call(threshInput);
}

export function toggleLightMode() {
    const mode = document.getElementById('cfg-light-mode').value;
    if (mode === 'fixed') {
        document.getElementById('cfg-light-fixed-group').classList.remove('hidden');
        document.getElementById('cfg-light-sun-group').classList.add('hidden');
    } else {
        document.getElementById('cfg-light-fixed-group').classList.add('hidden');
        document.getElementById('cfg-light-sun-group').classList.remove('hidden');
    }
}

/** 通用："开关关闭时收起对应的子设置区"，设置页四张卡（自动浇水、补光灯、
 *  每日照片、土壤自动校准）共用这一个函数，不再各写一份。
 *
 *  switchId 是开关 checkbox 的 id，groupId 是随开关状态一起显隐的容器 id。
 *  本地即时反馈，不等保存。关掉时收起是因为这些设置此时都不会被对应的
 *  后台逻辑用到——展开徒增噪音，也容易让人以为改了就立刻生效（尤其"重新
 *  拍摄"：拍出来的照片会落进一个同样被隐藏的时间轴，等于拍了看不到）。
 *  隐藏不影响保存：saveConfig 读的是 DOM 里的当前值，隐藏元素的 value/checked
 *  照样存在，提交时原样回传。
 *
 *  HTML 里直接以 onchange="toggleSettingsGroup('cfg-xxx-enabled','cfg-xxx-group')"
 *  调用；新增一张带开关的设置卡时，照此接一行即可，不需要再写专用函数。
 */
export function toggleSettingsGroup(switchId, groupId) {
    const on = document.getElementById(switchId).checked;
    document.getElementById(groupId).classList.toggle('hidden', !on);
}

/** 设置页数据未就绪前的占位卡与实际内容之间切换。
 *
 *  两者是兄弟节点而不是"内容上盖一层遮罩"：盖遮罩的话，字段在遮罩后面已经
 *  被上一次的值（或空值）填好，用户在加载的一瞬间会看到一闪而过的旧内容。
 *  直接不渲染内容区，就没有这个问题——参见 index.html 里 #settings-content
 *  用 display:contents，只为整体显隐、不参与网格布局。
 */
function showSettingsLoading(loading) {
    document.getElementById('settings-loading').classList.toggle('hidden', !loading);
    document.getElementById('settings-content').classList.toggle('hidden', loading);
}

export async function fetchConfig() {
    showSettingsLoading(true);
    try {
        const res = await apiWater('/api/config');

        // 设置页只对持有浇水密钥的人可见，所以这里的失败不是访客路径——
        // 多半是密钥失效或树莓派掉线，必须让用户看见。
        // 不检查 res.ok 的话，403 会静默返回，留下一屏空输入框。
        if (!res.ok) { showToast(t('fail_load_cfg'), 'error'); return; }

        const data = await res.json();
        if (data.error) { showToast(t('fail_load_cfg'), 'error'); return; }

        loadedConfig = data;
        document.getElementById('cfg-water-enabled').checked = data.auto_water.enabled;
        document.getElementById('cfg-water-threshold').value = data.auto_water.threshold;
        document.getElementById('cfg-water-target').value = data.auto_water.target_moisture ?? 85;
        document.getElementById('cfg-water-duration').value = data.auto_water.duration;
        document.getElementById('cfg-water-pulse-interval').value = data.auto_water.pulse_interval ?? 60;
        document.getElementById('cfg-water-max-pulses').value = data.auto_water.max_pulses ?? 10;
        document.getElementById('cfg-water-min-interval').value = data.auto_water.min_interval_hours ?? 12;
        document.getElementById('cfg-water-start-hour').value = data.auto_water.start_hour ?? 6;
        document.getElementById('cfg-water-end-hour').value = data.auto_water.end_hour ?? 20;
        renderWateringSafety(data.watering_safety || {});
        
        initDualSlider();
        document.getElementById('cfg-light-enabled').checked = data.auto_light.enabled;
        document.getElementById('cfg-light-mode').value = data.auto_light.mode;
        document.getElementById('cfg-light-on').value = data.auto_light.on_time;
        document.getElementById('cfg-light-off').value = data.auto_light.off_time;
        document.getElementById('cfg-light-on-offset').value = data.auto_light.sun_on_offset;
        document.getElementById('cfg-light-off-offset').value = data.auto_light.sun_off_offset;
        document.getElementById('cfg-light-lat').value = data.auto_light.lat || "";
        document.getElementById('cfg-light-lng').value = data.auto_light.lng || "";
        if (data.effective_light_on && data.effective_light_off) document.getElementById('cfg-light-effective-times').innerText = `` + t('currently_scheduled', { on: data.effective_light_on, off: data.effective_light_off }) + ``;

        // 两个段都可能来自旧版本配置文件，取不到时用后端默认值兜底。
        // 补光在 camera 段而不是 daily_photo 段：它对所有拍摄路径生效。
        const photo = data.daily_photo || {};
        const cam = data.camera || {};
        document.getElementById('cfg-photo-fill-light').checked = cam.fill_light !== false;
        document.getElementById('cfg-photo-enabled').checked = photo.enabled !== false;
        document.getElementById('cfg-photo-hour').value = photo.hour ?? 12;

        // 同样可能来自旧版本配置文件（这段设置是后加的），取不到时用后端默认值兜底。
        // max_drift_ratio 后端存的是 0-1 的比率，界面按百分比展示更直观。
        const calib = data.soil_calibration || {};
        document.getElementById('cfg-calib-enabled').checked = calib.enabled !== false;
        document.getElementById('cfg-calib-window-days').value = calib.window_days ?? 30;
        document.getElementById('cfg-calib-max-drift').value = Math.round((calib.max_drift_ratio ?? 0.15) * 100);

        // 远程节点动态设置
        const dev = state.currentDevice;
        const nodeInfo = state.availableNodes[dev] || {};
        const schema = nodeInfo.settings_schema;
        const nodeCard = document.getElementById('cfg-node-settings-card');
        const nodeTitle = document.getElementById('cfg-node-settings-title');
        const nodeGroup = document.getElementById('cfg-node-settings-group');
        if (nodeCard && nodeGroup) {
            if (schema && Object.keys(schema).length > 0) {
                if (nodeTitle) {
                    nodeTitle.innerText = `${nodeInfo.description || dev} ${t('settings')}`;
                }
                let html = '';
                const currentVals = (data.node_settings && data.node_settings[dev]) || {};
                for (const [key, meta] of Object.entries(schema)) {
                    const label = t(meta.label || key);
                    const val = currentVals[key] ?? meta.default ?? '';
                    const min = meta.min !== undefined ? `min="${meta.min}"` : '';
                    const max = meta.max !== undefined ? `max="${meta.max}"` : '';
                    const step = meta.step !== undefined ? `step="${meta.step}"` : '';
                    const unit = meta.unit ? `<span class="unit-label" style="margin-left:6px; opacity:0.8;">${escapeHtml(meta.unit)}</span>` : '';
                    html += `<div class="form-row">
                        <label for="cfg-ns-${escapeHtml(key)}">${escapeHtml(label)}</label>
                        <div style="display:flex; align-items:center;">
                            <input type="${meta.type === 'number' ? 'number' : 'text'}" 
                                   id="cfg-ns-${escapeHtml(key)}" 
                                   class="form-input form-input--sm" 
                                   value="${escapeHtml(String(val))}" 
                                   ${min} ${max} ${step}>
                            ${unit}
                        </div>
                    </div>`;
                }
                nodeGroup.innerHTML = html;
            } else {
                nodeGroup.innerHTML = '';
            }
        }

        toggleLightMode();
        toggleSettingsGroup('cfg-water-enabled', 'cfg-water-group');
        toggleSettingsGroup('cfg-light-enabled', 'cfg-light-group');
        toggleSettingsGroup('cfg-photo-enabled', 'cfg-photo-daily-group');
        toggleSettingsGroup('cfg-calib-enabled', 'cfg-calib-group');
    } catch (e) {
        console.error(e);
        showToast(t('fail_load_cfg'), 'error');
    } finally {
        // 无论成功、失败还是抛异常都要收起占位卡——错误已经用 toast 说明了，
        // 不该让用户永远停在转圈上。
        showSettingsLoading(false);
    }
}

/** 保存设置页的全部配置。返回是否保存成功——调用方据此决定要不要重算
 *  界面显隐（每日照片开关会改变"照片"子页签的存在与否）。 */
export async function saveConfig() {
    if (!getWaterKey()) return false;

    const btn = document.getElementById('save-cfg-btn');
    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = t('saving');

    // 收集当前节点的远程动态设置
    const dev = state.currentDevice;
    const nodeInfo = state.availableNodes[dev] || {};
    const schema = nodeInfo.settings_schema;
    const nodeSettings = { ...(loadedConfig.node_settings || {}) };
    if (schema && Object.keys(schema).length > 0) {
        const thisNodeSettings = { ...(nodeSettings[dev] || {}) };
        for (const [key, meta] of Object.entries(schema)) {
            const inputEl = document.getElementById(`cfg-ns-${key}`);
            if (inputEl) {
                if (meta.type === 'number') {
                    const num = parseFloat(inputEl.value);
                    thisNodeSettings[key] = isNaN(num) ? (meta.default ?? 0) : num;
                } else {
                    thisNodeSettings[key] = inputEl.value;
                }
            }
        }
        nodeSettings[dev] = thisNodeSettings;
    }

    const cfg = {
        auto_water: {
            ...(loadedConfig.auto_water || {}),
            enabled: document.getElementById('cfg-water-enabled').checked,
            threshold: Math.min(100, Math.max(0, parseFloat(document.getElementById('cfg-water-threshold').value) || 65.0)),
            target_moisture: Math.min(100, Math.max(0, parseFloat(document.getElementById('cfg-water-target').value) || 85.0)),
            duration: Math.min(5.0, Math.max(0.1, parseFloat(document.getElementById('cfg-water-duration').value) || 0.5)),
            pulse_interval: Math.min(300, Math.max(10, parseInt(document.getElementById('cfg-water-pulse-interval').value) || 60)),
            max_pulses: Math.min(30, Math.max(1, parseInt(document.getElementById('cfg-water-max-pulses').value) || 10)),
            min_interval_hours: Math.min(72, Math.max(1, parseInt(document.getElementById('cfg-water-min-interval').value) || 12)),
            start_hour: Math.min(23, Math.max(0, parseInt(document.getElementById('cfg-water-start-hour').value) || 6)),
            end_hour: Math.min(23, Math.max(0, parseInt(document.getElementById('cfg-water-end-hour').value) || 20))
        },
        auto_light: {
            ...(loadedConfig.auto_light || {}),
            enabled: document.getElementById('cfg-light-enabled').checked,
            mode: document.getElementById('cfg-light-mode').value,
            on_time: document.getElementById('cfg-light-on').value,
            off_time: document.getElementById('cfg-light-off').value,
            sun_on_offset: parseInt(document.getElementById('cfg-light-on-offset').value) || 0,
            sun_off_offset: parseInt(document.getElementById('cfg-light-off-offset').value) || 0,
            lat: document.getElementById('cfg-light-lat').value,
            lng: document.getElementById('cfg-light-lng').value
        },
        camera: {
            ...(loadedConfig.camera || {}),
            fill_light: document.getElementById('cfg-photo-fill-light').checked
        },
        daily_photo: {
            ...(loadedConfig.daily_photo || {}),
            enabled: document.getElementById('cfg-photo-enabled').checked,
            // 后端按整点判断（背景循环 10 分钟一轮），越界值会让每日照片永远拍不成
            hour: Math.min(23, Math.max(0, parseInt(document.getElementById('cfg-photo-hour').value) || 0))
        },
        soil_calibration: {
            ...(loadedConfig.soil_calibration || {}),
            enabled: document.getElementById('cfg-calib-enabled').checked,
            // 窗口太短统计不稳，太长又会超过 DEWY_DATA_RETENTION_DAYS（默认 365）
            window_days: Math.min(365, Math.max(7, parseInt(document.getElementById('cfg-calib-window-days').value) || 30)),
            // 界面按百分比展示，后端存 0-1 的比率
            max_drift_ratio: Math.min(1, Math.max(0.01, (parseFloat(document.getElementById('cfg-calib-max-drift').value) || 15) / 100))
        },
        node_settings: nodeSettings
    };

    try {
        const res = await apiWaterPost('/api/config', cfg);
        if (res.ok) {
            showToast(t('cfg_saved'), 'success');

            setTimeout(() => {
                btn.innerText = originalText;

                btn.disabled = false;
            }, 2000);
            return true;
        } else {
            throw new Error('Failed');
        }
    } catch (e) {
        showToast(t('fail_save'), 'error');

        setTimeout(() => {
            btn.innerText = originalText;

            btn.disabled = false;
        }, 2000);
        return false;
    }
}

// —— 重新拍摄当日照片 ——
//
// 覆盖不可撤销（原图与缩略图都会被换掉），所以要二次确认。确认没有做成
// confirm() 弹窗：那个模态框会打断整页、在移动端尤其突兀，而这里只是一个
// 次要操作。改成"按钮自己变成确认态，三秒后自动退回"——不点第二下就等于取消，
// 不需要用户去点"否"。
//
// 当日**没有**照片时不问：那一下不会覆盖任何东西，弹确认属于噪音。
// 是否已有照片由后端判定（409），不看前端那份可能过期的照片列表——
// 时间轴的缓存有五分钟，靠它判断会漏掉"刚到点自动拍了一张"的情况。
const RETAKE_CONFIRM_MS = 3000;
let retakeConfirmTimer = null;

function disarmRetake(btn) {
    clearTimeout(retakeConfirmTimer);
    retakeConfirmTimer = null;
    btn.classList.remove('confirming');
    btn.innerText = t('retake_photo');
}

function armRetake(btn) {
    btn.classList.add('confirming');
    btn.innerText = t('retake_confirm_btn');
    showToast(t('retake_confirm'), 'error');
    retakeConfirmTimer = setTimeout(() => disarmRetake(btn), RETAKE_CONFIRM_MS);
}

export async function retakeTodayPhoto() {
    if (!getWaterKey()) return;

    const btn = document.getElementById('retake-photo-btn');
    // 处于确认态说明这是三秒内的第二次点击：直接带 force 覆盖。
    const force = retakeConfirmTimer !== null;
    if (force) disarmRetake(btn);

    btn.disabled = true;
    btn.innerText = t('retaking_btn');
    // 这里**不**弹"拍摄中"提示：第一次点击有可能只是撞上 409（当天已有照片，
    // 什么都没拍），弹了就是假消息。HQ 抓拍的十几秒由按钮自己显示状态，
    // 与保存按钮的 saving… 是同一套做法。
    try {
        const res = await apiWaterPost('/api/photo/retake' + (force ? '?force=true' : ''));

        if (res.status === 409) {
            // 当日已有照片，等用户再点一次确认覆盖
            btn.disabled = false;
            armRetake(btn);
            return;
        }

        btn.disabled = false;
        btn.innerText = t('retake_photo');

        if (res.status === 423) { showToast(t('cam_capturing'), 'error'); return; }
        if (!res.ok) { showToast(t('retake_fail'), 'error'); return; }

        showToast(t('retake_success'), 'success');
        // 时间轴的缩略图缓存按 timestamp_size_thumbSize 失效，
        // 重拍已经刷新了 timestamp，这里强拉一次列表就能换成新图。
        loadPhotoTimeline(true);
    } catch (e) {
        console.error(e);
        btn.disabled = false;
        btn.innerText = t('retake_photo');
        showToast(t('retake_fail'), 'error');
    }
}
