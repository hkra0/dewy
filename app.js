const translations = {
    en: {
        env: "environment", sys: "system", hist: "history", settings: "settings",
        camera: "camera", manual_water: "manual watering", duration_s: "Duration (s):", water_btn: "Water",
        power_status: "power status", cpu_temp: "cpu temp", ram_used: "ram used", disk_used: "disk storage used",
        env_trends: "environmental trends", past_24h: "24h", daily_avg: "day", watering_log: "water", chart_loading: "loading...",
        auto_water: "Auto Watering", threshold: "Threshold (%)", duration: "Duration (s)", fill_light: "Fill Light",
        mode: "Mode", fixed_time: "Fixed Time", sunrise_sunset: "Sunrise & Sunset", turn_on: "Turn On", turn_off: "Turn Off",
        lat: "Latitude", lng: "Longitude", on_offset: "On Offset (min)", off_offset: "Off Offset (min)", currently_scheduled: "Currently scheduled: {on} to {off}",
        save_cfg: "Save Configuration", refresh: "refresh", capturing_hd: "capturing hd image...", close: "close", not_synced: "not synced",
        saving: "saving...", cfg_saved: "Configuration Saved!", fail_save: "Failed to save configuration.",
        no_data_node: "no data for this node", temp: "temperature", humidity: "humidity", soil_moisture: "soil moisture", pressure: "pressure",
        light_title: "fill light", watering_cmd: "Watering Command Sent!", watering_ing: "watering...", light_on: "Light turned ON", light_off: "Light turned OFF",
        cam_capturing: "Camera is capturing, try again later", light_fail: "Light toggle failed", no_water_records: "no watering records yet.",
        table_duration: "Duration (s)", table_soil: "Soil (%)", table_time: "Time", no_data: "no data available.",
        chart_temp: "temp (℃)", chart_hum: "hum (%)", chart_soil: "soil (%)", chart_pres: "pres (hPa)", syncing: "syncing...",
        cam_offline: "camera hardware offline or error", net_disconnect: "network disconnected", hd_capture_est: "capturing hd image... (est. 10s+)",
        fail_hd: "failed to capture hd image", last_synced: "last synced at {time}",
        photo_log: "photo", no_photos: "no photos yet",
        export_gif: "GIF", exporting: "creating...", gif_start: "Synthesizing GIF timeline, please wait...", gif_success: "GIF downloaded successfully", gif_error: "Failed to generate GIF.", gif_lib_missing: "GIF library loading, please try again in a moment."
    },
    zh: {
        env: "环境", sys: "系统", hist: "历史", settings: "设置",
        camera: "相机", manual_water: "手动浇水", duration_s: "时长 (秒):", water_btn: "浇水",
        power_status: "电源状态", cpu_temp: "处理器温度", ram_used: "内存使用率", disk_used: "存储使用率",
        env_trends: "环境趋势", past_24h: "24h", daily_avg: "日均", watering_log: "浇水", chart_loading: "加载中...",
        auto_water: "自动浇水", threshold: "湿度阈值 (%)", duration: "浇水时长 (秒)", fill_light: "补光灯",
        mode: "模式", fixed_time: "定时", sunrise_sunset: "日出 & 日落", turn_on: "开启时间", turn_off: "关闭时间",
        lat: "纬度", lng: "经度", on_offset: "开启偏移 (分钟)", off_offset: "关闭偏移 (分钟)", currently_scheduled: "当前计划: {on} 至 {off}",
        save_cfg: "保存配置", refresh: "刷新", capturing_hd: "正在拍摄高清图片...", close: "关闭", not_synced: "未同步",
        saving: "保存中...", cfg_saved: "配置已保存！", fail_save: "配置保存失败。",
        no_data_node: "该节点暂无数据", temp: "温度", humidity: "湿度", soil_moisture: "土壤湿度", pressure: "气压",
        light_title: "补光灯", watering_cmd: "浇水指令已发送！", watering_ing: "正在浇水...", light_on: "补光灯已开启", light_off: "补光灯已关闭",
        cam_capturing: "相机正在拍摄中，请稍后再试", light_fail: "补光灯切换失败", no_water_records: "暂无浇水记录。",
        table_duration: "时长 (秒)", table_soil: "土壤湿度 (%)", table_time: "时间", no_data: "暂无数据。",
        chart_temp: "温度 (℃)", chart_hum: "湿度 (%)", chart_soil: "土壤 (%)", chart_pres: "气压 (hPa)", syncing: "同步中...",
        cam_offline: "相机硬件离线或故障", net_disconnect: "网络已断开", hd_capture_est: "正在拍摄高清图片... (约10秒+)",
        fail_hd: "获取高清图片失败。", last_synced: "最后同步时间: {time}",
        photo_log: "照片", no_photos: "暂无照片",
        export_gif: "导出 GIF", exporting: "合成中...", gif_start: "正在高速合成延时动图，请稍候...", gif_success: "GIF 动图已生成", gif_error: "GIF 合成失败，请重试。", gif_lib_missing: "动图组件准备中，请稍后再试"
    }
};

let currentLang = (typeof navigator !== 'undefined' && navigator.language && navigator.language.startsWith('zh')) ? 'zh' : 'en';
function t(key, replacements = {}) {
    let text = translations[currentLang][key] || key;
    for (let k in replacements) {
        text = text.replace(`{${k}}`, replacements[k]);
    }
    return text;
}

function applyTranslations() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (key === 'currently_scheduled') return; // Handled dynamically
        el.innerText = t(key);
    });
}


function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerText = message;
    container.appendChild(toast);
    setTimeout(() => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
    }, 3000);
}

const STORAGE_KEY = 'robin_viewer_key';
let sessionHDSrc = null, sessionHDTime = null, sessionHDEpoch = 0, myChart = null;
let currentTab = 'environment', currentHistType = '24h', currentDevice = 'main';
let availableNodes = {};
const historyCache = {};

