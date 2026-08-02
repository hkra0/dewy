// 摄像头：实时预览与高清抓拍弹窗。
import { t } from './i18n.js';
import { state, getViewerKey } from './state.js';
import { apiGet, bust } from './api.js';

let sessionHDSrc = null, sessionHDTime = null, sessionHDEpoch = 0;
let currentCamBlobUrl = null;

export async function fetchImage(forceLive = false) {
    const cameraBlock = document.getElementById('camera-block');

    if (!getViewerKey()) { cameraBlock.classList.add('hidden'); return; }

    const img = document.getElementById('cam-img');
    const camTs = document.getElementById('cam-timestamp');

    camTs.innerText = t('syncing');
    camTs.style.color = '#94a3b8';
    state.isCameraSyncing = true;

    try {
        const res = await apiGet(bust(forceLive ? '/api/image?live=true' : '/api/image'));

        if (!res.ok) {
            camTs.innerText = t('cam_offline');
            camTs.style.color = '#ef4444';
            if (state.currentTab === 'environment') cameraBlock.classList.remove('hidden');
            return;
        }

        const timestamp = res.headers.get('X-Image-Timestamp');
        const blob = await res.blob();

        img.onload = () => {
            if (timestamp) {
                const imgDate = new Date(parseInt(timestamp) * 1000);
                const isStale = (Date.now() - imgDate.getTime()) > 60000;
                camTs.innerText = (isStale ? '⏳ ' : '📸 ') + imgDate.toLocaleTimeString().toLowerCase();
                camTs.style.color = '#94a3b8';
            }
        };
        if (currentCamBlobUrl) URL.revokeObjectURL(currentCamBlobUrl);
        currentCamBlobUrl = URL.createObjectURL(blob);
        img.src = currentCamBlobUrl;

        if (state.currentTab === 'environment') cameraBlock.classList.remove('hidden');
    } catch (e) {
        camTs.innerText = t('net_disconnect');
        camTs.style.color = '#ef4444';
        if (state.currentTab === 'environment') cameraBlock.classList.remove('hidden');
    } finally {
        state.isCameraSyncing = false;
    }
}

export async function fetchHDImage() {
    if (!getViewerKey()) return;

    const modal = document.getElementById('hd-modal');
    const hdImg = document.getElementById('hd-img');
    const statusText = document.getElementById('hd-status');
    const loader = document.getElementById('hd-loader');
    const hdTs = document.getElementById('hd-timestamp');

    hdImg.onload = null;

    const now = Date.now();
    if (sessionHDSrc && sessionHDEpoch > 0 && (now - sessionHDEpoch < 60000)) {
        statusText.style.display = 'none';
        loader.style.display = 'none';
        hdImg.src = sessionHDSrc;
        hdImg.style.display = 'block';
        hdImg.style.opacity = '1';
        hdImg.style.filter = 'none';
        hdTs.innerText = '📸 ' + sessionHDTime;
        hdTs.classList.remove('hidden');
        hdTs.style.opacity = '1';
        modal.style.display = 'flex';
        return;
    }

    statusText.style.display = 'block';
    statusText.innerText = t('hd_capture_est');
    loader.style.display = 'block';
    modal.style.display = 'flex';

    state.isHDSyncing = true;
    if (sessionHDSrc) {
        hdImg.src = sessionHDSrc;
        hdImg.style.display = 'block';
        hdImg.style.opacity = '1';
        hdImg.style.filter = 'none';
        if (sessionHDTime) {
            hdTs.innerText = '📸 ' + sessionHDTime;
            hdTs.classList.remove('hidden');
            hdTs.style.opacity = '1';
        }
    } else {
        hdImg.style.display = 'none';
        hdTs.classList.add('hidden');
    }

    try {
        const res = await apiGet(bust('/api/image?live=true&hq=true'));

        if (!res.ok) throw new Error('capture failed');

        const timestamp = res.headers.get('X-Image-Timestamp');
        const liveBlob = await res.blob();

        hdImg.onload = () => {
            statusText.style.display = 'none';
            loader.style.display = 'none';
            hdImg.style.display = 'block';
            sessionHDEpoch = Date.now();
            if (timestamp) {
                const imgDate = new Date(parseInt(timestamp) * 1000);
                sessionHDTime = imgDate.toLocaleTimeString().toLowerCase();
                hdTs.innerText = '📸 ' + sessionHDTime;
                hdTs.classList.remove('hidden');
            }
        };

        if (sessionHDSrc) URL.revokeObjectURL(sessionHDSrc);
        sessionHDSrc = URL.createObjectURL(liveBlob);
        hdImg.src = sessionHDSrc;

    } catch (e) {
        loader.style.display = 'none';
        statusText.style.display = 'block';
        statusText.innerText = t('fail_hd');
        statusText.style.color = '#ef4444';
    } finally {
        state.isHDSyncing = false;
    }
}

export function closeHD() { document.getElementById('hd-modal').style.display = 'none'; }
