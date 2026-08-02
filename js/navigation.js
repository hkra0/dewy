// 设备/标签页/历史子页的切换与 URL 同步。
import { state, STORAGE_KEY, WATER_KEY, getViewerKey, nodeCaps } from './state.js';
import { setLang } from './i18n.js';
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

/** 切换设备。
 *
 *  skipFetch 供启动路径使用：parseURLAndNavigate 里 switchDevice 与 switchTab
 *  会连着调用，若两边各自取一次数，首屏就会打两轮 /api/monitor，其中一轮还带
 *  live=true、白白让树莓派跑一次 rpicam。启动时由 app.js 统一取一次。
 */
export function switchDevice(dev, pushState = false, skipFetch = false) {
    state.currentDevice = dev;
    document.getElementById('device-select').value = dev;

    // 切换设备后历史缓存失效
    clearHistoryCache();

    const nodeInfo = state.availableNodes[dev] || {};
    const caps = nodeCaps(dev);
    const hasSystem = nodeInfo.type === 'local';
    const hasPump = caps.pump;
    const hasSettings = (caps.pump || caps.light) && !!localStorage.getItem(WATER_KEY);

    const hasKey = !!localStorage.getItem(STORAGE_KEY);
    const hasCamera = caps.camera;

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
    if (!skipFetch) fetchAllData(false);
}

export function switchTab(tabName, pushState = true, skipFetch = false) {
    const nodeInfo = state.availableNodes[state.currentDevice] || {};
    const caps = nodeCaps();
    const hasSystem = nodeInfo.type === 'local';
    const hasSettings = (caps.pump || caps.light) && !!localStorage.getItem(WATER_KEY);

    if (tabName === 'system' && !hasSystem) tabName = 'environment';
    if (tabName === 'settings' && !hasSettings) tabName = 'environment';

    state.currentTab = tabName;
    if (pushState) updateURL();

    // aria-current 与 .active 同步：视觉上的高亮对屏幕阅读器不存在，
    // 需要显式告诉它当前在哪个视图
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.remove('active');
        btn.removeAttribute('aria-current');
    });
    const activeTab = document.getElementById('tab-' + tabName);
    activeTab.classList.add('active');
    activeTab.setAttribute('aria-current', 'page');

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

/** 魔法链接：把密钥与语言偏好从 URL 收进 localStorage，然后把 URL 擦干净。
 *
 *  **密钥一律用片段**：`https://…/#key=xxx&water_key=yyy`
 *
 *  片段不随请求上行，所以密钥不会进 Cloudflare 的边缘访问日志，也不会出现在
 *  发往第三方 CDN/字体服务的 Referer 里。query 形式（?key=）两处都会泄漏，
 *  而 replaceState 只能擦掉地址栏，擦不掉已经写下的日志。
 *  仍然接受 ?key=，否则已经分享出去的旧链接会全部失效；但不要再用它生成新链接。
 *
 *  `lang` 不是机密，`?lang=zh` 与 `#lang=zh` 都行。它是界面语言的唯一覆盖入口——
 *  刻意不做界面控件，理由见 i18n.js。发一次链接即长期生效。
 *
 *  本函数必须在 applyTranslations() 之前调用（app.js 里就是这个顺序），
 *  这样语言在首屏渲染前就定下来了，不需要任何重绘。
 *
 *  返回是否消费到了参数，供 initMagicLinkNav 判断要不要重载。
 */
export function checkMagicLink() {
    const fromHash = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    const fromQuery = new URLSearchParams(window.location.search);
    const pick = (name) => fromHash.get(name) || fromQuery.get(name);

    let updated = false;
    const viewer = pick('key');
    const water = pick('water_key');
    const lang = pick('lang');
    if (viewer) { localStorage.setItem(STORAGE_KEY, viewer); updated = true; }
    if (water) { localStorage.setItem(WATER_KEY, water); updated = true; }
    // 即使 lang 与当前值相同（setLang 返回 false），也要把 URL 擦掉，
    // 否则参数会一直挂在地址栏上
    if (lang) { setLang(lang); updated = true; }

    // pathname 不含 search 也不含 hash，一次擦掉两者
    if (updated) window.history.replaceState({}, document.title, window.location.pathname);
    return updated;
}

/** 片段变化时重新消费魔法链接。
 *
 *  只改 hash 的导航**不会重新加载文档**，window.onload 也就不会再触发——
 *  用户已经开着页面时再点一条 `#key=` 链接，会什么都不发生。密钥挪进片段后
 *  这条路径才出现，query 形式不受影响（换 query 一定是整页导航）。
 *
 *  消费完直接 reload：此时参数已经落进 localStorage、URL 也擦干净了，
 *  重载会以新密钥走一遍正常启动流程，不必在这里复刻一遍初始化。
 *  replaceState 不触发 hashchange，所以不会自我循环。
 */
export function initMagicLinkNav() {
    window.addEventListener('hashchange', () => {
        if (checkMagicLink()) window.location.reload();
    });
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

/** 启动时按地址栏定位视图。两个 switch 都不取数——
 *  取数由 app.js 在导航就位后统一发起一次。 */
export function parseURLAndNavigate() {
    const { dev, tab } = parseURL();
    switchDevice(dev, false, true);
    switchTab(tab, false, true);
}

/** 浏览器前进/后退。updateURL() 在 pushState，没人监听 popstate 的话
 *  就是地址栏变了、界面不变。 */
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