function toggleLightMode() {
    const mode = document.getElementById('cfg-light-mode').value;
    if (mode === 'fixed') {
        document.getElementById('cfg-light-fixed-group').classList.remove('hidden');
        document.getElementById('cfg-light-sun-group').classList.add('hidden');
    } else {
        document.getElementById('cfg-light-fixed-group').classList.add('hidden');
        document.getElementById('cfg-light-sun-group').classList.remove('hidden');
    }
}

async function fetchConfig() {
    const savedKey = localStorage.getItem(STORAGE_KEY) || '';
    const waterKey = localStorage.getItem('robin_water_key') || '';
    try {
        const res = await fetch('/api/config', { headers: { 'X-Viewer-Key': savedKey, 'x-water-key': waterKey, 'X-Requested-By': 'Robin-Web' } });
        const data = await res.json();
        if (data.error) return;

        document.getElementById('cfg-water-enabled').checked = data.auto_water.enabled;
        document.getElementById('cfg-water-threshold').value = data.auto_water.threshold;
        document.getElementById('cfg-water-duration').value = data.auto_water.duration;
        document.getElementById('cfg-light-enabled').checked = data.auto_light.enabled;
        document.getElementById('cfg-light-mode').value = data.auto_light.mode;
        document.getElementById('cfg-light-on').value = data.auto_light.on_time;
        document.getElementById('cfg-light-off').value = data.auto_light.off_time;
        document.getElementById('cfg-light-on-offset').value = data.auto_light.sun_on_offset;
        document.getElementById('cfg-light-off-offset').value = data.auto_light.sun_off_offset;
        document.getElementById('cfg-light-lat').value = data.auto_light.lat || "";
        document.getElementById('cfg-light-lng').value = data.auto_light.lng || "";
        if (data.effective_light_on && data.effective_light_off) document.getElementById('cfg-light-effective-times').innerText = `` + t('currently_scheduled', { on: data.effective_light_on, off: data.effective_light_off }) + ``;
        toggleLightMode();
    } catch (e) { console.error(e); }
}

async function saveConfig() {
    const waterKey = localStorage.getItem('robin_water_key');
    if (!waterKey) return;

    const btn = document.getElementById('save-cfg-btn');
    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = t('saving');

    const cfg = {
        auto_water: {
            enabled: document.getElementById('cfg-water-enabled').checked,
            threshold: parseFloat(document.getElementById('cfg-water-threshold').value) || 50.0,
            duration: parseFloat(document.getElementById('cfg-water-duration').value) || 0.5
        },
        auto_light: {
            enabled: document.getElementById('cfg-light-enabled').checked,
            mode: document.getElementById('cfg-light-mode').value,
            on_time: document.getElementById('cfg-light-on').value,
            off_time: document.getElementById('cfg-light-off').value,
            sun_on_offset: parseInt(document.getElementById('cfg-light-on-offset').value) || 0,
            sun_off_offset: parseInt(document.getElementById('cfg-light-off-offset').value) || 0,
            lat: document.getElementById('cfg-light-lat').value,
            lng: document.getElementById('cfg-light-lng').value
        }
    };

    try {
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'x-water-key': waterKey, 'Content-Type': 'application/json' },
            body: JSON.stringify(cfg)
        });
        if (res.ok) {
            showToast(t('cfg_saved'), 'success');

            setTimeout(() => {
                btn.innerText = originalText;

                btn.disabled = false;
            }, 2000);
        } else {
            throw new Error('Failed');
        }
    } catch (e) {
        showToast(t('fail_save'), 'error');

        setTimeout(() => {
            btn.innerText = originalText;

            btn.disabled = false;
        }, 2000);
    }
}

async function initNodes() {
    try {
        const savedKey = localStorage.getItem(STORAGE_KEY) || '';
        const res = await fetch('/api/nodes', { headers: { 'X-Viewer-Key': savedKey, 'X-Requested-By': 'Robin-Web' } });
        availableNodes = await res.json();
        const select = document.getElementById('device-select');
        select.innerHTML = '';
        for (let node_id in availableNodes) {
            let opt = document.createElement('option');
            opt.value = node_id;
            opt.innerText = node_id;
            select.appendChild(opt);
        }
        if (availableNodes[currentDevice]) select.value = currentDevice;
        else if (Object.keys(availableNodes).length > 0) currentDevice = Object.keys(availableNodes)[0];
    } catch (e) { }
}

function updateURL() {
    let newPath = '/';
    if (currentTab === 'system') newPath = `/${currentDevice}/system`;
    else if (currentTab === 'history') newPath = `/${currentDevice}/history`;
    else if (currentTab === 'settings') newPath = `/${currentDevice}/settings`;
    else newPath = `/${currentDevice}`;
    history.pushState({ tab: currentTab, dev: currentDevice }, '', newPath);
}

function switchDevice(dev, pushState = false) {
    currentDevice = dev;
    document.getElementById('device-select').value = dev;

    // clear cache for history
    for (let k in historyCache) delete historyCache[k];

    const nodeInfo = availableNodes[dev] || {};
    const hasSystem = nodeInfo.type === 'local';
    const hasPump = nodeInfo.actuators && ('pump' in nodeInfo.actuators);
    const hasSettings = nodeInfo.actuators && ('pump' in nodeInfo.actuators || 'light' in nodeInfo.actuators) && !!localStorage.getItem('robin_water_key');

    const hasKey = !!localStorage.getItem(STORAGE_KEY);
    const hasCamera = nodeInfo.sensors && ('camera' in nodeInfo.sensors);

    if (hasSystem) document.getElementById('tab-system').classList.remove('hidden');
    else document.getElementById('tab-system').classList.add('hidden');

    if (hasSettings) document.getElementById('tab-settings').classList.remove('hidden');
    else document.getElementById('tab-settings').classList.add('hidden');

    if (hasPump) document.getElementById('hist-watering').classList.remove('hidden');
    else document.getElementById('hist-watering').classList.add('hidden');

    if (hasKey && hasCamera) document.getElementById('hist-photos').classList.remove('hidden');
    else document.getElementById('hist-photos').classList.add('hidden');

    if ((currentTab === 'system' && !hasSystem) || (currentTab === 'settings' && !hasSettings)) {
        switchTab('environment', false, true);
    }

    if (currentHistType === 'watering' && !hasPump) {
        switchHistType('24h');
    }
    if (currentHistType === 'photos' && !(hasKey && hasCamera)) {
        switchHistType('24h');
    }

    if (pushState) updateURL();
    fetchAllData(false);
}

