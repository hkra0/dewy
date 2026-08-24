// 历史视图：Chart.js 曲线与浇水日志表格。
import { t } from './i18n.js';
import { state } from './state.js';
import { apiGet } from './api.js';
import { ensureChart } from './cdn.js';
import { loadPhotoTimeline } from './timeline.js';
import { metricLabel, metricUnit, metricColor } from './metrics.js';

let myChart = null;
const historyCache = {};
let historyFetchTime = {};

/** 切换设备时清空缓存，避免串数据。 */
export function clearHistoryCache() {
    for (const k in historyCache) delete historyCache[k];
}

/** 历史数据取不到时的提示。
 *
 *  屏幕上已经有缓存数据时保持沉默：这个函数在历史页会被 30 秒轮询反复调用，
 *  每轮弹一次提示会刷屏，而 fetchSensorData 已经把状态栏切成 conn_lost 了。
 *  只有当界面上什么都没有、否则会永远停在 "loading..." 时才需要接管。 */
function showHistoryError(type, hasData) {
    if (hasData) return;
    if (type === 'watering') {
        document.getElementById('watering-log-wrapper').innerHTML =
            `<div class="loading-text" style="position: relative; height: 100px; margin-top: 15px;">${t('load_failed')}</div>`;
        return;
    }
    const el = document.getElementById('chart-loading');
    el.innerText = t('load_failed');
    el.classList.remove('hidden');
}

