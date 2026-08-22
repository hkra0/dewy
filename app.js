// dewy 前端入口。
//
// 以 ES 模块加载（index.html 里是 <script type="module" src="/app.js">）。
// 模块作用域不是全局作用域，而 index.html 与 dashboard.js 生成的 HTML 里
// 用了 onclick="xxx()" 这类内联处理器——它们只认 window 上的函数，
// 所以下面必须把用到的函数显式挂到 window，缺一个就是运行时报错。
//
// 新增内联处理器时记得同步这里。

import { applyTranslations, t } from './js/i18n.js';
import {
    initNodes,
    switchTab,
    switchDevice,
    switchHistType,
    checkMagicLink,
    initMagicLinkNav,
    saveConfigAndRefresh,
    parseURLAndNavigate,
    initHistoryNav,
} from './js/navigation.js';
import { triggerWatering, toggleLight, toggleSoilView } from './js/dashboard.js';
import { fetchHDImage, closeHD, initModalDismiss } from './js/camera.js';
import { initKeyboardActivation } from './js/ui.js';
import { toggleLightMode, toggleSettingsGroup, retakeTodayPhoto } from './js/settings.js';
import {
    toggleTimelinePlay,
    seekTimeline,
    navTimeline,
    setTimelineSpeed,
    exportTimelineGIF,
    viewFullPhoto,
} from './js/timeline.js';
import { fetchAllData } from './js/refresh.js';

// —— 供 index.html 的内联事件处理器调用 ——
Object.assign(window, {
    switchTab,
    switchDevice,
    switchHistType,
    toggleLightMode,
    toggleSettingsGroup,
    saveConfigAndRefresh,   // 保存 + 重算显隐（见 navigation.js），不是裸的 saveConfig
    retakeTodayPhoto,
    triggerWatering,
    toggleLight,          // 由 dashboard.js 生成的卡片 HTML 内联调用
    toggleSoilView,       // 点击土壤湿度卡片翻转百分比/原始 ADC
    fetchAllData,
    fetchHDImage,
    closeHD,
    toggleTimelinePlay,
    seekTimeline,
    navTimeline,
    setTimelineSpeed,
    exportTimelineGIF,
    viewFullPhoto,
});

const REFRESH_INTERVAL_MS = 30000;

// initNodes 的失败原因 → 文案。别在这里把它们合并成一句"加载失败"：
// 这四种情况要做的事完全不同（等网络 / 看树莓派 / 换链接 / 报 bug），
// 用户唯一能从界面上得到的线索就是这句话。
const BOOT_ERROR_KEYS = {
    network: 'boot_err_network',
    pi: 'boot_err_pi',
    unauthorized: 'boot_err_key',
    http: 'boot_err_http',
};

/** 拆掉首屏加载层，露出主界面。 */
function revealApp() {
    document.getElementById('app-boot')?.remove();
    document.getElementById('app-root')?.classList.remove('hidden');
}

/** 把加载层切到报错态：停下转圈、给出人话、给一个能点的出口。 */
function showBootError(result) {
    const boot = document.getElementById('app-boot');
    if (!boot) { revealApp(); return; }

    boot.classList.add('is-error');
    document.getElementById('boot-spinner').classList.add('hidden');

    const textEl = document.getElementById('boot-text');
    // 去掉 data-i18n：这句是运行时算出来的，留着的话下一次
    // applyTranslations() 会把它改回 "加载中..."。
    textEl.removeAttribute('data-i18n');
    textEl.innerText = t(BOOT_ERROR_KEYS[result.reason] || 'boot_err_http', { status: result.status ?? '' });

    document.getElementById('boot-actions').classList.remove('hidden');
}

/** 收起报错态，回到转圈。重试前调用。 */
function showBootLoading() {
    const boot = document.getElementById('app-boot');
    if (!boot) return;
    boot.classList.remove('is-error');
    document.getElementById('boot-spinner').classList.remove('hidden');
    document.getElementById('boot-actions').classList.add('hidden');
    document.getElementById('boot-text').innerText = t('booting');
}

let entered = false;

/** 进主界面。重试与"仍然进入"都可能走到这里，所以要防重入——
 *  否则轮询定时器会被装第二次。 */
function enterApp() {
    if (entered) return;
    entered = true;

    // parseURLAndNavigate 只摆好视图、不取数，首屏的唯一一轮请求在下面发出。
    // 两边都取的话首屏会打两轮 /api/monitor，且其中一轮带 live=true，
    // 等于每次打开页面都让树莓派多跑一次 rpicam。
    parseURLAndNavigate();
    revealApp();

    initHistoryNav();
    initKeyboardActivation();
    initModalDismiss();
    fetchAllData(true);

    // 页面不可见时不轮询，省流量也省树莓派的电
    setInterval(() => {
        if (document.visibilityState === 'visible') {
            fetchAllData(false);
        }
    }, REFRESH_INTERVAL_MS);
}

/** 取节点列表，成功就进界面，失败就停在加载层上报错。
 *
 *  节点列表决定哪些标签页与卡片存在，拿到之前渲染主界面只会先给用户看一份
 *  错的、随后被改写的界面；而树莓派连不上时，那份界面还会是空的——
 *  与其让用户对着空壳猜发生了什么，不如把原因写在加载层上。 */
async function boot() {
    let result;
    try {
        result = await initNodes();
    } catch (e) {
        // initNodes 自己已经兜住了网络与解析错误，这里只是最后一道保险，
        // 免得任何意外把页面永远钉在转圈上。
        result = { ok: false, reason: 'network' };
    }

    // 无密钥的访客本来就看不到设备列表，这是设计好的路径，不是故障。
    if (result.ok || result.reason === 'no-key') enterApp();
    else showBootError(result);
}

window.onload = () => {
    checkMagicLink();
    applyTranslations();

    // 必须在 boot() 之外装：密钥失效时用户停在报错层上，此时点一条新的
    // `#key=` 链接（只改 hash、不重载文档）得靠这个监听器才会生效——
    // 而报错文案让用户去做的正是这件事。
    initMagicLinkNav();

    document.getElementById('boot-retry-btn').onclick = () => { showBootLoading(); boot(); };
    document.getElementById('boot-skip-btn').onclick = () => enterApp();

    boot();
};