function switchTab(tabName, pushState = true, skipFetch = false) {
    const nodeInfo = availableNodes[currentDevice] || {};
    const hasSystem = nodeInfo.type === 'local';
    const hasSettings = nodeInfo.actuators && ('pump' in nodeInfo.actuators || 'light' in nodeInfo.actuators) && !!localStorage.getItem('robin_water_key');

    if (tabName === 'system' && !hasSystem) tabName = 'environment';
    if (tabName === 'settings' && !hasSettings) tabName = 'environment';

    currentTab = tabName;
    if (pushState) updateURL();

    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById('tab-' + tabName).classList.add('active');

    document.getElementById('view-environment').classList.add('hidden');
    document.getElementById('view-system').classList.add('hidden');
    document.getElementById('view-history').classList.add('hidden');
    document.getElementById('view-settings').classList.add('hidden');

    document.getElementById('view-' + tabName).classList.remove('hidden');

    if (tabName === 'history' && !skipFetch) loadHistoryData(false);
    if (tabName === 'settings') fetchConfig();
}

function switchHistType(type) {
    currentHistType = type;
    document.querySelectorAll('.sub-nav-btn').forEach(btn => btn.classList.remove('active'));
    const activeBtn = document.getElementById('hist-' + type);
    if (activeBtn) activeBtn.classList.add('active');

    if (type === 'watering') {
        document.getElementById('chart-container-wrapper').classList.add('hidden');
        document.getElementById('watering-log-wrapper').classList.remove('hidden');
        document.getElementById('photo-timeline-wrapper').classList.add('hidden');
    } else if (type === 'photos') {
        document.getElementById('chart-container-wrapper').classList.add('hidden');
        document.getElementById('watering-log-wrapper').classList.add('hidden');
        document.getElementById('photo-timeline-wrapper').classList.remove('hidden');
    } else {
        document.getElementById('chart-container-wrapper').classList.remove('hidden');
        document.getElementById('watering-log-wrapper').classList.add('hidden');
        document.getElementById('photo-timeline-wrapper').classList.add('hidden');
    }
    if (type === 'photos') {
        loadPhotoTimeline(false);
    } else {
        loadHistoryData(false);
    }
}

function renderDynamicCards(nodeData, globalData) {
    const container = document.getElementById('dynamic-cards');

    if (!nodeData) {
        container.innerHTML = `<div class="card full-width">${t('no_data_node')}</div>`;
        return;
    }

    const formatVal = (v, unit) => (v !== undefined && v !== null) ? `${v} ${unit}` : '--';
    let html = '';

    if (nodeData.temperature !== undefined) {
        html += `<div class="card"><div class="card-title">` + t('temp') + `</div><div class="card-value" style="color: #f59e0b;">${formatVal(nodeData.temperature, '℃')}</div></div>`;
    }
    if (nodeData.humidity !== undefined) {
        html += `<div class="card"><div class="card-title">` + t('humidity') + `</div><div class="card-value" style="color: #3b82f6;">${formatVal(nodeData.humidity, '%')}</div></div>`;
    }
    if (nodeData.soil_moisture !== undefined) {
        html += `<div class="card"><div class="card-title">` + t('soil_moisture') + `</div><div class="card-value" style="color: var(--accent);">${formatVal(nodeData.soil_moisture, '%')}</div></div>`;
    }
    if (nodeData.pressure !== undefined) {
        html += `<div class="card"><div class="card-title">` + t('pressure') + `</div><div class="card-value" style="color: #8b5cf6;">${formatVal(nodeData.pressure, 'hPa')}</div></div>`;
    }

    // Light Status (global for now, or you can attach to specific node)
    // Use optimistic status if available to prevent polling from reverting manual toggles
    if (currentDevice === 'main') {
        const effectiveStatus = optimisticLightStatus || globalData.light_status;
        if (effectiveStatus && effectiveStatus !== '--') {
            const color = effectiveStatus === 'ON' ? '#eab308' : 'var(--text-muted)';
            html += `<div class="card" id="light-card" style="cursor: pointer;" onclick="toggleLight()"><div class="card-title">` + t('light_title') + `</div><div class="card-value" id="light-status" style="color: ${color};">${effectiveStatus}</div></div>`;
        } else if (globalData.light_status) {
            const color = globalData.light_status === 'ON' ? '#eab308' : 'var(--text-muted)';
            html += `<div class="card" id="light-card" style="cursor: pointer;" onclick="toggleLight()"><div class="card-title">${t('light_title')}</div><div class="card-value" id="light-status" style="color: ${color};">${globalData.light_status}</div></div>`;
        }
    }

    container.innerHTML = html;

    // Power System Health is rendered in System Tab.

    // Hardware Actions (Camera / Water)
    const hasKey = !!localStorage.getItem(STORAGE_KEY);
    const hasWaterKey = !!localStorage.getItem('robin_water_key');
    const nodeInfo = availableNodes[currentDevice] || {};
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
        if (currentHistType === 'photos') switchHistType('24h');
    }

    if (hasWaterKey && hasPump) {
        document.getElementById('water-block').classList.remove('hidden');
    } else {
        document.getElementById('water-block').classList.add('hidden');
    }
}

async function fetchSensorData() {
    const savedKey = localStorage.getItem(STORAGE_KEY) || '';
    try {
        const res = await fetch('/api/monitor', { headers: { 'X-Viewer-Key': savedKey, 'X-Requested-By': 'Robin-Web' } });
        const data = await res.json();
        if (data.error) return;

        const nodeData = data.nodes ? data.nodes[currentDevice] : {};
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
        document.getElementById('update-time').innerText = t('last_synced', { time: time.toLocaleTimeString().toLowerCase() });
    } catch (e) { console.error(e); }
}

