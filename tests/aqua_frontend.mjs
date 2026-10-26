// Run with: node tests/aqua_frontend.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const elements = new Map();
function element(id) {
    if (!elements.has(id)) elements.set(id, {
        value: '7', checked: false, innerText: 'Save', innerHTML: '', style: {},
        classList: { add() {}, remove() {}, toggle() {} },
    });
    return elements.get(id);
}
let sent;
const context = vm.createContext({
    console, setTimeout() {}, clearTimeout() {},
    navigator: { language: 'en' }, localStorage: { getItem() {}, setItem() {} },
    document: { getElementById: element },
    state: { currentDevice: 'tank', currentHistType: '24h', availableNodes: { tank: { settings_schema: {
        enabled: { type: 'boolean' }, mode: { type: 'select', options: ['daily', 'temperature_accumulation'] },
        rate: { type: 'number' }, name: { type: 'text' },
    } } } },
    getWaterKey: () => 'fixture', getViewerKey: () => 'fixture', nodeCaps: () => ({}),
    showToast() {}, switchHistType() {},
    escapeHtml: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
    apiWaterPost: async (path, body) => { sent = body; return { ok: true, json: async () => ({}) }; },
});
function load(path) {
    const source = fs.readFileSync(new URL('../' + path, import.meta.url), 'utf8')
        .replace(/^import .*;\r?$/gm, '').replace(/^export \{.*\};\r?$/gm, '').replace(/\bexport /g, '');
    vm.runInContext(source, context, { filename: path });
}
load('js/i18n.js'); load('js/ui.js'); load('js/metrics.js'); load('js/settings.js'); load('js/dashboard.js');
context.showToast = () => {};   // ui.js 的真实实现要操作 DOM，测试里只需要它的 fmtNum / escapeHtml
element('cfg-ns-enabled').checked = true;
element('cfg-ns-mode').value = 'temperature_accumulation';
element('cfg-ns-rate').value = '2.25'; element('cfg-ns-name').value = 'Tank';
vm.runInContext('loadedConfig = { node_settings: { tank: { hidden_parameter: 9 } } }', context);
assert.equal(await vm.runInContext('saveConfig()', context), true);
assert.equal(sent.node_settings.tank.enabled, true);
assert.equal(sent.node_settings.tank.mode, 'temperature_accumulation');
assert.equal(sent.node_settings.tank.rate, 2.25);
assert.equal(sent.node_settings.tank.hidden_parameter, 9);

for (const lang of ['en', 'zh']) {
    vm.runInContext(`setLang('${lang}')`, context);
    context.fixture = { water_temp: null, water_temp_valid: false, feeding_state: 'probe_fault',
        fed: 0, feeding_score: 54, next_prompt_date: 20270101, data_version: 2, received_at: 1,
        alarms: [{ kind: 'high', acknowledged: true, silenced: true }] };
    vm.runInContext('renderDynamicCards(fixture, {})', context);
    const html = element('dynamic-cards').innerHTML;
    assert.match(html, /54%/);
    assert.doesNotMatch(html, /2027-01-01/);
    assert.doesNotMatch(html, /data version|received at|feeding score|feeding_probe_fault|alarm_high/);
    assert.match(html, lang === 'zh' ? /探头异常/ : /Probe unavailable/);
    assert.match(html, lang === 'zh' ? /已确认/ : /Acknowledged/);
}
context.fixture = { fed: 1, fed_time: '07:30' };
vm.runInContext('renderDynamicCards(fixture, {})', context);
assert.match(element('dynamic-cards').innerHTML, /已喂食/);

// 正常状态与主节点卡片同一精度、同样简洁：一位小数，无样本年龄，已喂食只显示时刻
const day = offset => {
    const d = new Date(); d.setDate(d.getDate() - offset);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};
context.fixture = { water_temp: 18.9375, water_temp_valid: true, water_temp_age: 1, time_valid: true,
    temperature: 19.86675, humidity: 61.38166, pressure: 969.3318, alarms: [],
    feeding_state: 'fed', fed: 1, fed_time: `${day(0)} 07:54`, next_prompt_date: 20261027 };
vm.runInContext('renderDynamicCards(fixture, {})', context);
{
    const html = element('dynamic-cards').innerHTML;
    for (const v of ['18.9 ℃', '19.9 ℃', '61.4 %', '969.3 hPa']) assert.ok(html.includes(v), v);
    assert.doesNotMatch(html, /18\.93|61\.38|969\.33|样本年龄|20261027|今日/);
    assert.match(html, />已喂食</);
    assert.match(html, /今天 07:54/);
}

// 积温模式：隔天还没到阈值——主值"暂不用喂"，副标题是距上次多久 + 百分比进度
context.fixture = { feeding_state: 'waiting', fed: 0, fed_time: `${day(3)} 08:10`,
    feeding_score: 60, feeding_threshold: 120 };
vm.runInContext('renderDynamicCards(fixture, {})', context);
{
    const html = element('dynamic-cards').innerHTML;
    assert.match(html, /暂不用喂/);
    assert.match(html, /上次 3 天前 · 进度 50%/);
}
context.fixture = { feeding_state: 'due', fed: 0, fed_time: `${day(1)} 08:10` };
vm.runInContext('renderDynamicCards(fixture, {})', context);
assert.match(element('dynamic-cards').innerHTML, /该喂食了[\s\S]*上次 昨天 08:10/);
console.log('PASS: boolean/select serialization, retained settings, bilingual status, metadata filtering, legacy card');
