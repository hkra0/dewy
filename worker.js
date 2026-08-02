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
import M_SETTINGS from "./js/settings.js";
import M_DASHBOARD from "./js/dashboard.js";
import M_HISTORY from "./js/history.js";
import M_CAMERA from "./js/camera.js";
import M_TIMELINE from "./js/timeline.js";
import M_NAVIGATION from "./js/navigation.js";
import M_REFRESH from "./js/refresh.js";

const JS_MODULES = {
    "/app.js": JS_TEMPLATE,
    "/js/api.js": M_API,
    "/js/i18n.js": M_I18N,
    "/js/state.js": M_STATE,
    "/js/ui.js": M_UI,
    "/js/settings.js": M_SETTINGS,
    "/js/dashboard.js": M_DASHBOARD,
    "/js/history.js": M_HISTORY,
    "/js/camera.js": M_CAMERA,
    "/js/timeline.js": M_TIMELINE,
    "/js/navigation.js": M_NAVIGATION,
    "/js/refresh.js": M_REFRESH,
};
export default {
    async fetch(request, env, ctx) {
        const PI_BASE_URL = env?.PI_BASE_URL;
        const PI_SECRET_TOKEN = env?.PI_SECRET_TOKEN;
        const VIEWER_MAGIC_KEY = env?.VIEWER_MAGIC_KEY;
        const WATER_MAGIC_KEY = env?.WATER_MAGIC_KEY;

        const url = new URL(request.url);
        const clientKey = request.headers.get("X-Viewer-Key");

        if (url.pathname.startsWith("/api/")) {
            if (!PI_BASE_URL) return new Response(JSON.stringify({ error: "Missing PI_BASE_URL config" }), { status: 500 });

            // Authorization
            // 所有只读端点一律要求 X-Viewer-Key。
            // 注意：这里曾有 `|| X-Requested-By === "Robin-Web"` 的旁路，
            // 但该头是写死在前端的非机密字符串，等同于无鉴权，已移除。
            if (url.pathname === "/api/monitor" || url.pathname === "/api/history" || url.pathname === "/api/nodes"
                || url.pathname === "/api/image" || url.pathname === "/api/photos" || url.pathname.startsWith("/api/photos/")) {
                if (clientKey !== VIEWER_MAGIC_KEY) return new Response("not found", { status: 404 });
            } else if (url.pathname === "/api/water" || url.pathname === "/api/light" || url.pathname === "/api/config") {
                if (url.pathname !== "/api/config" && request.method !== "POST") return new Response("method not allowed", { status: 405 });
                const clientWaterKey = request.headers.get("x-water-key");
                if (clientWaterKey !== WATER_MAGIC_KEY) {
                    return new Response(JSON.stringify({ error: "invalid key" }), { status: 403, headers: { 'Content-Type': 'application/json' } });
                }
            } else {
                return new Response("not found", { status: 404 });
            }

            const targetURL = PI_BASE_URL + url.pathname + url.search;
            const newHeaders = new Headers();
            newHeaders.set("X-BFF-To-Pi-Token", PI_SECRET_TOKEN || "");
            if (url.pathname === "/api/monitor" || url.pathname === "/api/history") {
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
                const isPhotoFile = url.pathname.startsWith("/api/photos/");
                if (!piResponse.ok) return new Response((isImageEndpoint || isPhotoFile) ? "offline" : JSON.stringify({ error: "cannot connect to pi" }), { status: piResponse.status });

                const responseHeaders = new Headers();
                responseHeaders.set("Access-Control-Allow-Origin", "*");
                if (isImageEndpoint) {
                    responseHeaders.set("Content-Type", "image/jpeg");
                    responseHeaders.set("Cache-Control", "no-store");
                    responseHeaders.set("Access-Control-Expose-Headers", "X-Image-Timestamp");
                    const imgTs = piResponse.headers.get("X-Image-Timestamp");
                    if (imgTs) responseHeaders.set("X-Image-Timestamp", imgTs);
                } else if (isPhotoFile) {
                    const piCt = piResponse.headers.get("Content-Type") || "image/jpeg";
                    const piCc = piResponse.headers.get("Cache-Control") || "public, max-age=86400";
                    responseHeaders.set("Content-Type", piCt);
                    responseHeaders.set("Cache-Control", piCc);
                } else {
                    responseHeaders.set("Content-Type", "application/json");
                    responseHeaders.set("Vary", "Accept-Encoding");
                }
                
                return new Response(piResponse.body, { status: piResponse.status, headers: responseHeaders });
            } catch (err) {
                return new Response(url.pathname === "/api/image" ? "error" : JSON.stringify({ error: "edge error" }), { status: 500 });
            }
        }

        
        if (url.pathname === "/style.css") {
            return new Response(CSS_TEMPLATE, { headers: { "Content-Type": "text/css;charset=UTF-8" } });
        }
        if (JS_MODULES[url.pathname] !== undefined) {
            return new Response(JS_MODULES[url.pathname], {
                headers: { "Content-Type": "application/javascript;charset=UTF-8" },
            });
        }
        // 未注册的 /js/ 路径必须 404，不能落到下面的 SPA 兜底返回 HTML——
        // 那样浏览器只会报难以定位的 MIME 错误
        if (url.pathname.startsWith("/js/")) {
            return new Response("not found", { status: 404 });
        }
        if (!url.pathname.startsWith("/api/")) {
            return new Response(HTML_TEMPLATE, { headers: { "Content-Type": "text/html;charset=UTF-8" } });
        }

        return new Response("not found", { status: 404 });
    },
};