async function triggerWatering() {
    const waterKey = localStorage.getItem('robin_water_key');
    if (!waterKey) return;
    const btn = document.getElementById('water-btn');
    btn.disabled = true; btn.innerText = t('watering_ing');
    const duration = parseFloat(document.getElementById('water-duration').value) || 0.5;
    try {
        const res = await fetch('/api/water', { method: 'POST', headers: { 'x-water-key': waterKey, 'Content-Type': 'application/json' }, body: JSON.stringify({ duration, node_id: currentDevice }) });
        if (res.ok) { showToast(t('watering_cmd'), 'success'); setTimeout(() => { btn.innerText = t('water_btn'); btn.disabled = false; fetchAllData(true); }, 2000); }
        else throw new Error('fail');
    } catch (e) { showToast('Failed to save configuration.', 'error'); setTimeout(() => { btn.innerText = t('water_btn'); btn.disabled = false; }, 2000); }
}

let lightToggleInProgress = false;
let optimisticLightStatus = null;

async function toggleLight() {
    if (isCameraSyncing || isHDSyncing) return;
    if (lightToggleInProgress) return;
    const waterKey = localStorage.getItem('robin_water_key');
    if (!waterKey) return;
    const statusEl = document.getElementById('light-status');
    if (!statusEl) return;

    lightToggleInProgress = true;

    const currentStatus = optimisticLightStatus || statusEl.innerText.trim();
    const isCurrentlyOn = currentStatus === 'ON';
    const newStatus = isCurrentlyOn ? 'OFF' : 'ON';

    // Pure optimistic update — no server refresh needed
    optimisticLightStatus = newStatus;
    statusEl.innerText = newStatus;
    statusEl.style.color = newStatus === 'ON' ? '#eab308' : 'var(--text-muted)';
    showToast(newStatus === 'ON' ? t('light_on') : t('light_off'), 'success');

    try {
        const res = await fetch('/api/light', { method: 'POST', headers: { 'x-water-key': waterKey } });
        if (!res.ok) {
            if (res.status === 409) throw new Error('camera');
            throw new Error('fail');
        }
    } catch (e) {
        // Revert optimistic state on failure
        optimisticLightStatus = isCurrentlyOn ? 'ON' : null;
        statusEl.innerText = isCurrentlyOn ? 'ON' : 'OFF';
        statusEl.style.color = isCurrentlyOn ? '#eab308' : 'var(--text-muted)';
        showToast(e.message === 'camera' ? t('cam_capturing') : t('light_fail'), 'error');
    }

    // 1s debounce
    setTimeout(() => { lightToggleInProgress = false; }, 1000);
}

function renderHistoryUI(data, type, animate = false) {
    if (type === 'watering') {
        const wrapper = document.getElementById('watering-log-wrapper');
        if (!data || data.length === 0) { wrapper.innerHTML = `<div class="loading-text" style="position: relative; height: 100px; margin-top: 15px;">${t('no_water_records')}</div>`; return; }
        let html = '<div class="watering-table-wrapper"><table class="watering-table">';
        html += `<thead><tr><th>${t('table_duration')}</th><th>${t('table_soil')}</th><th>${t('table_time')}</th></tr></thead><tbody>`;
        data.forEach(item => {
            html += `<tr><td>${item.duration}</td><td>${item.soil}</td><td class="log-time" style="color: var(--text-muted); font-size: 12px;">${item.time}</td></tr>`;
        });
        wrapper.innerHTML = html + '</tbody></table></div>';
        return;
    }
    if (!data || data.length === 0) {
        if (myChart) { myChart.destroy(); myChart = null; }
        document.getElementById('chart-loading').innerText = t('no_data');
        document.getElementById('chart-loading').classList.remove('hidden');
        return;
    }
    document.getElementById('chart-loading').classList.add('hidden');

    const chartData = data;
    const labels = chartData.map(d => d.time);
    const datasets = [];

    const hasTemp = chartData.some(d => d.temp !== null && d.temp !== undefined);
    const hasHum = chartData.some(d => d.hum !== null && d.hum !== undefined);
    const hasSoil = chartData.some(d => d.soil !== null && d.soil !== undefined);
    const hasPres = chartData.some(d => d.pressure !== null && d.pressure !== undefined);

    if (hasTemp) datasets.push({ label: t('chart_temp'), data: chartData.map(d => d.temp), borderColor: '#f59e0b', tension: 0.4, pointRadius: 0, yAxisID: 'y', spanGaps: true });
    if (hasHum) datasets.push({ label: t('chart_hum'), data: chartData.map(d => d.hum), borderColor: '#3b82f6', tension: 0.4, pointRadius: 0, yAxisID: 'y1', spanGaps: true });
    if (hasSoil) datasets.push({ label: t('chart_soil'), data: chartData.map(d => d.soil), borderColor: '#10b981', tension: 0.4, pointRadius: 0, yAxisID: 'y1', spanGaps: true });
    if (hasPres) datasets.push({ label: t('chart_pres'), data: chartData.map(d => d.pressure), borderColor: '#8b5cf6', tension: 0.4, pointRadius: 0, yAxisID: 'y2', spanGaps: true });

    const computedStyle = getComputedStyle(document.documentElement);
    const textColor = computedStyle.getPropertyValue('--text-muted').trim() || '#666';
    const tooltipBg = computedStyle.getPropertyValue('--surface-color').trim() || 'rgba(0,0,0,0.8)';
    const tooltipText = computedStyle.getPropertyValue('--text-main').trim() || '#fff';
    const gridColor = computedStyle.getPropertyValue('--border').trim() || 'rgba(0,0,0,0.1)';

    if (myChart) {
        myChart.data.labels = labels;
        myChart.data.datasets = datasets;

        myChart.options.plugins.legend.labels.color = textColor;
        myChart.options.plugins.tooltip.titleColor = tooltipText;
        myChart.options.plugins.tooltip.bodyColor = tooltipText;
        myChart.options.plugins.tooltip.backgroundColor = tooltipBg;
        myChart.options.plugins.tooltip.borderColor = gridColor;

        myChart.options.scales.x.ticks.color = textColor;
        myChart.options.scales.x.grid.color = gridColor;
        myChart.options.scales.y.ticks.color = textColor;
        myChart.options.scales.y.grid.color = gridColor;
        myChart.options.scales.y1.ticks.color = textColor;
        myChart.options.scales.y1.grid.color = gridColor;

        if (animate || myChart.lastReqType !== type) {
            myChart.update();
        } else {
            myChart.update('none');
        }
        myChart.lastReqType = type;
        return;
    }

    const ctx = document.getElementById('historyChart').getContext('2d');
    myChart = new Chart(ctx, {
        type: 'line', data: { labels: labels, datasets: datasets },
        options: {
            responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { labels: { color: textColor } },
                tooltip: { titleColor: tooltipText, bodyColor: tooltipText, backgroundColor: tooltipBg, titleFont: { size: 13, family: 'Inter' }, bodyFont: { size: 12, family: 'Inter' }, padding: 10, cornerRadius: 8, borderColor: gridColor, borderWidth: 1 }
            },
            scales: {
                x: { grid: { display: false, color: gridColor }, ticks: { color: textColor, maxTicksLimit: 6, font: { size: 10 } } },
                y: { type: 'linear', display: true, position: 'left', grid: { color: gridColor }, ticks: { color: textColor, font: { size: 10 } } },
                y1: { type: 'linear', display: true, position: 'right', grid: { drawOnChartArea: false, color: gridColor }, ticks: { color: textColor, font: { size: 10 } } },
                y2: { type: 'linear', display: false, grid: { drawOnChartArea: false, color: gridColor } }
            }
        }
    });
    myChart.lastReqType = type;
}

