import { t, tf } from './i18n.js';
import { showToast, escapeHtml } from './ui.js';
import { getWaterKey, state } from './state.js';
import { apiWater, apiWaterPost } from './api.js';
import { loadPhotoTimeline } from './timeline.js';

let dualSliderInitialized = false;
let loadedConfig = {};
let wateringSafety = {};

let configPollGeneration = 0;
function renderNodeConfigStatus(statuses = {}) {
    const el = document.getElementById('node-config-status');
    if (!el) return;
    const report = statuses[state.currentDevice] || { status: 'pending' };
    el.textContent = t('node_config_' + report.status) + (report.error ? `: ${report.error}` : '');
    el.title = report.actual ? JSON.stringify(report.actual, null, 2) : '';
}
async function pollNodeConfigStatus(generation, attempts = 0) {
    if (generation !== configPollGeneration || !getWaterKey()) return;
    try {
        const res = await apiWater('/api/config');
        if (!res.ok) return;
        const data = await res.json();
        if (generation !== configPollGeneration) return;
        renderNodeConfigStatus(data.node_config_status);
        const status = data.node_config_status?.[state.currentDevice]?.status;
        if (status === 'pending' && attempts < 19) {
            setTimeout(() => pollNodeConfigStatus(generation, attempts + 1), 1500);
        }
    } catch (error) { console.error(error); }
}

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
        // 补光灯按节点分段（auto_light.<node>），表单只展示当前设备那一段。
        // 当前设备没有灯时整张卡片是隐藏的（navigation.js 看 caps.light），
        // 保存时也不会写这一段——见 saveConfig。
        const light = (data.auto_light || {})[state.currentDevice] || {};
        document.getElementById('cfg-light-enabled').checked = light.enabled !== false;
        document.getElementById('cfg-light-mode').value = light.mode || 'fixed';
        document.getElementById('cfg-light-on').value = light.on_time || '07:30';
        document.getElementById('cfg-light-off').value = light.off_time || '21:30';
        document.getElementById('cfg-light-on-offset').value = light.sun_on_offset ?? 0;
        document.getElementById('cfg-light-off-offset').value = light.sun_off_offset ?? 0;
        document.getElementById('cfg-light-lat').value = light.lat || "";
        document.getElementById('cfg-light-lng').value = light.lng || "";
        const effective = (data.effective_light_times || {})[state.currentDevice];
        document.getElementById('cfg-light-effective-times').innerText =
            effective ? t('currently_scheduled', { on: effective.on, off: effective.off }) : '';

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

        // 远程节点动态设置：按 schema 元数据分组成卡片，见 renderNodeSettings
        const dev = state.currentDevice;
        const nodeInfo = state.availableNodes[dev] || {};
        const schema = nodeInfo.settings_schema;
        const nodeCards = document.getElementById('cfg-node-settings-card');
        if (nodeCards) {
            if (schema && Object.keys(schema).length > 0) {
                const currentVals = (data.node_settings && data.node_settings[dev]) || {};
                nodeCards.innerHTML = renderNodeSettings(schema, currentVals, `${nodeInfo.description || dev} ${t('settings')}`);
                // 赋值而不是 addEventListener：fetchConfig 每次切设备都会跑，不能叠监听器
                nodeCards.onchange = () => applyNodeSettingsVisibility(nodeCards);
                applyNodeSettingsVisibility(nodeCards);
                renderNodeConfigStatus(data.node_config_status);
            } else {
                nodeCards.innerHTML = '';
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

// —— 节点远程设置的渲染 ——
//
// 字段由 hardware_config 的 settings_schema 声明，前端不认识具体业务，
// 只认这几个可选的展示元数据（都不写时退化成"一项一行、一张卡片"）：
//   group    同组的字段放在同一张卡片里，标题取 i18n 的 cfg_group_<group>
//   row      同一 row 的字段排在一行（如报警下限~上限），行标题取 cfg_row_<row>，
//            行下说明取 cfg_row_<row>_hint
//   show_if  {字段: 值}，条件全部满足才显示（如积温参数只在积温模式下出现）
//   advanced 收进卡片底部默认折叠的"高级"区
// 藏起来的输入框照样留在 DOM 里，saveConfig 按 id 读取、原样回传。

function nodeControl(key, meta, val) {
    const id = `cfg-ns-${escapeHtml(key)}`;
    if (meta.type === 'boolean') return `<input type="checkbox" id="${id}" ${val === true ? 'checked' : ''}>`;
    if (meta.type === 'select') {
        return `<select id="${id}" class="form-select">${(meta.options || []).map(option =>
            `<option value="${escapeHtml(option)}" ${option === val ? 'selected' : ''}>${escapeHtml(t('option_' + option))}</option>`).join('')}</select>`;
    }
    const attrs = ['min', 'max', 'step'].filter(a => meta[a] !== undefined).map(a => `${a}="${meta[a]}"`).join(' ');
    return `<input type="${meta.type === 'number' ? 'number' : 'text'}" id="${id}" class="form-input" value="${escapeHtml(String(val))}" ${attrs}>`;
}

function nodeRow(fields, values) {
    const [firstKey, firstMeta] = fields[0];
    const value = (key, meta) => values[key] ?? meta.default ?? '';
    const label = fields.length > 1 || firstMeta.row
        ? tf('cfg_row_' + firstMeta.row, t(firstMeta.label || firstKey))
        : t(firstMeta.label || firstKey);
    const hint = firstMeta.row ? tf('cfg_row_' + firstMeta.row + '_hint', '') : '';
    const showIf = firstMeta.show_if ? ` data-show-if="${escapeHtml(JSON.stringify(firstMeta.show_if))}"` : '';
    const forId = `cfg-ns-${escapeHtml(firstKey)}`;

    let control;
    if (fields.length === 1 && firstMeta.type !== 'number' && firstMeta.type !== undefined && firstMeta.type !== 'text') {
        control = nodeControl(firstKey, firstMeta, value(firstKey, firstMeta));
    } else {
        // 同单位的一对是区间（10 ℃ ~ 30 ℃），不同单位的是两个量（1.8 ℃ / 30 min）
        const sameUnit = fields.every(([, m]) => (m.unit || '') === (firstMeta.unit || ''));
        const sep = `<span class="separator">${sameUnit ? '~' : '/'}</span>`;
        control = `<div class="input-group-row">${fields.map(([k, m]) =>
            nodeControl(k, m, value(k, m)) + (m.unit ? `<span>${escapeHtml(m.unit)}</span>` : '')).join(sep)}</div>`;
    }
    // 下拉框的每个选项可以有一句说明（option_desc_<value>），随选择切换
    const desc = firstMeta.type === 'select'
        ? `<div class="form-desc" data-option-desc="${forId}">${escapeHtml(tf('option_desc_' + value(firstKey, firstMeta), ''))}</div>`
        : (hint ? `<div class="form-desc">${escapeHtml(hint)}</div>` : '');
    return `<div class="ns-item"${showIf}><div class="form-row"><label for="${forId}">${escapeHtml(label)}</label>${control}</div>${desc}</div>`;
}

export function renderNodeSettings(schema, values, defaultTitle) {
    // 按 schema 的声明顺序：组按首次出现排序，行内字段也按声明顺序
    const groups = new Map();
    for (const [key, meta] of Object.entries(schema)) {
        const g = meta.group || '';
        if (!groups.has(g)) groups.set(g, new Map());
        const rows = groups.get(g);
        const rowKey = meta.row ? 'row:' + meta.row : 'key:' + key;
        if (!rows.has(rowKey)) rows.set(rowKey, []);
        rows.get(rowKey).push([key, meta]);
    }
    const cards = [...groups].map(([g, rows], i, all) => {
        const title = g ? tf('cfg_group_' + g, g) : defaultTitle;
        const main = [], advanced = [];
        for (const fields of rows.values()) (fields[0][1].advanced ? advanced : main).push(nodeRow(fields, values));
        const adv = advanced.length
            ? `<details class="form-advanced"><summary>${escapeHtml(t('settings_advanced'))}</summary><div class="form-group">${advanced.join('')}</div></details>`
            : '';
        // 同步状态只放一处：最后一张卡片底部
        const status = i === all.length - 1 ? '<p id="node-config-status" class="card-subtitle" aria-live="polite"></p>' : '';
        return `<div class="card full-width form-card"><div class="form-card-head"><span>${escapeHtml(title)}</span></div>`
            + `<div class="form-body">${main.join('')}${adv}${status}</div></div>`;
    });
    return cards.join('');
}

/** 按当前表单值重算 show_if 的显隐，并刷新下拉框的选项说明。 */
export function applyNodeSettingsVisibility(root) {
    const current = key => {
        const el = document.getElementById(`cfg-ns-${key}`);
        if (!el) return undefined;
        return el.type === 'checkbox' ? el.checked : el.value;
    };
    root.querySelectorAll('[data-show-if]').forEach(item => {
        let cond = {};
        try { cond = JSON.parse(item.dataset.showIf); } catch (e) { /* 坏的元数据：照常显示 */ }
        const ok = Object.entries(cond).every(([k, want]) =>
            (Array.isArray(want) ? want : [want]).some(w => String(w) === String(current(k))));
        item.classList.toggle('hidden', !ok);
    });
    // 折叠区里的项全被条件藏起来时，连"高级"标题一起收起
    root.querySelectorAll('.form-advanced').forEach(det => {
        det.classList.toggle('hidden', !det.querySelector('.ns-item:not(.hidden)'));
    });
    root.querySelectorAll('[data-option-desc]').forEach(desc => {
        const sel = document.getElementById(desc.dataset.optionDesc);
        if (sel) desc.textContent = tf('option_desc_' + sel.value, '');
    });
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
                } else if (meta.type === 'boolean') {
                    thisNodeSettings[key] = inputEl.checked;
                } else {
                    thisNodeSettings[key] = inputEl.value;
                }
            }
        }
        nodeSettings[dev] = thisNodeSettings;
    }

    // 只改当前设备那一段，其它节点的灯原样回传
    const lights = { ...(loadedConfig.auto_light || {}) };
    if (lights[dev]) {
        lights[dev] = {
            ...lights[dev],
            enabled: document.getElementById('cfg-light-enabled').checked,
            mode: document.getElementById('cfg-light-mode').value,
            on_time: document.getElementById('cfg-light-on').value,
            off_time: document.getElementById('cfg-light-off').value,
            sun_on_offset: parseInt(document.getElementById('cfg-light-on-offset').value) || 0,
            sun_off_offset: parseInt(document.getElementById('cfg-light-off-offset').value) || 0,
            lat: document.getElementById('cfg-light-lat').value,
            lng: document.getElementById('cfg-light-lng').value
        };
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
        auto_light: lights,
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
            loadedConfig = cfg;
            const result = await res.json();
            renderNodeConfigStatus(result.node_config_status);
            setTimeout(() => pollNodeConfigStatus(++configPollGeneration), 1500);
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
