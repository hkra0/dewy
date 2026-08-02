// 历史视图：Chart.js 曲线与浇水日志表格。
import { t } from './i18n.js';
import { state } from './state.js';
import { apiGet } from './api.js';
import { loadPhotoTimeline } from './timeline.js';

let myChart = null;
const historyCache = {};
let historyFetchTime = {};

/** 切换设备时清空缓存，避免串数据。 */
export function clearHistoryCache() {
    for (const k in historyCache) delete historyCache[k];
}

export function renderHistoryUI(data, type, animate = false) {
    if (type === 'watering') {
        const wrapper = document.getElementById('watering-log-wrapper');
        if (!data || data.length === 0) { wrapper.innerHTML = `<div class="loading-text" style="position: relative; height: 100px; margin-top: 15px;">${t('no_water_records')}</div>`; return; }
        let html = '<div class="watering-table-wrapper"><table class="watering-table">';
        html += `<thead><tr><th>${t('table_duration')}</th><th>${t('table_soil')}</th><th>${t('table_time')}</th></tr></thead><tbody>`;
        data.forEach(item => {
            html += `<tr><td>${item.duration}</td><td>${item.soil}</td><td class="log-time" style="color: var(--text-muted); font-size: 12px;">${item.time}</td></tr>`;
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

    if (hasTemp) datasets.push({ label: t('chart_temp'), data: chartData.map(d => d.temp), borderColor: '#f59e0b', backgroundColor: '#f59e0b', tension: 0.4, pointRadius: 0, yAxisID: 'y', spanGaps: true });
    if (hasHum) datasets.push({ label: t('chart_hum'), data: chartData.map(d => d.hum), borderColor: '#3b82f6', backgroundColor: '#3b82f6', tension: 0.4, pointRadius: 0, yAxisID: 'y1', spanGaps: true });
    if (hasSoil) datasets.push({ label: t('chart_soil'), data: chartData.map(d => d.soil), borderColor: '#10b981', backgroundColor: '#10b981', tension: 0.4, pointRadius: 0, yAxisID: 'y1', spanGaps: true });
    if (hasPres) datasets.push({ label: t('chart_pres'), data: chartData.map(d => d.pressure), borderColor: '#8b5cf6', backgroundColor: '#8b5cf6', tension: 0.4, pointRadius: 0, yAxisID: 'y2', spanGaps: true });
    if (hasWater) datasets.push({
        type: 'line',
        label: t('chart_water'),
        data: chartData.map(d => (d.water > 0) ? (d.soil !== null && d.soil !== undefined ? d.soil : (d.hum !== null && d.hum !== undefined ? d.hum : 50)) : null),
        borderColor: '#22d3ee',
        backgroundColor: '#22d3ee',
        pointBackgroundColor: '#22d3ee',
        pointBorderColor: '#22d3ee',
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

    const computedStyle = getComputedStyle(document.documentElement);
    const textColor = computedStyle.getPropertyValue('--text-muted').trim() || '#666';
    const tooltipBg = computedStyle.getPropertyValue('--surface-color').trim() || 'rgba(0,0,0,0.8)';
    const tooltipText = computedStyle.getPropertyValue('--text-main').trim() || '#fff';
    const gridColor = computedStyle.getPropertyValue('--border').trim() || 'rgba(0,0,0,0.1)';

    if (myChart) {
        myChart.data.labels = labels;
        myChart.data.datasets = datasets;

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
                y2: { type: 'linear', display: false, grid: { drawOnChartArea: false, color: gridColor } }
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
            renderHistoryUI(historyCache[cacheKey], reqType, animateUpdate);
            return;
        }
    } else {
        if (reqType === 'watering') document.getElementById('watering-log-wrapper').innerHTML = '<div class="loading-text" style="position: relative; height: 100px; margin-top: 15px;">loading...</div>';
        else { if (myChart) { myChart.destroy(); myChart = null; } document.getElementById('chart-loading').classList.remove('hidden'); }
    }

    try {
        const res = await apiGet(`/api/history?hist_type=${reqType}&node_id=${state.currentDevice}`);
        const data = await res.json();
        if (!data.error) {
            historyCache[cacheKey] = data;
            historyFetchTime[cacheKey] = Date.now();
            if (state.currentHistType === reqType) renderHistoryUI(data, reqType, animateUpdate);
        }
    } catch (e) { }
}