export async function renderHistoryUI(data, type, animate = false) {
    if (type === 'watering') {
        const wrapper = document.getElementById('watering-log-wrapper');
        if (!data || data.length === 0) { wrapper.innerHTML = `<div class="loading-text" style="position: relative; height: 100px; margin-top: 15px;">${t('no_water_records')}</div>`; return; }
        let html = '<div class="watering-table-wrapper"><table class="watering-table">';
        html += `<thead><tr><th>${t('table_duration')}</th><th>${t('table_soil')}</th><th>${t('table_pulses')}</th><th>${t('table_soil_after')}</th><th>${t('table_time')}</th></tr></thead><tbody>`;
        data.forEach(item => {
            const pulses = item.pulses != null ? item.pulses : 1;
            const soilAfter = item.soil_after != null ? item.soil_after : '--';
            html += `<tr><td>${item.duration}</td><td>${item.soil}</td><td>${pulses}</td><td>${soilAfter}</td><td class="log-time" style="color: var(--text-muted); font-size: 12px;">${item.time}</td></tr>`;
        });
        wrapper.innerHTML = html + '</tbody></table></div>';
        return;
    }
    if (!data || data.length === 0) {
        if (myChart) { myChart.destroy(); myChart = null; }
        document.getElementById('chart-loading').innerText = t('no_data');
        document.getElementById('chart-loading').classList.remove('hidden');
        return;
    }
    document.getElementById('chart-loading').classList.add('hidden');

    const chartData = data;
    const labels = chartData.map(d => d.time);
    const datasets = [];

    const hasTemp = chartData.some(d => d.temp !== null && d.temp !== undefined);
    const hasHum = chartData.some(d => d.hum !== null && d.hum !== undefined);
    const hasSoil = chartData.some(d => d.soil !== null && d.soil !== undefined);
    const hasPres = chartData.some(d => d.pressure !== null && d.pressure !== undefined);
    const hasWater = chartData.some(d => d.water !== null && d.water !== undefined && d.water > 0);

    // 后端按时间桶并进来的额外指标。哪些字段存在完全取决于用户接了什么传感器，
    // 所以要从数据里收集，不能有一张预设清单。
    const extraKeys = [...new Set(chartData.flatMap(d => Object.keys(d.extra || {})))].sort();

    // Chart.js 只认真实色值，取不到 var()，所以从 :root 上把 token 读出来。
    // 色值的唯一来源仍是 style.css，暗色模式会自动跟着变。
    const metric = (name, fallback) =>
        getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
    const cTemp = metric('--metric-temp', '#d97706');
    const cHum = metric('--metric-hum', '#2563eb');
    const cSoil = metric('--metric-soil', '#059669');
    const cPres = metric('--metric-pres', '#7c3aed');
    const cWater = metric('--metric-water', '#0891b2');

    // metrics.js 给的是 var(--x) 形式（卡片直接用得上），Chart.js 只认真实色值
    const resolveColor = (value) => {
        const m = /^var\((--[\w-]+)\)$/.exec(value.trim());
        return m ? metric(m[1], '#888') : value;
    };

    if (hasTemp) datasets.push({ label: t('chart_temp'), data: chartData.map(d => d.temp), borderColor: cTemp, backgroundColor: cTemp, tension: 0.4, pointRadius: 0, yAxisID: 'y', spanGaps: true });
    if (hasHum) datasets.push({ label: t('chart_hum'), data: chartData.map(d => d.hum), borderColor: cHum, backgroundColor: cHum, tension: 0.4, pointRadius: 0, yAxisID: 'y1', spanGaps: true });
    if (hasSoil) datasets.push({ label: t('chart_soil'), data: chartData.map(d => d.soil), borderColor: cSoil, backgroundColor: cSoil, tension: 0.4, pointRadius: 0, yAxisID: 'y1', spanGaps: true });
    if (hasPres) datasets.push({ label: t('chart_pres'), data: chartData.map(d => d.pressure), borderColor: cPres, backgroundColor: cPres, tension: 0.4, pointRadius: 0, yAxisID: 'y2', spanGaps: true });
    // 额外指标（照度、CO₂…）。默认折叠：它们的量纲与温湿度差着几个数量级，
    // 直接画出来会把原本的曲线压成直线；放进图例让用户按需点开，
    // 数据可达，默认视图又不被破坏。
    for (const key of extraKeys) {
        const unit = metricUnit(key);
        datasets.push({
            label: metricLabel(key) + (unit ? ` (${unit})` : ''),
            data: chartData.map(d => (d.extra && d.extra[key] !== undefined) ? d.extra[key] : null),
            borderColor: resolveColor(metricColor(key)),
            backgroundColor: resolveColor(metricColor(key)),
            tension: 0.4, pointRadius: 0, yAxisID: 'y3', spanGaps: true,
            hidden: true,
        });
    }

    if (hasWater) datasets.push({
        type: 'line',
        label: t('chart_water'),
        data: chartData.map(d => (d.water > 0) ? (d.soil !== null && d.soil !== undefined ? d.soil : (d.hum !== null && d.hum !== undefined ? d.hum : 50)) : null),
        borderColor: cWater,
        backgroundColor: cWater,
        pointBackgroundColor: cWater,
        pointBorderColor: cWater,
        pointBorderWidth: 2.5,
        pointRadius: 6,
        pointHoverRadius: 8,
        pointStyle: 'cross',
        showLine: false,
        spanGaps: false,
        yAxisID: 'y1',
        isWatering: true,
        waterData: chartData.map(d => d.water)
    });

    // Chart.js 改为按需加载：只看环境页的访客不必下载这 200KB。
    // 数据集已经算好，这里才是第一次真正用到 Chart。
    if (!await ensureChart()) {
        const loadingEl = document.getElementById('chart-loading');
        loadingEl.innerText = t('chart_lib_missing');
        loadingEl.classList.remove('hidden');
        return;
    }

    const computedStyle = getComputedStyle(document.documentElement);
    const textColor = computedStyle.getPropertyValue('--text-muted').trim() || '#666';
    const tooltipBg = computedStyle.getPropertyValue('--surface-color').trim() || 'rgba(0,0,0,0.8)';
    const tooltipText = computedStyle.getPropertyValue('--text-main').trim() || '#fff';
    const gridColor = computedStyle.getPropertyValue('--border').trim() || 'rgba(0,0,0,0.1)';

    if (myChart) {
        // 先记下用户在图例上的显示/隐藏选择。历史页 30 秒轮询一次，
        // 每轮都整体换掉 datasets——不还原的话，用户刚点开的额外指标
        // 下一轮就被 hidden 的默认值重新收起来了。按 label 而非下标匹配：
        // 传感器上下线会让下标错位。
        const wasVisible = new Map();
        myChart.data.datasets.forEach((ds, i) => wasVisible.set(ds.label, myChart.isDatasetVisible(i)));

        myChart.data.labels = labels;
        myChart.data.datasets = datasets;

        datasets.forEach((ds, i) => {
            if (wasVisible.has(ds.label)) {
                myChart.getDatasetMeta(i).hidden = !wasVisible.get(ds.label);
            }
        });

        myChart.options.plugins.legend.labels.color = textColor;
        myChart.options.plugins.tooltip.titleColor = tooltipText;
        myChart.options.plugins.tooltip.bodyColor = tooltipText;
        myChart.options.plugins.tooltip.backgroundColor = tooltipBg;
        myChart.options.plugins.tooltip.borderColor = gridColor;

        myChart.options.scales.x.ticks.color = textColor;
        myChart.options.scales.x.grid.color = gridColor;
        myChart.options.scales.y.ticks.color = textColor;
        myChart.options.scales.y.grid.color = gridColor;
        myChart.options.scales.y1.ticks.color = textColor;
        myChart.options.scales.y1.grid.color = gridColor;

        if (animate || myChart.lastReqType !== type) {
            myChart.update();
        } else {
            myChart.update('none');
        }
        myChart.lastReqType = type;
        return;
    }

    const ctx = document.getElementById('historyChart').getContext('2d');
    myChart = new Chart(ctx, {
        type: 'line', data: { labels: labels, datasets: datasets },
        options: {
            responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { labels: { color: textColor, boxWidth: 16, boxHeight: 10, useBorderRadius: true, borderRadius: 5 } },
                tooltip: {
                    titleColor: tooltipText, bodyColor: tooltipText, backgroundColor: tooltipBg, titleFont: { size: 13, family: 'Inter' }, bodyFont: { size: 12, family: 'Inter' }, padding: 10, cornerRadius: 8, borderColor: gridColor, borderWidth: 1,
                    callbacks: {
                        label: function (context) {
                            if (context.dataset.isWatering) {
                                const waterVal = context.dataset.waterData ? context.dataset.waterData[context.dataIndex] : '';
                                return `${context.dataset.label}: ${waterVal}`;
                            }
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                label += context.parsed.y;
                            }
                            return label;
                        }
                    }
                }
            },
            scales: {
                x: { grid: { display: false, color: gridColor }, ticks: { color: textColor, maxTicksLimit: 6, font: { size: 10 } } },
                y: { type: 'linear', display: true, position: 'left', grid: { color: gridColor }, ticks: { color: textColor, font: { size: 10 } } },
                y1: { type: 'linear', display: true, position: 'right', grid: { drawOnChartArea: false, color: gridColor }, ticks: { color: textColor, font: { size: 10 } } },
                y2: { type: 'linear', display: false, grid: { drawOnChartArea: false, color: gridColor } },
                // 额外指标共用一条隐藏轴：它们彼此量纲也不同，但都不该去挤压主轴
                y3: { type: 'linear', display: false, grid: { drawOnChartArea: false, color: gridColor } }
            }
        }
    });
    myChart.lastReqType = type;
}

