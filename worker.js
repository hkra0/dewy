import HTML_TEMPLATE from "./index.html";
export default {
    async fetch(request, env, ctx) {
        const PI_BASE_URL = env?.PI_BASE_URL;
        const PI_SECRET_TOKEN = env?.PI_SECRET_TOKEN;
        const VIEWER_MAGIC_KEY = env?.VIEWER_MAGIC_KEY;
        const WATER_MAGIC_KEY = env?.WATER_MAGIC_KEY;

        const url = new URL(request.url);
        const clientKey = request.headers.get("X-Viewer-Key");
        const requestedBy = request.headers.get("X-Requested-By");

        if (url.pathname.startsWith("/api/")) {
            if (!PI_BASE_URL) return new Response(JSON.stringify({ error: "Missing PI_BASE_URL config" }), { status: 500 });

            // Authorization
            if (url.pathname === "/api/monitor" || url.pathname === "/api/history" || url.pathname === "/api/nodes") {
                if (clientKey !== VIEWER_MAGIC_KEY && requestedBy !== "Robin-Web") return new Response("not found", { status: 404 });
            } else if (url.pathname === "/api/image") {
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

                if (!piResponse.ok) return new Response(url.pathname === "/api/image" ? "offline" : JSON.stringify({ error: "cannot connect to pi" }), { status: piResponse.status });

                const responseHeaders = new Headers(piResponse.headers);
                responseHeaders.set("Access-Control-Allow-Origin", "*");
                if (url.pathname === "/api/image") {
                    responseHeaders.set("Content-Type", "image/jpeg");
                    responseHeaders.set("Cache-Control", "no-store");
                    responseHeaders.set("Access-Control-Expose-Headers", "X-Image-Timestamp");
                } else {
                    responseHeaders.set("Content-Type", "application/json");
                }
                
                return new Response(piResponse.body, { status: piResponse.status, headers: responseHeaders });
            } catch (err) {
                return new Response(url.pathname === "/api/image" ? "error" : JSON.stringify({ error: "edge error" }), { status: 500 });
            }
        }

        if (!url.pathname.startsWith("/api/")) {
            return new Response(HTML_TEMPLATE, { headers: { "Content-Type": "text/html;charset=UTF-8" } });
        }

        return new Response("not found", { status: 404 });
    },
};