let historyFetchTime = {};

async function loadHistoryData(forceFetch = false) {
    if (currentHistType === 'photos') {
        loadPhotoTimeline(forceFetch);
        return;
    }
    const savedKey = localStorage.getItem(STORAGE_KEY) || '';
    const reqType = currentHistType;
    const cacheKey = currentDevice + '_' + reqType;

    let animateUpdate = false;

    if (historyCache[cacheKey]) {
        const lastFetch = historyFetchTime[cacheKey] || 0;
        if (Date.now() - lastFetch > 30 * 60 * 1000) {
            animateUpdate = true;
        }

        if (!forceFetch) {
            renderHistoryUI(historyCache[cacheKey], reqType, animateUpdate);
            return;
        }
    } else {
        if (reqType === 'watering') document.getElementById('watering-log-wrapper').innerHTML = '<div class="loading-text" style="position: relative; height: 100px; margin-top: 15px;">loading...</div>';
        else { if (myChart) { myChart.destroy(); myChart = null; } document.getElementById('chart-loading').classList.remove('hidden'); }
    }

    try {
        const res = await fetch(`/api/history?hist_type=${reqType}&node_id=${currentDevice}`, { headers: { 'X-Viewer-Key': savedKey, 'X-Requested-By': 'Robin-Web' } });
        const data = await res.json();
        if (!data.error) {
            historyCache[cacheKey] = data;
            historyFetchTime[cacheKey] = Date.now();
            if (currentHistType === reqType) renderHistoryUI(data, reqType, animateUpdate);
        }
    } catch (e) { }
}

let currentCamBlobUrl = null;
let isCameraSyncing = false;
async function fetchImage(forceLive = false) {
    const savedKey = localStorage.getItem(STORAGE_KEY);
    const cameraBlock = document.getElementById('camera-block');

    if (!savedKey) { cameraBlock.classList.add('hidden'); return; }

    const img = document.getElementById('cam-img');
    const camTs = document.getElementById('cam-timestamp');

    camTs.innerText = t('syncing');
    camTs.style.color = '#94a3b8';
    isCameraSyncing = true;

    try {
        const endpoint = forceLive ? '/api/image?live=true&t=' : '/api/image?t=';
        const res = await fetch(endpoint + new Date().getTime(), {
            method: 'GET', headers: { 'X-Viewer-Key': savedKey }
        });

        if (!res.ok) {
            camTs.innerText = t('cam_offline');
            camTs.style.color = '#ef4444';
            if (currentTab === 'environment') cameraBlock.classList.remove('hidden');
            return;
        }

        const timestamp = res.headers.get('X-Image-Timestamp');
        const blob = await res.blob();

        img.onload = () => {
            if (timestamp) {
                const imgDate = new Date(parseInt(timestamp) * 1000);
                const isStale = (Date.now() - imgDate.getTime()) > 60000;
                camTs.innerText = (isStale ? '⏳ ' : '📸 ') + imgDate.toLocaleTimeString().toLowerCase();
                camTs.style.color = '#94a3b8';
            }
        };
        if (currentCamBlobUrl) URL.revokeObjectURL(currentCamBlobUrl);
        currentCamBlobUrl = URL.createObjectURL(blob);
        img.src = currentCamBlobUrl;

        if (currentTab === 'environment') cameraBlock.classList.remove('hidden');
    } catch (e) {
        camTs.innerText = t('net_disconnect');
        camTs.style.color = '#ef4444';
        if (currentTab === 'environment') cameraBlock.classList.remove('hidden');
    } finally {
        isCameraSyncing = false;
    }
}

