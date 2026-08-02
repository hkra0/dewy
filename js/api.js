// 统一的 API 调用封装：鉴权头只在这里注入。
//
// 两把钥匙互相独立，端点决定用哪一把（见 agent.md「七、鉴权」）：
//   - 只读端点 /api/monitor|history|nodes|image|photos*  → X-Viewer-Key，不匹配 404
//   - 高危端点 /api/water|light|config                   → x-water-key，不匹配 403
// 业务模块一律走 apiGet / apiWater，不要再自己拼 headers。
import { getViewerKey, getWaterKey } from './state.js';

// 合并调用方自带的 header，鉴权头优先，不允许被覆盖。
function withAuth(init, name, value) {
    return { ...init, headers: { ...(init.headers || {}), [name]: value } };
}

/** 只读端点。返回原始 Response，由调用方决定 json() / blob()。 */
export function apiGet(path, init = {}) {
    return fetch(path, withAuth(init, 'X-Viewer-Key', getViewerKey()));
}

/** 高危端点（浇水 / 切灯 / 配置读写）。 */
export function apiWater(path, init = {}) {
    return fetch(path, withAuth(init, 'x-water-key', getWaterKey() || ''));
}

/** 高危端点的 JSON POST。 */
export function apiWaterPost(path, body) {
    const init = { method: 'POST' };
    if (body !== undefined) {
        init.headers = { 'Content-Type': 'application/json' };
        init.body = JSON.stringify(body);
    }
    return apiWater(path, init);
}

/** 缓存穿透用的时间戳参数，拼在已有 query 之后。 */
export function bust(path) {
    return path + (path.includes('?') ? '&' : '?') + 't=' + Date.now();
}
