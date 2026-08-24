import HTML_TEMPLATE from "./index.html";
import CSS_TEMPLATE from "./style.css";
import JS_TEMPLATE from "./app.js";

// 前端已拆成 ES 模块，浏览器会按 import 路径逐个请求。
// Wrangler 的 Text 规则只能静态导入，所以新增模块时这里也要加一行，
// 否则该路径会落到 SPA 兜底分支、返回 HTML，浏览器报 MIME 类型错误。
import M_API from "./js/api.js";
import M_I18N from "./js/i18n.js";
import M_STATE from "./js/state.js";
import M_UI from "./js/ui.js";
import M_CDN from "./js/cdn.js";
import M_SETTINGS from "./js/settings.js";
import M_DASHBOARD from "./js/dashboard.js";
import M_HISTORY from "./js/history.js";
import M_CAMERA from "./js/camera.js";
import M_TIMELINE from "./js/timeline.js";
import M_NAVIGATION from "./js/navigation.js";
import M_REFRESH from "./js/refresh.js";
import M_METRICS from "./js/metrics.js";

const JS_MODULES = {
    "/app.js": JS_TEMPLATE,
    "/js/api.js": M_API,
    "/js/i18n.js": M_I18N,
    "/js/state.js": M_STATE,
    "/js/ui.js": M_UI,
    "/js/cdn.js": M_CDN,
    "/js/settings.js": M_SETTINGS,
    "/js/dashboard.js": M_DASHBOARD,
    "/js/history.js": M_HISTORY,
    "/js/camera.js": M_CAMERA,
    "/js/timeline.js": M_TIMELINE,
    "/js/navigation.js": M_NAVIGATION,
    "/js/refresh.js": M_REFRESH,
    "/js/metrics.js": M_METRICS,
};
// 静态资源随 Worker 一起部署，URL 里没有内容哈希，所以不能用长 max-age——
// 那样改完发上去，用户手里还是旧版本。改用 ETag：仍然每次回源校验，
// 但命中时返回 304 不带 body，省掉的正是体积大头。
//
// 所有资源共用同一个 ETag（它们本来就同一次部署），这样 index.html 与
// js/*.js 不可能各自缓存到不同版本。
//
// ETag 的来源优先用部署版本号（wrangler.toml 的 [version_metadata] 绑定）：
// "同一次部署" 正是这个 id 的语义，而且零计算。绑定缺失时（本地 dev、旧版
// wrangler）才退回内容哈希——那要逐字符扫全部资源（约 110KB → 十几万次循环），
// 所以必须懒计算，不能放在模块初始化里让每个 isolate 冷启动都付一次。
let _contentHash = null;
function contentHash() {
    if (_contentHash === null) {
        let h = 5381;
        for (const text of [HTML_TEMPLATE, CSS_TEMPLATE, ...Object.values(JS_MODULES)]) {
            for (let i = 0; i < text.length; i++) h = (h * 33 ^ text.charCodeAt(i)) >>> 0;
        }
        _contentHash = h.toString(36);
    }
    return _contentHash;
}

let _etag = null;
function getETag(env) {
    if (_etag === null) {
        _etag = `"${env?.CF_VERSION_METADATA?.id || contentHash()}"`;
    }
    return _etag;
}

// 应用在所有响应上的基础安全头。
//
// nosniff 对 js/json 最要紧：没有它，浏览器可能把响应按嗅探出的类型执行。
// no-referrer 同时兜住魔法链接——即使有人还在用旧的 ?key= 格式，
// 密钥也不会随 Referer 漏给第三方 CDN 或字体服务。
const BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
};

// 只对 HTML 文档生效（CSP 是文档级策略，挂在 json/图片上没有意义）。
//
// script-src 保留 'unsafe-inline'：index.html 与 dashboard.js 生成的 HTML 里
// 用的是内联 onclick，这是 AGENTS.md 第五节明确的约定，不是疏漏。
// 因此这条 CSP 挡不住注入的内联脚本，它挡的是**主机**——注入的外部脚本加载不了，
// connect-src 'self' 也让数据无法外发到任意域名。这是在不推翻既有约定前提下
// 能拿到的那一半，且是更值钱的那一半。
//
// script-src 的三个 CDN 必须与 js/cdn.js 的 CHART_CDNS / GIFSHOT_CDNS 保持一致，
// 改那边记得同步这里，否则库会被 CSP 拦掉、图表和 GIF 导出静默失效。
// worker-src blob: 是给 gifshot 的（它的 numWorkers 从 blob URL 起 worker）。
// img-src 的 blob:/data: 分别对应 createObjectURL 的图片与 canvas 水印帧。
const CSP = [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com https://cdnjs.cloudflare.com",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' blob: data:",
    "media-src 'self' blob: data:",
    "connect-src 'self'",
    "worker-src blob:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
].join("; ");