let isHDSyncing = false;
async function fetchHDImage() {
    const savedKey = localStorage.getItem(STORAGE_KEY);
    if (!savedKey) return;

    const modal = document.getElementById('hd-modal');
    const hdImg = document.getElementById('hd-img');
    const statusText = document.getElementById('hd-status');
    const loader = document.getElementById('hd-loader');
    const hdTs = document.getElementById('hd-timestamp');

    hdImg.onload = null;

    const now = Date.now();
    if (sessionHDSrc && sessionHDEpoch > 0 && (now - sessionHDEpoch < 60000)) {
        statusText.style.display = 'none';
        loader.style.display = 'none';
        hdImg.src = sessionHDSrc;
        hdImg.style.display = 'block';
        hdImg.style.opacity = '1';
        hdImg.style.filter = 'none';
        hdTs.innerText = '📸 ' + sessionHDTime;
        hdTs.classList.remove('hidden');
        hdTs.style.opacity = '1';
        modal.style.display = 'flex';
        return;
    }

    statusText.style.display = 'block';
    statusText.innerText = t('hd_capture_est');
    loader.style.display = 'block';
    modal.style.display = 'flex';

    isHDSyncing = true;
    if (sessionHDSrc) {
        hdImg.src = sessionHDSrc;
        hdImg.style.display = 'block';
        hdImg.style.opacity = '1';
        hdImg.style.filter = 'none';
        if (sessionHDTime) {
            hdTs.innerText = '📸 ' + sessionHDTime;
            hdTs.classList.remove('hidden');
            hdTs.style.opacity = '1';
        }
    } else {
        hdImg.style.display = 'none';
        hdTs.classList.add('hidden');
    }

    try {
        const res = await fetch('/api/image?live=true&hq=true&t=' + new Date().getTime(), {
            method: 'GET', headers: { 'X-Viewer-Key': savedKey }
        });

        if (!res.ok) throw new Error('capture failed');

        const timestamp = res.headers.get('X-Image-Timestamp');
        const liveBlob = await res.blob();

        hdImg.onload = () => {
            statusText.style.display = 'none';
            loader.style.display = 'none';
            hdImg.style.display = 'block';
            sessionHDEpoch = Date.now();
            if (timestamp) {
                const imgDate = new Date(parseInt(timestamp) * 1000);
                sessionHDTime = imgDate.toLocaleTimeString().toLowerCase();
                hdTs.innerText = '📸 ' + sessionHDTime;
                hdTs.classList.remove('hidden');
            }
        };

        if (sessionHDSrc) URL.revokeObjectURL(sessionHDSrc);
        sessionHDSrc = URL.createObjectURL(liveBlob);
        hdImg.src = sessionHDSrc;

    } catch (e) {
        loader.style.display = 'none';
        statusText.style.display = 'block';
        statusText.innerText = t('fail_hd');
        statusText.style.color = '#ef4444';
    } finally {
        isHDSyncing = false;
    }
}
function closeHD() { document.getElementById('hd-modal').style.display = 'none'; }

async function fetchAllData(forceLive = false) {
    const btn = document.getElementById('refresh-btn');
    if (btn) btn.innerText = t('syncing');

    const tasks = [fetchSensorData()];
    const nodeInfo = availableNodes[currentDevice] || {};
    const hasCamera = nodeInfo.sensors && ('camera' in nodeInfo.sensors);

    if (currentTab === 'environment' && hasCamera) tasks.push(fetchImage(forceLive));
    if (currentTab === 'history') tasks.push(loadHistoryData(true));

    await Promise.allSettled(tasks);

    if (btn) btn.innerText = t('refresh');
}

function checkMagicLink() {
    const urlParams = new URLSearchParams(window.location.search);
    let updated = false;
    if (urlParams.get('key')) { localStorage.setItem(STORAGE_KEY, urlParams.get('key')); updated = true; }
    if (urlParams.get('water_key')) { localStorage.setItem('robin_water_key', urlParams.get('water_key')); updated = true; }
    if (updated) window.history.replaceState({}, document.title, window.location.pathname);
}

function parseURLAndNavigate() {
    const pathParts = window.location.pathname.split('/').filter(p => p);
    let initialDev = 'main';
    let initialTab = 'environment';
    if (pathParts.length > 0) {
        if (['system', 'history', 'settings'].includes(pathParts[0])) { initialTab = pathParts[0]; }
        else {
            initialDev = pathParts[0];
            if (pathParts.length > 1) initialTab = pathParts[1];
        }
    }
    switchDevice(initialDev, false);
    switchTab(initialTab, false, true);
}

// ========== Photo Timeline Player ==========
let tlPhotos = [];
let tlCurrentIdx = 0;
let tlPlaying = false;
let tlInterval = null;
let tlSpeed = 500;
const tlThumbCache = new Map();
const tlFetching = new Set();
let tlLastFetchTime = 0;

function getPhotoVersion(photo) {
    if (!photo) return '';
    return encodeURIComponent(`${photo.timestamp || ''}_${photo.size || ''}_${photo.thumb_size || ''}`);
}

async function loadPhotoTimeline(forceFetch = false) {
    const savedKey = localStorage.getItem(STORAGE_KEY) || '';
    const nodeInfo = availableNodes[currentDevice] || {};
    const hasCamera = nodeInfo.sensors && ('camera' in nodeInfo.sensors);
    if (!savedKey || !hasCamera) return;

    const loadingEl = document.getElementById('timeline-loading');
    const imgEl = document.getElementById('timeline-img');
    const dateEl = document.getElementById('timeline-date');
    const emptyEl = document.getElementById('timeline-empty');
    const slider = document.getElementById('tl-slider');
    const counter = document.getElementById('tl-counter');

    if (!forceFetch && tlPhotos.length > 0 && Date.now() - tlLastFetchTime < 300000) {
        renderTimelineFrame(tlCurrentIdx);
        return;
    }
    if (tlPhotos.length === 0 || !imgEl.getAttribute('src')) {
        if (emptyEl) emptyEl.classList.add('hidden');
        if (loadingEl) loadingEl.classList.remove('hidden');
    }
    try {
        const res = await fetch('/api/photos', {
            headers: { 'X-Viewer-Key': savedKey }
        });
        if (res.ok) {
            const list = await res.json();
            // Reverse to chronological order (oldest -> newest for timeline play)
            const newPhotos = list.reverse();
            newPhotos.forEach(p => {
                const oldP = tlPhotos.find(old => old.date === p.date);
                if (oldP && getPhotoVersion(oldP) !== getPhotoVersion(p) && tlThumbCache.has(p.date)) {
                    URL.revokeObjectURL(tlThumbCache.get(p.date));
                    tlThumbCache.delete(p.date);
                }
            });
            tlPhotos = newPhotos;
            tlLastFetchTime = Date.now();
        }
    } catch (e) {
        console.error("Failed to load photo list", e);
    }

    if (tlPhotos.length === 0) {
        if (loadingEl) loadingEl.classList.add('hidden');
        imgEl.src = "";
        dateEl.innerText = "";
        if (emptyEl) emptyEl.classList.remove('hidden');
        slider.max = "0";
        slider.value = "0";
        counter.innerText = "0 / 0";
        if (tlPlaying) toggleTimelinePlay();
        return;
    }

    if (emptyEl) emptyEl.classList.add('hidden');
    slider.min = "0";
    slider.max = String(tlPhotos.length - 1);
    if (tlCurrentIdx >= tlPhotos.length || tlCurrentIdx === 0) {
        tlCurrentIdx = tlPhotos.length - 1; // Default to newest photo
    }
    renderTimelineFrame(tlCurrentIdx);
}

