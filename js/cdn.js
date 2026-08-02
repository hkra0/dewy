// 按需加载第三方库。无依赖。
//
// Chart.js 与 gifshot 合计约 240KB，且都只在特定视图才用得上——写进
// index.html 的 <head> 会让每个访客首屏都下载一遍，哪怕从不打开历史或
// 照片页。这里在进入对应视图时才加载，并保留多个 CDN 兜底。

const loaded = new Map();   // url -> Promise<boolean>

function loadScript(url) {
    if (!loaded.has(url)) {
        loaded.set(url, new Promise((resolve) => {
            const script = document.createElement('script');
            script.src = url;
            script.onload = () => resolve(true);
            script.onerror = () => resolve(false);
            document.head.appendChild(script);
        }));
    }
    return loaded.get(url);
}

/**
 * 依次尝试多个 CDN，直到 isReady() 为真。
 * 同一个库并发调用只会真正加载一次（同 url 的 Promise 被复用）。
 */
export async function ensureLib(isReady, urls) {
    if (isReady()) return true;
    for (const url of urls) {
        const ok = await loadScript(url);
        if (ok && isReady()) return true;
        console.warn(`failed to load library from ${url}`);
    }
    return isReady();
}

export const CHART_CDNS = [
    'https://cdn.jsdelivr.net/npm/chart.js',
    'https://unpkg.com/chart.js@4/dist/chart.umd.js',
    'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js',
];

export const GIFSHOT_CDNS = [
    'https://cdnjs.cloudflare.com/ajax/libs/gifshot/0.3.2/gifshot.min.js',
    'https://unpkg.com/gifshot@0.3.3/build/gifshot.min.js',
    'https://cdn.jsdelivr.net/npm/gifshot@0.3.3/build/gifshot.min.js',
];

export const ensureChart = () => ensureLib(() => typeof Chart !== 'undefined', CHART_CDNS);
export const ensureGifshot = () => ensureLib(() => typeof gifshot !== 'undefined', GIFSHOT_CDNS);