export async function loadHistoryData(forceFetch = false) {
    if (state.currentHistType === 'photos') {
        loadPhotoTimeline(forceFetch);
        return;
    }
    const reqType = state.currentHistType;
    const cacheKey = state.currentDevice + '_' + reqType;

    let animateUpdate = false;

    if (historyCache[cacheKey]) {
        const lastFetch = historyFetchTime[cacheKey] || 0;
        if (Date.now() - lastFetch > 30 * 60 * 1000) {
            animateUpdate = true;
        }

        if (!forceFetch) {
            await renderHistoryUI(historyCache[cacheKey], reqType, animateUpdate);
            return;
        }
    } else {
        if (reqType === 'watering') document.getElementById('watering-log-wrapper').innerHTML = `<div class="loading-text" style="position: relative; height: 100px; margin-top: 15px;">${t('chart_loading')}</div>`;
        else { if (myChart) { myChart.destroy(); myChart = null; } document.getElementById('chart-loading').classList.remove('hidden'); }
    }

    const hasData = !!historyCache[cacheKey];

    try {
        const res = await apiGet(`/api/history?hist_type=${reqType}&node_id=${state.currentDevice}`);

        // 404 = 密钥不对/端点不存在，属访客路径，必须静默（见 AGENTS.md「七、鉴权」）。
        // 其余失败是真的连不上，必须报出来——一起吞掉的话界面就永远停在
        // loading 上，用户没有任何线索。
        if (res.status === 404) return;
        if (!res.ok) { showHistoryError(reqType, hasData); return; }

        const data = await res.json();
        if (data.error) { showHistoryError(reqType, hasData); return; }

        historyCache[cacheKey] = data;
        historyFetchTime[cacheKey] = Date.now();
        if (state.currentHistType === reqType) await renderHistoryUI(data, reqType, animateUpdate);
    } catch (e) {
        // fetch 抛异常或响应不是 JSON —— 网络层就没通
        console.error('history load failed', e);
        showHistoryError(reqType, hasData);
    }
}
