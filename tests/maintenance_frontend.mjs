// Run: node tests/maintenance_frontend.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Exercise actual Worker auth/proxy code without Wrangler or a network.
const source = fs.readFileSync(new URL('../worker.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?$/gm, '').replace('export default', 'globalThis.worker =');
const constants = [...source.matchAll(/:\s*(M_[A-Z0-9_]+|JS_TEMPLATE),/g)].map(x => x[1]);
let forwarded = 0;
const workerContext = vm.createContext({
    Response, Request, Headers, URL, HTML_TEMPLATE: '', CSS_TEMPLATE: '',
    ...Object.fromEntries(constants.map(name => [name, ''])),
    fetch: async (_, init) => {
        forwarded++;
        assert.equal(init.headers.get('X-BFF-To-Pi-Token'), 'pi-token');
        return Response.json({ online: true });
    },
});
vm.runInContext(source, workerContext);
const env = { PI_BASE_URL: 'https://pi.test', PI_SECRET_TOKEN: 'pi-token', VIEWER_MAGIC_KEY: 'viewer', WATER_MAGIC_KEY: 'water' };
for (const path of ['/api/maintenance/aqua', '/api/maintenance/aqua/firmware']) {
    const method = path.endsWith('/firmware') ? 'POST' : 'GET';
    for (const headers of [{}, { 'X-Viewer-Key': 'viewer' }, { 'x-water-key': 'wrong' }]) {
        const res = await workerContext.worker.fetch(new Request('https://worker.test' + path, { method, headers }), env, {});
        assert.equal(res.status, 403);
    }
    const response = await workerContext.worker.fetch(new Request('https://worker.test' + path, { method, headers: { 'x-water-key': 'water' } }), env, {});
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
}
assert.equal(forwarded, 2);

// A response for the previous node must never overwrite the new node's console.
const elements = new Map();
function element(id) {
    if (!elements.has(id)) elements.set(id, { textContent: '', value: '', disabled: false,
        classList: { toggle() {} }, scrollTop: 0, clientHeight: 10, scrollHeight: 10 });
    return elements.get(id);
}
let resolveOld;
const context = vm.createContext({
    document: { getElementById: element }, state: { currentTab: 'settings', currentDevice: 'aqua' },
    nodeCaps: () => ({ maintenance: true }), getWaterKey: () => 'water', t: key => key,
    setTimeout() {}, console, Date,
    apiWater: path => path.includes('/aqua?') ? new Promise(resolve => { resolveOld = resolve; }) :
        Promise.resolve({ ok: true, json: async () => ({ online: true, device: { board: 'other' }, job: null, cursor: 1,
            logs: [{ time: 1, text: '<script>untrusted log</script>' }] }) }),
});
vm.runInContext(fs.readFileSync(new URL('../js/maintenance.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?$/gm, '').replace(/\bexport /g, ''), context);
vm.runInContext('refreshMaintenance()', context);
context.state.currentDevice = 'other';
vm.runInContext('refreshMaintenance()', context);
await new Promise(resolve => setImmediate(resolve));
resolveOld({ ok: true, json: async () => ({ device: { board: 'OLD' }, logs: [] }) });
await new Promise(resolve => setImmediate(resolve));
assert.match(element('maintenance-status').textContent, /other/);
assert.doesNotMatch(element('maintenance-status').textContent, /OLD/);
assert.match(element('maintenance-log').textContent, /<script>untrusted log<\/script>/);
context.failed = { device: { update_result: { status: 'rolled_back', code: 'main_loop_stalled' } },
    job: { status: 'failed', error_code: 'rolled_back', error: 'Old firmware restored', device_error: 'main_loop_stalled' } };
vm.runInContext("renderFeedback(failed, 'other')", context);
assert.match(element('maintenance-feedback').textContent, /maint_error_rolled_back/);
assert.match(element('maintenance-feedback').textContent, /maint_reason_main_loop_stalled/);
// A fresh poll still shows the durable device failure after Pi task state was lost.
context.failed.job = null;
vm.runInContext("renderFeedback(failed, 'other')", context);
assert.match(element('maintenance-feedback').textContent, /maint_error_rolled_back/);
vm.runInContext("uploadErrors.set('other', 'persistent upload error'); renderFeedback({ device: {} }, 'other')", context);
assert.equal(element('maintenance-feedback').textContent, 'persistent upload error');
console.log('PASS: admin auth, node-switch race, plain-text logs, rollback reason, durable upload errors');
