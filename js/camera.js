// 摄像头：实时预览与高清抓拍弹窗。
import { t } from './i18n.js';
import { state, getViewerKey } from './state.js';
import { apiGet, bust } from './api.js';

let sessionHDSrc = null, sessionHDTime = null, sessionHDEpoch = 0;
let currentCamBlobUrl = null;

// 当前这张预览图的拍摄时间（秒）。作为 ?since= 发给树莓派做条件请求：
// 这张图只有在有人请求 live 时才会被重写，而前端 30 秒轮询一次，
// 不带条件的话每轮都在重下同一张几十 KB 的图。
let currentCamEpoch = 0;

/** 时间戳标签。⏳ 表示这张图已经超过一分钟没更新了。 */
function renderCamTimestamp(camTs, epochSec) {
    if (!epochSec) return;
    const imgDate = new Date(epochSec * 1000);
    const isStale = (Date.now() - imgDate.getTime()) > 60000;
    camTs.innerText = (isStale ? '⏳ ' : '📸 ') + imgDate.toLocaleTimeString().toLowerCase();
    camTs.style.color = 'var(--text-muted)';
}

export async function fetchImage(forceLive = false) {
    const cameraBlock = document.getElementById('camera-block');

    if (!getViewerKey()) { cameraBlock.classList.add('hidden'); return; }

    const img = document.getElementById('cam-img');
    const camTs = document.getElementById('cam-timestamp');

    // 只有 live 抓拍才值得打断标签：那要等树莓派真的跑一次 rpicam。
    // 后台轮询多半直接 304 返回，闪一下 "syncing" 纯属噪音。
    if (forceLive) {
        camTs.innerText = t('syncing');
        camTs.style.color = 'var(--text-muted)';
    }
    state.isCameraSyncing = true;

    try {
        const path = forceLive
            ? '/api/image?live=true'
            : `/api/image${currentCamEpoch ? '?since=' + currentCamEpoch : ''}`;
        const res = await apiGet(bust(path));

        // 图没变，省掉一次整图下载。时间戳标签仍要重绘——
        // 是否 stale 取决于当前时刻，不取决于这次响应。
        if (res.status === 304) {
            renderCamTimestamp(camTs, currentCamEpoch);
            if (state.currentTab === 'environment') cameraBlock.classList.remove('hidden');
            return;
        }

        if (!res.ok) {
            camTs.innerText = t('cam_offline');
            camTs.style.color = 'var(--danger)';
            if (state.currentTab === 'environment') cameraBlock.classList.remove('hidden');
            return;
        }

        const timestamp = res.headers.get('X-Image-Timestamp');
        const blob = await res.blob();
        const epochSec = timestamp ? parseInt(timestamp, 10) : 0;

        img.onload = () => renderCamTimestamp(camTs, epochSec);
        if (currentCamBlobUrl) URL.revokeObjectURL(currentCamBlobUrl);
        currentCamBlobUrl = URL.createObjectURL(blob);
        currentCamEpoch = epochSec;
        img.src = currentCamBlobUrl;

        if (state.currentTab === 'environment') cameraBlock.classList.remove('hidden');
    } catch (e) {
        camTs.innerText = t('net_disconnect');
        camTs.style.color = 'var(--danger)';
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
        statusText.style.color = 'var(--danger)';
    } finally {
        state.isHDSyncing = false;
    }
}

export function closeHD() { document.getElementById('hd-modal').style.display = 'none'; }

/** 弹窗的 Esc 与点击背景关闭。
 *
 *  此前唯一的出口是那个 close 按钮——手机上按返回键或点背景都关不掉，
 *  是很常见的挫败点。app.js 启动时调用一次。 */
export function initModalDismiss() {
    const modal = document.getElementById('hd-modal');
    if (!modal) return;

    const isOpen = () => modal.style.display === 'flex';

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && isOpen()) closeHD();
    });

    // 只有点在遮罩本身才关闭；点图片或按钮时 e.target 是子元素，不误关
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeHD();
    });
}
