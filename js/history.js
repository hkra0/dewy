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

/** 将颜色转换为指定透明度的 RGBA 字符串，兼容 hex (#rgb, #rrggbb) 与 rgb 格式。 */
function hexToRgba(color, alpha) {
    if (!color) return `rgba(217, 119, 6, ${alpha})`;
    color = color.trim();
    if (color.startsWith('rgb')) {
        const m = color.match(/\d+/g);
        if (m && m.length >= 3) return `rgba(${m[0]}, ${m[1]}, ${m[2]}, ${alpha})`;
    }
    const clean = color.replace('#', '');
    if (clean.length === 3) {
        const r = parseInt(clean[0] + clean[0], 16);
        const g = parseInt(clean[1] + clean[1], 16);
        const b = parseInt(clean[2] + clean[2], 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }
    if (clean.length === 6) {
        const num = parseInt(clean, 16);
        if (!isNaN(num)) {
            return `rgba(${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255}, ${alpha})`;
        }
    }
    return `rgba(217, 119, 6, ${alpha})`;
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
    const cFed = metric('--metric-fed', '#10b981');

    // metrics.js 给的是 var(--x) 形式（卡片直接用得上），Chart.js 只认真实色值
    const resolveColor = (value) => {
        const m = /^var\((--[\w-]+)\)$/.exec(value.trim());
        return m ? metric(m[1], '#888') : value;
    };

    const cWaterTemp = metric('--metric-water-temp', '#06b6d4');

    // 水温与气温量纲一致 (℃)，共用 y 轴并默认绘制
    if (extraKeys.includes('water_temp')) {
        datasets.push({
            label: metricLabel('water_temp') + ' (℃)',
            data: chartData.map(d => (d.extra && d.extra.water_temp !== undefined) ? d.extra.water_temp : null),
            borderColor: cWaterTemp,
            backgroundColor: cWaterTemp,
            tension: 0.4, pointRadius: 0, yAxisID: 'y', spanGaps: true,
            hidden: false,
        });
    }

    const hasTempDist = type === 'daily' && chartData.some(d => d.temp_dist && typeof d.temp_dist === 'object');

    // 每日视图：绘制温度分位数密度条带 (Fan Chart / Density Ribbon)
    if (hasTemp && hasTempDist) {
        // 外层极值带 (Min ~ Max)，透明度 10%
        datasets.push({
            label: 'temp_max',
            data: chartData.map(d => d.temp_dist ? d.temp_dist.max : null),
            borderColor: 'transparent',
            backgroundColor: 'transparent',
            pointRadius: 0,
            pointHoverRadius: 0,
            tension: 0.4,
            yAxisID: 'y',
            spanGaps: true,
            isTempBand: true,
            hideFromLegend: true,
            fill: false,
        });
        datasets.push({
            label: 'temp_min',
            data: chartData.map(d => d.temp_dist ? d.temp_dist.min : null),
            borderColor: 'transparent',
            backgroundColor: hexToRgba(cTemp, 0.10),
            pointRadius: 0,
            pointHoverRadius: 0,
            tension: 0.4,
            yAxisID: 'y',
            spanGaps: true,
            isTempBand: true,
            hideFromLegend: true,
            fill: '-1',
        });
        // 内层核心带 (P25 ~ P75 四分位距)，透明度 18%
        datasets.push({
            label: 'temp_p75',
            data: chartData.map(d => d.temp_dist ? d.temp_dist.p75 : null),
            borderColor: 'transparent',
            backgroundColor: 'transparent',
            pointRadius: 0,
            pointHoverRadius: 0,
            tension: 0.4,
            yAxisID: 'y',
            spanGaps: true,
            isTempBand: true,
            hideFromLegend: true,
            fill: false,
        });
        datasets.push({
            label: 'temp_p25',
            data: chartData.map(d => d.temp_dist ? d.temp_dist.p25 : null),
            borderColor: 'transparent',
            backgroundColor: hexToRgba(cTemp, 0.18),
            pointRadius: 0,
            pointHoverRadius: 0,
            tension: 0.4,
            yAxisID: 'y',
            spanGaps: true,
            isTempBand: true,
            hideFromLegend: true,
            fill: '-1',
        });
    }

    if (hasTemp) datasets.push({
        label: t('chart_temp'),
        data: chartData.map(d => d.temp),
        borderColor: cTemp,
        backgroundColor: cTemp,
        tension: 0.4,
        pointRadius: 0,
        yAxisID: 'y',
        spanGaps: true,
        isTemp: true,
        tempDist: chartData.map(d => d.temp_dist),
    });
    if (hasHum) datasets.push({ label: t('chart_hum'), data: chartData.map(d => d.hum), borderColor: cHum, backgroundColor: cHum, tension: 0.4, pointRadius: 0, yAxisID: 'y1', spanGaps: true });
    if (hasSoil) datasets.push({ label: t('chart_soil'), data: chartData.map(d => d.soil), borderColor: cSoil, backgroundColor: cSoil, tension: 0.4, pointRadius: 0, yAxisID: 'y1', spanGaps: true });
    if (hasPres) datasets.push({ label: t('chart_pres'), data: chartData.map(d => d.pressure), borderColor: cPres, backgroundColor: cPres, tension: 0.4, pointRadius: 0, yAxisID: 'y2', spanGaps: true });
    // 其余额外指标（照度、CO₂…）。默认折叠：它们的量纲与温湿度差着几个数量级，
    // 直接画出来会把原本的曲线压成直线；放进图例让用户按需点开，
    // 数据可达，默认视图又不被破坏。
    for (const key of extraKeys) {
        if (key === 'water_temp' || key === 'fed' || key === 'fed_time') continue;
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

    // 喂食事件图钉（离散事件）：
    // 在 24h 视图中进行边沿检测（只在 0 -> 1 跳变时记录事件点，避免全天持续产生几十个密集点）；
    // 在 daily 视图中，当天均值大于 0 则视为当天已喂食。
    // 固定在隐藏辅助轴 yEvent 的顶部 (96)，不挤压温湿度主轴。
    let fedPoints = [];
    let fedInfo = [];
    let hasFedEvent = false;
    const hasFedMetric = extraKeys.includes('fed') || chartData.some(d => d.extra && d.extra.fed !== undefined);

    if (hasFedMetric) {
        if (type === 'daily') {
            chartData.forEach(d => {
                const fedVal = (d.extra && d.extra.fed != null) ? Number(d.extra.fed) : 0;
                if (fedVal > 0) {
                    fedPoints.push(96);
                    fedInfo.push(t('fed_yes'));
                    hasFedEvent = true;
                } else {
                    fedPoints.push(null);
                    fedInfo.push(null);
                }
            });
        } else {
            for (let i = 0; i < chartData.length; i++) {
                const d = chartData[i];
                const currentFed = (d.extra && d.extra.fed != null) ? Number(d.extra.fed) : 0;
                const prevFed = (i > 0 && chartData[i - 1].extra && chartData[i - 1].extra.fed != null)
                    ? Number(chartData[i - 1].extra.fed) : 0;
                const isEdge = (currentFed >= 1 && prevFed < 1 && (i > 0 || chartData.length === 1));
                if (isEdge) {
                    fedPoints.push(96);
                    fedInfo.push(t('fed_yes'));
                    hasFedEvent = true;
                } else {
                    fedPoints.push(null);
                    fedInfo.push(null);
                }
            }
        }
    }

    if (hasFedEvent) datasets.push({
        type: 'line',
        label: t('chart_fed'),
        data: fedPoints,
        borderColor: cFed,
        backgroundColor: cFed,
        pointBackgroundColor: cFed,
        pointBorderColor: cFed,
        pointBorderWidth: 2,
        pointRadius: 6,
        pointHoverRadius: 8,
        pointStyle: 'rectRot',
        showLine: false,
        spanGaps: false,
        yAxisID: 'yEvent',
        isFeeding: true,
        fedData: fedInfo
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

    const legendFilter = (item, chartData) => !chartData.datasets[item.datasetIndex]?.hideFromLegend;

    const onLegendClick = (e, legendItem, legend) => {
        const chart = legend.chart;
        const index = legendItem.datasetIndex;
        const isVisible = chart.isDatasetVisible(index);
        chart.setDatasetVisibility(index, !isVisible);

        const clickedDs = chart.data.datasets[index];
        if (clickedDs && clickedDs.isTemp) {
            chart.data.datasets.forEach((ds, i) => {
                if (ds.isTempBand) {
                    chart.setDatasetVisibility(i, !isVisible);
                }
            });
        }
        chart.update();
    };

    const formatTooltipLabel = (context) => {
        if (context.dataset.isTempBand) {
            return null;
        }
        if (context.dataset.isWatering) {
            const waterVal = context.dataset.waterData ? context.dataset.waterData[context.dataIndex] : '';
            return `${context.dataset.label}: ${waterVal}`;
        }
        if (context.dataset.isFeeding) {
            const fedVal = context.dataset.fedData ? context.dataset.fedData[context.dataIndex] : '';
            return `${context.dataset.label}: ${fedVal}`;
        }
        if (context.dataset.isTemp && context.dataset.tempDist) {
            const dist = context.dataset.tempDist[context.dataIndex];
            if (dist && dist.min !== undefined && dist.max !== undefined) {
                const val = context.parsed.y !== null ? context.parsed.y : '--';
                return [
                    `${context.dataset.label}: ${val}℃`,
                    `  ${t('temp_core')}: ${dist.p25} ~ ${dist.p75}℃`,
                    `  ${t('temp_range')}: ${dist.min} ~ ${dist.max}℃`
                ];
            }
        }
        let label = context.dataset.label || '';
        if (label) {
            label += ': ';
        }
        if (context.parsed.y !== null) {
            label += context.parsed.y;
        }
        return label;
    };

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
            if (ds.isTempBand) {
                const tempVisible = wasVisible.has(t('chart_temp')) ? wasVisible.get(t('chart_temp')) : true;
                myChart.getDatasetMeta(i).hidden = !tempVisible;
            } else if (wasVisible.has(ds.label)) {
                myChart.getDatasetMeta(i).hidden = !wasVisible.get(ds.label);
            }
        });

        myChart.options.plugins.legend.labels.filter = legendFilter;
        myChart.options.plugins.legend.onClick = onLegendClick;
        myChart.options.plugins.tooltip.callbacks.label = formatTooltipLabel;

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
        if (!myChart.options.scales.yEvent) {
            myChart.options.scales.yEvent = { type: 'linear', display: false, min: 0, max: 100, grid: { drawOnChartArea: false, color: gridColor } };
        }

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
                legend: {
                    labels: { color: textColor, boxWidth: 16, boxHeight: 10, useBorderRadius: true, borderRadius: 5, filter: legendFilter },
                    onClick: onLegendClick
                },
                tooltip: {
                    titleColor: tooltipText, bodyColor: tooltipText, backgroundColor: tooltipBg, titleFont: { size: 13, family: 'Inter' }, bodyFont: { size: 12, family: 'Inter' }, padding: 10, cornerRadius: 8, borderColor: gridColor, borderWidth: 1,
                    callbacks: {
                        label: formatTooltipLabel
                    }
                }
            },
            scales: {
                x: { grid: { display: false, color: gridColor }, ticks: { color: textColor, maxTicksLimit: 6, font: { size: 10 } } },
                y: { type: 'linear', display: true, position: 'left', grid: { color: gridColor }, ticks: { color: textColor, font: { size: 10 } } },
                y1: { type: 'linear', display: true, position: 'right', grid: { drawOnChartArea: false, color: gridColor }, ticks: { color: textColor, font: { size: 10 } } },
                y2: { type: 'linear', display: false, grid: { drawOnChartArea: false, color: gridColor } },
                // 额外指标共用一条隐藏轴：它们彼此量纲也不同，但都不该去挤压主轴
                y3: { type: 'linear', display: false, grid: { drawOnChartArea: false, color: gridColor } },
                // 事件图钉（喂食等离散事件）固定顶部标尺辅助轴
                yEvent: { type: 'linear', display: false, min: 0, max: 100, grid: { drawOnChartArea: false, color: gridColor } }
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
