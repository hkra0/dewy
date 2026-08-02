// dewy 前端入口。
//
// 以 ES 模块加载（index.html 里是 <script type="module" src="/app.js">）。
// 模块作用域不是全局作用域，而 index.html 与 dashboard.js 生成的 HTML 里
// 用了 onclick="xxx()" 这类内联处理器——它们只认 window 上的函数，
// 所以下面必须把用到的函数显式挂到 window，缺一个就是运行时报错。
//
// 新增内联处理器时记得同步这里。

import { applyTranslations } from './js/i18n.js';
import {
    initNodes,
    switchTab,
    switchDevice,
    switchHistType,
    checkMagicLink,
    initMagicLinkNav,
    parseURLAndNavigate,
    initHistoryNav,
} from './js/navigation.js';
import { triggerWatering, toggleLight } from './js/dashboard.js';
import { fetchHDImage, closeHD, initModalDismiss } from './js/camera.js';
import { initKeyboardActivation } from './js/ui.js';
import { saveConfig, toggleLightMode, retakeTodayPhoto } from './js/settings.js';
import {
    toggleTimelinePlay,
    seekTimeline,
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
    saveConfig,
    retakeTodayPhoto,
    triggerWatering,
    toggleLight,          // 由 dashboard.js 生成的卡片 HTML 内联调用
    fetchAllData,
    fetchHDImage,
    closeHD,
    toggleTimelinePlay,
    seekTimeline,
    setTimelineSpeed,
    exportTimelineGIF,
    viewFullPhoto,
});

const REFRESH_INTERVAL_MS = 30000;

window.onload = async () => {
    checkMagicLink();
    applyTranslations();
    await initNodes();
    // parseURLAndNavigate 只摆好视图、不取数，首屏的唯一一轮请求在这里发出。
    // 两边都取的话首屏会打两轮 /api/monitor，且其中一轮带 live=true，
    // 等于每次打开页面都让树莓派多跑一次 rpicam。
    parseURLAndNavigate();
    initHistoryNav();
    initMagicLinkNav();
    initKeyboardActivation();
    initModalDismiss();
    fetchAllData(true);

    // 页面不可见时不轮询，省流量也省树莓派的电
    setInterval(() => {
        if (document.visibilityState === 'visible') {
            fetchAllData(false);
        }
    }, REFRESH_INTERVAL_MS);
};