function staticResponse(request, env, body, contentType) {
    const etag = getETag(env);
    const headers = {
        ...BASE_SECURITY_HEADERS,
        "ETag": etag,
        "Cache-Control": "public, max-age=0, must-revalidate",
    };
    if (contentType.startsWith("text/html")) headers["Content-Security-Policy"] = CSP;

    if (request.headers.get("If-None-Match") === etag) {
        return new Response(null, { status: 304, headers });
    }
    return new Response(body, { headers: { ...headers, "Content-Type": contentType } });
}

export default {
    async fetch(request, env, ctx) {
        const PI_BASE_URL = env?.PI_BASE_URL;
        const PI_SECRET_TOKEN = env?.PI_SECRET_TOKEN;
        const VIEWER_MAGIC_KEY = env?.VIEWER_MAGIC_KEY;
        const WATER_MAGIC_KEY = env?.WATER_MAGIC_KEY;

        const url = new URL(request.url);
        const clientKey = request.headers.get("X-Viewer-Key");

        if (url.pathname.startsWith("/api/")) {
            // 鉴权必须排在任何配置检查之前。反过来的话，未授权的人能靠
            // 500 与 404 的差别推断出"这里确实有个 Worker，只是没配好"，
            // 与只读端点一律回 404、不暴露端点存在的原则相悖。
            //
            // Authorization
            // 所有只读端点一律要求 X-Viewer-Key。不要给它加"标识头即凭证"式的
            // 旁路（如 X-Requested-By 之类固定字符串）——写死在前端的非机密值
            // 等同于无鉴权。
            if (url.pathname === "/api/monitor" || url.pathname === "/api/history" || url.pathname === "/api/nodes"
                || url.pathname === "/api/metrics"
                || url.pathname === "/api/image" || url.pathname === "/api/photos" || url.pathname.startsWith("/api/photos/")) {
                if (clientKey !== VIEWER_MAGIC_KEY) return new Response("not found", { status: 404, headers: BASE_SECURITY_HEADERS });
            } else if (url.pathname === "/api/water" || url.pathname === "/api/water/emergency-stop"
                || url.pathname === "/api/light" || url.pathname === "/api/config"
                || url.pathname === "/api/photo/retake") {
                // 重拍走 water key：它会驱动相机与补光灯，属于写操作。
                // 注意路径不在 /api/photos/ 前缀下，否则会先被上面那条 viewer key
                // 分支接走，变成只读鉴权。
                if (url.pathname !== "/api/config" && request.method !== "POST") return new Response("method not allowed", { status: 405, headers: BASE_SECURITY_HEADERS });
                const clientWaterKey = request.headers.get("x-water-key");
                if (clientWaterKey !== WATER_MAGIC_KEY) {
                    return new Response(JSON.stringify({ error: "invalid key" }), { status: 403, headers: { ...BASE_SECURITY_HEADERS, "Content-Type": "application/json" } });
                }
            } else {
                return new Response("not found", { status: 404, headers: BASE_SECURITY_HEADERS });
            }

            // 走到这里说明已经通过鉴权，此时再暴露配置错误是安全的，
            // 而且对排查部署问题有用。
            if (!PI_BASE_URL) return new Response(JSON.stringify({ error: "Missing PI_BASE_URL config" }), { status: 500, headers: BASE_SECURITY_HEADERS });

            const targetURL = PI_BASE_URL + url.pathname + url.search;
            const newHeaders = new Headers();
            newHeaders.set("X-BFF-To-Pi-Token", PI_SECRET_TOKEN || "");
            if (url.pathname === "/api/monitor" || url.pathname === "/api/history" || url.pathname === "/api/metrics") {
                newHeaders.set("Accept", "application/json");
            }
            if (request.headers.has("Content-Type")) {
                newHeaders.set("Content-Type", request.headers.get("Content-Type"));
            }
            
            try {
                const piResponse = await fetch(targetURL, {
                    method: request.method,
                    headers: newHeaders,
                    body: request.method === "POST" ? request.body : undefined
                });

                const isImageEndpoint = url.pathname === "/api/image";
                const isExportDownload = url.pathname === "/api/photos/export/download";
                const isPhotoFile = url.pathname.startsWith("/api/photos/") && url.pathname !== "/api/photos/export" && url.pathname !== "/api/photos/export/status" && !isExportDownload;

                // 304 必须先于 !ok 判断：Response.ok 只认 2xx，落到下面就会被
                // 当成故障、回一个带 "offline" body 的 304——而 304 本就不允许
                // 带 body。/api/image?since= 靠它省掉重复下载。
                if (piResponse.status === 304) {
                    return new Response(null, { status: 304, headers: { ...BASE_SECURITY_HEADERS, "Cache-Control": "no-store" } });
                }

                if (!piResponse.ok) {
                    if (isImageEndpoint || isPhotoFile) {
                        return new Response("offline", { status: piResponse.status, headers: BASE_SECURITY_HEADERS });
                    }
                    const errBody = await piResponse.text();
                    return new Response(errBody || JSON.stringify({ error: "cannot connect to pi" }), {
                        status: piResponse.status,
                        headers: { ...BASE_SECURITY_HEADERS, "Content-Type": piResponse.headers.get("Content-Type") || "application/json" },
                    });
                }

                // 前端由同一个 Worker 下发，与 API 同源，所以 CORS 头本来就用不上：
                // 而且鉴权走的是自定义头（X-Viewer-Key / x-water-key），跨源调用必须
                // 先过预检，而这里根本没有 OPTIONS 处理器——ACAO:* 是一行死代码。
                // Expose-Headers 同理：同源 JS 本来就能读到全部响应头。
                const responseHeaders = new Headers(BASE_SECURITY_HEADERS);
                if (isImageEndpoint) {
                    responseHeaders.set("Content-Type", "image/jpeg");
                    responseHeaders.set("Cache-Control", "no-store");
                    const imgTs = piResponse.headers.get("X-Image-Timestamp");
                    if (imgTs) responseHeaders.set("X-Image-Timestamp", imgTs);
                } else if (isPhotoFile || isExportDownload) {
                    const piCt = piResponse.headers.get("Content-Type") || (isExportDownload ? "video/mp4" : "image/jpeg");
                    const piCc = piResponse.headers.get("Cache-Control") || (isExportDownload ? "no-cache" : "public, max-age=86400");
                    responseHeaders.set("Content-Type", piCt);
                    responseHeaders.set("Cache-Control", piCc);
                    const piCd = piResponse.headers.get("Content-Disposition");
                    if (piCd) responseHeaders.set("Content-Disposition", piCd);
                } else {
                    responseHeaders.set("Content-Type", "application/json");
                    responseHeaders.set("Vary", "Accept-Encoding");
                }
                
                return new Response(piResponse.body, { status: piResponse.status, headers: responseHeaders });
            } catch (err) {
                return new Response(url.pathname === "/api/image" ? "error" : JSON.stringify({ error: "edge error" }), { status: 500, headers: BASE_SECURITY_HEADERS });
            }
        }

        
        if (url.pathname === "/style.css") {
            return staticResponse(request, env, CSS_TEMPLATE, "text/css;charset=UTF-8");
        }
        if (JS_MODULES[url.pathname] !== undefined) {
            return staticResponse(request, env, JS_MODULES[url.pathname], "application/javascript;charset=UTF-8");
        }
        // 未注册的 /js/ 路径必须 404，不能落到下面的 SPA 兜底返回 HTML——
        // 那样浏览器只会报难以定位的 MIME 错误
        if (url.pathname.startsWith("/js/")) {
            return new Response("not found", { status: 404, headers: BASE_SECURITY_HEADERS });
        }
        if (!url.pathname.startsWith("/api/")) {
            const INLINED_HTML = HTML_TEMPLATE.replace('<link rel="stylesheet" href="/style.css">', `<style>\n${CSS_TEMPLATE}\n</style>`);
            return staticResponse(request, env, INLINED_HTML, "text/html;charset=UTF-8");
        }

        return new Response("not found", { status: 404, headers: BASE_SECURITY_HEADERS });
    },
};