async function fetchThumb(date) {
    if (tlThumbCache.has(date) || tlFetching.has(date)) return;
    tlFetching.add(date);
    try {
        const savedKey = localStorage.getItem(STORAGE_KEY) || '';
        const photo = tlPhotos.find(p => p.date === date);
        const ver = getPhotoVersion(photo);
        const res = await fetch(`/api/photos/${date}?thumb=1${ver ? '&v=' + ver : ''}`, {
            headers: { 'X-Viewer-Key': savedKey }
        });
        if (res.ok) {
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            tlThumbCache.set(date, url);
            // Maintain max cache size of 20
            if (tlThumbCache.size > 20) {
                const oldestKey = tlThumbCache.keys().next().value;
                if (oldestKey !== tlPhotos[tlCurrentIdx]?.date) {
                    URL.revokeObjectURL(tlThumbCache.get(oldestKey));
                    tlThumbCache.delete(oldestKey);
                }
            }
        }
    } catch (e) {
        console.error(`Failed to fetch thumb for ${date}`, e);
    } finally {
        tlFetching.delete(date);
    }
}

async function renderTimelineFrame(idx) {
    if (idx < 0 || idx >= tlPhotos.length) return;
    tlCurrentIdx = idx;
    const photo = tlPhotos[idx];

    document.getElementById('tl-slider').value = idx;
    document.getElementById('tl-counter').innerText = `${idx + 1} / ${tlPhotos.length}`;
    document.getElementById('timeline-date').innerText = photo.date;

    const imgEl = document.getElementById('timeline-img');
    const loadingEl = document.getElementById('timeline-loading');
    const emptyEl = document.getElementById('timeline-empty');
    if (emptyEl) emptyEl.classList.add('hidden');

    if (tlThumbCache.has(photo.date)) {
        if (loadingEl) loadingEl.classList.add('hidden');
        imgEl.src = tlThumbCache.get(photo.date);
    } else {
        if (!imgEl.getAttribute('src') && loadingEl) loadingEl.classList.remove('hidden');
        await fetchThumb(photo.date);
        if (tlThumbCache.has(photo.date) && tlCurrentIdx === idx) {
            if (loadingEl) loadingEl.classList.add('hidden');
            imgEl.src = tlThumbCache.get(photo.date);
        }
    }

    // Preload 6 frames ahead
    for (let step = 1; step <= 6; step++) {
        const nextIdx = (idx + step) % tlPhotos.length;
        if (!tlThumbCache.has(tlPhotos[nextIdx].date)) {
            fetchThumb(tlPhotos[nextIdx].date);
        }
    }
}

function toggleTimelinePlay() {
    const btn = document.getElementById('tl-play-btn');
    if (tlPlaying) {
        clearInterval(tlInterval);
        tlInterval = null;
        tlPlaying = false;
        btn.innerHTML = "&#9654;";
    } else {
        if (tlPhotos.length <= 1) return;
        tlPlaying = true;
        btn.innerHTML = "&#10074;&#10074;";
        if (tlCurrentIdx === tlPhotos.length - 1) {
            tlCurrentIdx = 0;
            renderTimelineFrame(0);
        }
        tlInterval = setInterval(() => {
            if (tlCurrentIdx < tlPhotos.length - 1) {
                renderTimelineFrame(tlCurrentIdx + 1);
            } else {
                toggleTimelinePlay(); // Auto stop at end
            }
        }, tlSpeed);
    }
}

function seekTimeline(val) {
    const idx = parseInt(val, 10);
    if (!isNaN(idx)) {
        renderTimelineFrame(idx);
    }
}

function setTimelineSpeed(ms) {
    tlSpeed = parseInt(ms, 10);
    if (tlPlaying) {
        clearInterval(tlInterval);
        tlInterval = setInterval(() => {
            if (tlCurrentIdx < tlPhotos.length - 1) {
                renderTimelineFrame(tlCurrentIdx + 1);
            } else {
                toggleTimelinePlay();
            }
        }, tlSpeed);
    }
}

function createWatermarkedFrame(imgUrl, dateText) {
    return new Promise((resolve) => {
        const img = new Image();
        img.onload = () => {
            const canvas = document.createElement('canvas');
            const targetWidth = 480;
            const aspect = img.naturalHeight / (img.naturalWidth || 1) || (3 / 4);
            const targetHeight = Math.round(targetWidth * aspect);
            canvas.width = targetWidth;
            canvas.height = targetHeight;
            const ctx = canvas.getContext('2d');

            ctx.drawImage(img, 0, 0, targetWidth, targetHeight);

            ctx.font = '600 13px Inter, -apple-system, sans-serif';
            const text = `📅 ${dateText}`;
            const textWidth = ctx.measureText(text).width;
            const padX = 8, padY = 5;
            const boxX = 10, boxY = targetHeight - 30;
            const boxW = textWidth + padX * 2;
            const boxH = 22;

            ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
            if (ctx.roundRect) {
                ctx.beginPath();
                ctx.roundRect(boxX, boxY, boxW, boxH, 6);
                ctx.fill();
            } else {
                ctx.fillRect(boxX, boxY, boxW, boxH);
            }

            ctx.fillStyle = '#ffffff';
            ctx.textBaseline = 'middle';
            ctx.fillText(text, boxX + padX, boxY + boxH / 2);

            resolve({ dataUrl: canvas.toDataURL('image/jpeg', 0.85), width: targetWidth, height: targetHeight });
        };
        img.onerror = () => resolve(null);
        img.src = imgUrl;
    });
}

