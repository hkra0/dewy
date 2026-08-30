// 固定指标之外的测量量：标签、单位与配色。
//
// 后端的 node_data 只有六个固定列，驱动返回的其它数值字段落到 node_metrics
// 长表（见 core/database.py）。这些字段事先不可知——第三方驱动想返回什么就
// 返回什么——所以这里不能是一张必须逐个登记的白名单：认识的给中英文名与单位，
// 不认识的也照样显示，只是标签用字段名本身。
import { tf } from './i18n.js';

// 已有专属界面的字段，不进"其它指标"区：
// 前四个是环境卡片，后两个在系统页的电源状态里。
export const BUILT_IN_FIELDS = new Set([
    'water_temp', 'temperature', 'humidity', 'soil_moisture', 'soil_adc_raw', 'pressure', 'voltage', 'current', 'fed', 'fed_time',
]);

// 常见量的单位。查不到就不显示单位，而不是猜一个错的。
const UNITS = {
    water_temp: '℃',
    illuminance: 'lx', lux: 'lx', uv_index: '',
    co2: 'ppm', tvoc: 'ppb', ec: 'mS/cm', ph: '',
    altitude: 'm', gas_resistance: 'Ω',
    battery: '%', battery_percent: '%',
    power: 'W', energy: 'Wh', rssi: 'dBm',
    wind_speed: 'm/s', rainfall: 'mm', noise: 'dB',
    pm25: 'µg/m³', pm10: 'µg/m³',
};

// 额外指标没有专属配色，按字段名稳定地分配一个，
// 保证同一个指标在卡片与图表里始终同色。
const PALETTE = [
    'var(--metric-extra-1)', 'var(--metric-extra-2)',
    'var(--metric-extra-3)', 'var(--metric-extra-4)',
];

/** 字段名 → 显示标签。i18n 里有 metric_<key> 就用它，否则把字段名读顺。 */
export function metricLabel(key) {
    return tf('metric_' + key, key.replace(/_/g, ' '));
}

/** 字段名 → 单位，未知返回空串。 */
export function metricUnit(key) {
    return UNITS[key] !== undefined ? UNITS[key] : '';
}

/** 字段名 → 颜色。同名字段每次都得到同一个颜色（简单的字符和取模）。 */
export function metricColor(key) {
    if (key === 'water_temp') return 'var(--metric-water-temp)';
    let sum = 0;
    for (let i = 0; i < key.length; i++) sum += key.charCodeAt(i);
    return PALETTE[sum % PALETTE.length];
}

/** 从一份节点读数里挑出要显示为"其它指标"的字段，按字段名排序。 */
export function extraMetricEntries(nodeData) {
    if (!nodeData) return [];
    return Object.keys(nodeData)
        .filter(k => !BUILT_IN_FIELDS.has(k))
        .filter(k => typeof nodeData[k] === 'number' && Number.isFinite(nodeData[k]))
        .sort()
        .map(k => [k, nodeData[k]]);
}
