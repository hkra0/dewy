// 设备/标签页/历史子页的切换与 URL 同步。
import { state, STORAGE_KEY, WATER_KEY, getViewerKey } from './state.js';
import { apiGet } from './api.js';
import { clearHistoryCache, loadHistoryData } from './history.js';
import { loadPhotoTimeline } from './timeline.js';
import { fetchConfig } from './settings.js';
import { fetchAllData } from './refresh.js';

export async function initNodes() {
    const wrapper = document.getElementById('device-select-wrapper');

    // 无密钥是被设计成"什么都不发生"的访客路径：不发注定 404 的请求，
    // 也不要留下 "Loading..." 这种"有东西没加载出来"的痕迹。
    if (!getViewerKey()) {
        if (wrapper) wrapper.classList.add('hidden');
        return;
    }

    try {
        const res = await apiGet('/api/nodes');
        if (!res.ok) {
            if (wrapper) wrapper.classList.add('hidden');
            return;
        }
        state.availableNodes = await res.json();
        const select = document.getElementById('device-select');
        select.innerHTML = '';
        for (let node_id in state.availableNodes) {
            let opt = document.createElement('option');
            opt.value = node_id;
            opt.innerText = node_id;
            select.appendChild(opt);
        }
        if (state.availableNodes[state.currentDevice]) select.value = state.currentDevice;
        else if (Object.keys(state.availableNodes).length > 0) state.currentDevice = Object.keys(state.availableNodes)[0];

        if (wrapper) wrapper.classList.remove('hidden');
    } catch (e) {
        if (wrapper) wrapper.classList.add('hidden');
    }
}

export function updateURL() {
    let newPath = '/';
    if (state.currentTab === 'system') newPath = `/${state.currentDevice}/system`;
    else if (state.currentTab === 'history') newPath = `/${state.currentDevice}/history`;
    else if (state.currentTab === 'settings') newPath = `/${state.currentDevice}/settings`;
    else newPath = `/${state.currentDevice}`;
    history.pushState({ tab: state.currentTab, dev: state.currentDevice }, '', newPath);
}

export function switchDevice(dev, pushState = false) {
    state.currentDevice = dev;
    document.getElementById('device-select').value = dev;

    // 切换设备后历史缓存失效
    clearHistoryCache();

    const nodeInfo = state.availableNodes[dev] || {};
    const hasSystem = nodeInfo.type === 'local';
    const hasPump = nodeInfo.actuators && ('pump' in nodeInfo.actuators);
    const hasSettings = nodeInfo.actuators && ('pump' in nodeInfo.actuators || 'light' in nodeInfo.actuators) && !!localStorage.getItem(WATER_KEY);

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

    if ((state.currentTab === 'system' && !hasSystem) || (state.currentTab === 'settings' && !hasSettings)) {
        switchTab('environment', false, true);
    }

    if (state.currentHistType === 'watering' && !hasPump) {
        switchHistType('24h');
    }
    if (state.currentHistType === 'photos' && !(hasKey && hasCamera)) {
        switchHistType('24h');
    }

    if (pushState) updateURL();
    fetchAllData(false);
}

export function switchTab(tabName, pushState = true, skipFetch = false) {
    const nodeInfo = state.availableNodes[state.currentDevice] || {};
    const hasSystem = nodeInfo.type === 'local';
    const hasSettings = nodeInfo.actuators && ('pump' in nodeInfo.actuators || 'light' in nodeInfo.actuators) && !!localStorage.getItem(WATER_KEY);

    if (tabName === 'system' && !hasSystem) tabName = 'environment';
    if (tabName === 'settings' && !hasSettings) tabName = 'environment';

    state.currentTab = tabName;
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

export function switchHistType(type) {
    state.currentHistType = type;
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

export function checkMagicLink() {
    const urlParams = new URLSearchParams(window.location.search);
    let updated = false;
    if (urlParams.get('key')) { localStorage.setItem(STORAGE_KEY, urlParams.get('key')); updated = true; }
    if (urlParams.get('water_key')) { localStorage.setItem(WATER_KEY, urlParams.get('water_key')); updated = true; }
    if (updated) window.history.replaceState({}, document.title, window.location.pathname);
}

function parseURL() {
    const pathParts = window.location.pathname.split('/').filter(p => p);
    let dev = 'main';
    let tab = 'environment';
    if (pathParts.length > 0) {
        if (['system', 'history', 'settings'].includes(pathParts[0])) { tab = pathParts[0]; }
        else {
            dev = pathParts[0];
            if (pathParts.length > 1) tab = pathParts[1];
        }
    }
    return { dev, tab };
}

export function parseURLAndNavigate() {
    const { dev, tab } = parseURL();
    switchDevice(dev, false);
    switchTab(tab, false, true);
}

/** 浏览器前进/后退。updateURL() 一直在 pushState，但此前没人监听，
 *  结果是地址栏变了、界面不变。 */
export function initHistoryNav() {
    window.addEventListener('popstate', () => {
        const { dev, tab } = parseURL();
        // 先切视图再切设备：switchDevice 内部的 fetchAllData 会按新视图取数，
        // 反过来则会用旧视图取一遍、再切过去，多发一轮请求。
        // 两处都传 pushState=false，否则后退会再压一条历史记录。
        switchTab(tab, false, true);
        switchDevice(dev, false);
    });
}
