// 一次刷新涉及多个视图，单独成模块以打断 navigation/dashboard 的循环引用。
import { t } from './i18n.js';
import { state } from './state.js';
import { fetchSensorData } from './dashboard.js';
import { fetchImage } from './camera.js';
import { loadHistoryData } from './history.js';

export async function fetchAllData(forceLive = false) {
    const btn = document.getElementById('refresh-btn');
    if (btn) btn.innerText = t('syncing');

    const tasks = [fetchSensorData()];
    const nodeInfo = state.availableNodes[state.currentDevice] || {};
    const hasCamera = nodeInfo.sensors && ('camera' in nodeInfo.sensors);

    if (state.currentTab === 'environment' && hasCamera) tasks.push(fetchImage(forceLive));
    if (state.currentTab === 'history') tasks.push(loadHistoryData(true));

    await Promise.allSettled(tasks);

    if (btn) btn.innerText = t('refresh');
}