async function ensureGifshotLoaded() {
    if (typeof gifshot !== 'undefined') return true;
    const cdns = [
        'https://cdnjs.cloudflare.com/ajax/libs/gifshot/0.3.2/gifshot.min.js',
        'https://unpkg.com/gifshot@0.3.3/build/gifshot.min.js',
        'https://cdn.jsdelivr.net/npm/gifshot@0.3.3/build/gifshot.min.js'
    ];
    for (let url of cdns) {
        try {
            await new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = url;
                script.onload = () => resolve(true);
                script.onerror = () => reject();
                document.head.appendChild(script);
            });
            if (typeof gifshot !== 'undefined') return true;
        } catch (e) {
            console.warn(`Failed to load GIF library from ${url}`);
        }
    }
    return typeof gifshot !== 'undefined';
}

async function exportTimelineGIF() {
    if (!tlPhotos || tlPhotos.length === 0) return;
    const btn = document.getElementById('tl-export-btn');
    if (!btn || btn.disabled) return;

    if (typeof gifshot === 'undefined') {
        showToast(t('gif_lib_missing'), 'info');
        btn.disabled = true;
        btn.innerText = '⏳...';
        const loaded = await ensureGifshotLoaded();
        if (!loaded || typeof gifshot === 'undefined') {
            btn.disabled = false;
            btn.innerText = t('export_gif');
            showToast(t('gif_error'), 'error');
            return;
        }
        btn.disabled = false;
    }

    if (tlPlaying) toggleTimelinePlay();
    btn.disabled = true;
    btn.innerText = t('exporting');
    showToast(t('gif_start'), 'info');

    const savedKey = localStorage.getItem(STORAGE_KEY) || '';
    const frameUrls = [];
    let gifWidth = 480, gifHeight = 360;

    try {
        for (let i = 0; i < tlPhotos.length; i++) {
            const photo = tlPhotos[i];
            let imgUrl = tlThumbCache.get(photo.date);
            let tempBlobUrl = null;

            if (!imgUrl) {
                try {
                    const ver = getPhotoVersion(photo);
                    const res = await fetch(`/api/photos/${photo.date}?thumb=1${ver ? '&v=' + ver : ''}`, {
                        headers: { 'X-Viewer-Key': savedKey }
                    });
                    if (res.ok) {
                        const blob = await res.blob();
                        tempBlobUrl = URL.createObjectURL(blob);
                        imgUrl = tempBlobUrl;
                    }
                } catch (err) {
                    console.error(`Error fetching frame ${photo.date}`, err);
                }
            }

            if (imgUrl) {
                const frame = await createWatermarkedFrame(imgUrl, photo.date);
                if (frame) {
                    frameUrls.push(frame.dataUrl);
                    gifWidth = frame.width;
                    gifHeight = frame.height;
                }
            }
            if (tempBlobUrl) URL.revokeObjectURL(tempBlobUrl);

            const percent = Math.round(((i + 1) / tlPhotos.length) * 50);
            btn.innerText = `${percent}%`;
        }

        if (frameUrls.length === 0) {
            throw new Error("No frames loaded");
        }

        const intervalSec = (tlSpeed || 500) / 1000;

        gifshot.createGIF({
            images: frameUrls,
            gifWidth: gifWidth,
            gifHeight: gifHeight,
            interval: intervalSec,
            numWorkers: 3,
            sampleInterval: 10,
            progressCallback: (captureProgress) => {
                const totalPercent = 50 + Math.round(captureProgress * 50);
                if (btn) btn.innerText = `${totalPercent}%`;
            }
        }, function (obj) {
            btn.disabled = false;
            btn.innerText = t('export_gif');
            if (!obj.error) {
                const a = document.createElement('a');
                a.href = obj.image;
                a.download = `dewy_timeline_${new Date().toISOString().slice(0, 10)}.gif`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                showToast(t('gif_success'), 'success');
            } else {
                showToast(t('gif_error'), 'error');
            }
        });
    } catch (e) {
        console.error("Failed during GIF export", e);
        btn.disabled = false;
        btn.innerText = t('export_gif');
        showToast(t('gif_error'), 'error');
    }
}

async function viewFullPhoto() {
    if (!tlPhotos || tlPhotos.length === 0 || tlCurrentIdx < 0 || tlCurrentIdx >= tlPhotos.length) return;
    const photo = tlPhotos[tlCurrentIdx];
    const modal = document.getElementById('hd-modal');
    const loader = document.getElementById('hd-loader');
    const statusText = document.getElementById('hd-status');
    const hdImg = document.getElementById('hd-img');
    const hdTs = document.getElementById('hd-timestamp');

    if (tlPlaying) toggleTimelinePlay();

    modal.style.display = 'flex';
    hdImg.style.display = 'none';
    hdTs.classList.add('hidden');
    loader.style.display = 'block';
    statusText.innerText = 'loading...';
    statusText.style.display = 'block';
    statusText.style.color = 'var(--text-main)';

    try {
        const savedKey = localStorage.getItem(STORAGE_KEY) || '';
        const ver = getPhotoVersion(photo);
        const res = await fetch(`/api/photos/${photo.date}?thumb=0${ver ? '&v=' + ver : ''}`, {
            headers: { 'X-Viewer-Key': savedKey }
        });
        if (!res.ok) throw new Error('failed to load full photo');
        const blob = await res.blob();
        hdImg.onload = () => {
            statusText.style.display = 'none';
            loader.style.display = 'none';
            hdImg.style.display = 'block';
            hdTs.innerText = '📅 ' + photo.date;
            hdTs.classList.remove('hidden');
        };
        hdImg.src = URL.createObjectURL(blob);
    } catch (e) {
        loader.style.display = 'none';
        statusText.style.display = 'block';
        statusText.innerText = t('fail_hd');
        statusText.style.color = '#ef4444';
    }
}

window.onload = async () => {
    checkMagicLink();
    applyTranslations();
    await initNodes();
    parseURLAndNavigate();
    fetchAllData(true);

    // Auto refresh every 30 seconds
    setInterval(() => {
        if (document.visibilityState === 'visible') {
            fetchAllData(false);
        }
    }, 30000);
};