// 照片时间轴播放器与 GIF 导出。
import { t } from './i18n.js';
import { showToast } from './ui.js';
import { state, getViewerKey } from './state.js';
import { apiGet } from './api.js';

let tlPhotos = [];
let tlCurrentIdx = 0;
let tlPlaying = false;
let tlInterval = null;
let tlSpeed = 500;
const tlThumbCache = new Map();
const tlFetching = new Set();
let tlLastFetchTime = 0;

export function getPhotoVersion(photo) {
    if (!photo) return '';
    return encodeURIComponent(`${photo.timestamp || ''}_${photo.size || ''}_${photo.thumb_size || ''}`);
}

export async function loadPhotoTimeline(forceFetch = false) {
    const nodeInfo = state.availableNodes[state.currentDevice] || {};
    const hasCamera = nodeInfo.sensors && ('camera' in nodeInfo.sensors);
    if (!getViewerKey() || !hasCamera) return;

    const loadingEl = document.getElementById('timeline-loading');
    const imgEl = document.getElementById('timeline-img');
    const dateEl = document.getElementById('timeline-date');
    const emptyEl = document.getElementById('timeline-empty');
    const slider = document.getElementById('tl-slider');
    const counter = document.getElementById('tl-counter');

    if (!forceFetch && tlPhotos.length > 0 && Date.now() - tlLastFetchTime < 300000) {
        renderTimelineFrame(tlCurrentIdx);
        return;
    }
    if (tlPhotos.length === 0 || !imgEl.getAttribute('src')) {
        if (emptyEl) emptyEl.classList.add('hidden');
        if (loadingEl) loadingEl.classList.remove('hidden');
    }
    try {
        const res = await apiGet('/api/photos');
        if (res.ok) {
            const list = await res.json();
            // Reverse to chronological order (oldest -> newest for timeline play)
            const newPhotos = list.reverse();
            newPhotos.forEach(p => {
                const oldP = tlPhotos.find(old => old.date === p.date);
                if (oldP && getPhotoVersion(oldP) !== getPhotoVersion(p) && tlThumbCache.has(p.date)) {
                    URL.revokeObjectURL(tlThumbCache.get(p.date));
                    tlThumbCache.delete(p.date);
                }
            });
            tlPhotos = newPhotos;
            tlLastFetchTime = Date.now();
        }
    } catch (e) {
        console.error("Failed to load photo list", e);
    }

    if (tlPhotos.length === 0) {
        if (loadingEl) loadingEl.classList.add('hidden');
        imgEl.src = "";
        dateEl.innerText = "";
        if (emptyEl) emptyEl.classList.remove('hidden');
        slider.max = "0";
        slider.value = "0";
        counter.innerText = "0 / 0";
        if (tlPlaying) toggleTimelinePlay();
        return;
    }

    if (emptyEl) emptyEl.classList.add('hidden');
    slider.min = "0";
    slider.max = String(tlPhotos.length - 1);
    if (tlCurrentIdx >= tlPhotos.length || tlCurrentIdx === 0) {
        tlCurrentIdx = tlPhotos.length - 1; // Default to newest photo
    }
    renderTimelineFrame(tlCurrentIdx);
}

async function fetchThumb(date) {
    if (tlThumbCache.has(date) || tlFetching.has(date)) return;
    tlFetching.add(date);
    try {
        const photo = tlPhotos.find(p => p.date === date);
        const ver = getPhotoVersion(photo);
        const res = await apiGet(`/api/photos/${date}?thumb=1${ver ? '&v=' + ver : ''}`);
        if (res.ok) {
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            tlThumbCache.set(date, url);
            // Maintain max cache size of 20
            if (tlThumbCache.size > 20) {
                const oldestKey = tlThumbCache.keys().next().value;
                if (oldestKey !== tlPhotos[tlCurrentIdx]?.date) {
                    URL.revokeObjectURL(tlThumbCache.get(oldestKey));
                    tlThumbCache.delete(oldestKey);
                }
            }
        }
    } catch (e) {
        console.error(`Failed to fetch thumb for ${date}`, e);
    } finally {
        tlFetching.delete(date);
    }
}

export async function renderTimelineFrame(idx) {
    if (idx < 0 || idx >= tlPhotos.length) return;
    tlCurrentIdx = idx;
    const photo = tlPhotos[idx];

    document.getElementById('tl-slider').value = idx;
    document.getElementById('tl-counter').innerText = `${idx + 1} / ${tlPhotos.length}`;
    document.getElementById('timeline-date').innerText = photo.date;

    const imgEl = document.getElementById('timeline-img');
    const loadingEl = document.getElementById('timeline-loading');
    const emptyEl = document.getElementById('timeline-empty');
    if (emptyEl) emptyEl.classList.add('hidden');

    if (tlThumbCache.has(photo.date)) {
        if (loadingEl) loadingEl.classList.add('hidden');
        imgEl.src = tlThumbCache.get(photo.date);
    } else {
        if (!imgEl.getAttribute('src') && loadingEl) loadingEl.classList.remove('hidden');
        await fetchThumb(photo.date);
        if (tlThumbCache.has(photo.date) && tlCurrentIdx === idx) {
            if (loadingEl) loadingEl.classList.add('hidden');
            imgEl.src = tlThumbCache.get(photo.date);
        }
    }

    // Preload 6 frames ahead
    for (let step = 1; step <= 6; step++) {
        const nextIdx = (idx + step) % tlPhotos.length;
        if (!tlThumbCache.has(tlPhotos[nextIdx].date)) {
            fetchThumb(tlPhotos[nextIdx].date);
        }
    }
}

export function toggleTimelinePlay() {
    const btn = document.getElementById('tl-play-btn');
    if (tlPlaying) {
        clearInterval(tlInterval);
        tlInterval = null;
        tlPlaying = false;
        btn.innerHTML = "&#9654;";
    } else {
        if (tlPhotos.length <= 1) return;
        tlPlaying = true;
        btn.innerHTML = "&#10074;&#10074;";
        if (tlCurrentIdx === tlPhotos.length - 1) {
            tlCurrentIdx = 0;
            renderTimelineFrame(0);
        }
        tlInterval = setInterval(() => {
            if (tlCurrentIdx < tlPhotos.length - 1) {
                renderTimelineFrame(tlCurrentIdx + 1);
            } else {
                toggleTimelinePlay(); // Auto stop at end
            }
        }, tlSpeed);
    }
}

export function seekTimeline(val) {
    const idx = parseInt(val, 10);
    if (!isNaN(idx)) {
        renderTimelineFrame(idx);
    }
}

export function setTimelineSpeed(ms) {
    tlSpeed = parseInt(ms, 10);
    if (tlPlaying) {
        clearInterval(tlInterval);
        tlInterval = setInterval(() => {
            if (tlCurrentIdx < tlPhotos.length - 1) {
                renderTimelineFrame(tlCurrentIdx + 1);
            } else {
                toggleTimelinePlay();
            }
        }, tlSpeed);
    }
}

function createWatermarkedFrame(imgUrl, dateText) {
    return new Promise((resolve) => {
        const img = new Image();
        img.onload = () => {
            const canvas = document.createElement('canvas');
            const targetWidth = 480;
            const aspect = img.naturalHeight / (img.naturalWidth || 1) || (3 / 4);
            const targetHeight = Math.round(targetWidth * aspect);
            canvas.width = targetWidth;
            canvas.height = targetHeight;
            const ctx = canvas.getContext('2d');

            ctx.drawImage(img, 0, 0, targetWidth, targetHeight);

            ctx.font = '600 13px Inter, -apple-system, sans-serif';
            const text = `📅 ${dateText}`;
            const textWidth = ctx.measureText(text).width;
            const padX = 8, padY = 5;
            const boxX = 10, boxY = targetHeight - 30;
            const boxW = textWidth + padX * 2;
            const boxH = 22;

            ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
            if (ctx.roundRect) {
                ctx.beginPath();
                ctx.roundRect(boxX, boxY, boxW, boxH, 6);
                ctx.fill();
            } else {
                ctx.fillRect(boxX, boxY, boxW, boxH);
            }

            ctx.fillStyle = '#ffffff';
            ctx.textBaseline = 'middle';
            ctx.fillText(text, boxX + padX, boxY + boxH / 2);

            resolve({ dataUrl: canvas.toDataURL('image/jpeg', 0.85), width: targetWidth, height: targetHeight });
        };
        img.onerror = () => resolve(null);
        img.src = imgUrl;
    });
}

async function ensureGifshotLoaded() {
    if (typeof gifshot !== 'undefined') return true;
    const cdns = [
        'https://cdnjs.cloudflare.com/ajax/libs/gifshot/0.3.2/gifshot.min.js',
        'https://unpkg.com/gifshot@0.3.3/build/gifshot.min.js',
        'https://cdn.jsdelivr.net/npm/gifshot@0.3.3/build/gifshot.min.js'
    ];
    for (let url of cdns) {
        try {
            await new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = url;
                script.onload = () => resolve(true);
                script.onerror = () => reject();
                document.head.appendChild(script);
            });
            if (typeof gifshot !== 'undefined') return true;
        } catch (e) {
            console.warn(`Failed to load GIF library from ${url}`);
        }
    }
    return typeof gifshot !== 'undefined';
}

export async function exportTimelineGIF() {
    if (!tlPhotos || tlPhotos.length === 0) return;
    const btn = document.getElementById('tl-export-btn');
    if (!btn || btn.disabled) return;

    if (typeof gifshot === 'undefined') {
        showToast(t('gif_lib_missing'), 'info');
        btn.disabled = true;
        btn.innerText = '⏳...';
        const loaded = await ensureGifshotLoaded();
        if (!loaded || typeof gifshot === 'undefined') {
            btn.disabled = false;
            btn.innerText = t('export_gif');
            showToast(t('gif_error'), 'error');
            return;
        }
        btn.disabled = false;
    }

    if (tlPlaying) toggleTimelinePlay();
    btn.disabled = true;
    btn.innerText = t('exporting');
    showToast(t('gif_start'), 'info');

    const frameUrls = [];
    let gifWidth = 480, gifHeight = 360;

    try {
        for (let i = 0; i < tlPhotos.length; i++) {
            const photo = tlPhotos[i];
            let imgUrl = tlThumbCache.get(photo.date);
            let tempBlobUrl = null;

            if (!imgUrl) {
                try {
                    const ver = getPhotoVersion(photo);
                    const res = await apiGet(`/api/photos/${photo.date}?thumb=1${ver ? '&v=' + ver : ''}`);
                    if (res.ok) {
                        const blob = await res.blob();
                        tempBlobUrl = URL.createObjectURL(blob);
                        imgUrl = tempBlobUrl;
                    }
                } catch (err) {
                    console.error(`Error fetching frame ${photo.date}`, err);
                }
            }

            if (imgUrl) {
                const frame = await createWatermarkedFrame(imgUrl, photo.date);
                if (frame) {
                    frameUrls.push(frame.dataUrl);
                    gifWidth = frame.width;
                    gifHeight = frame.height;
                }
            }
            if (tempBlobUrl) URL.revokeObjectURL(tempBlobUrl);

            const percent = Math.round(((i + 1) / tlPhotos.length) * 50);
            btn.innerText = `${percent}%`;
        }

        if (frameUrls.length === 0) {
            throw new Error("No frames loaded");
        }

        const intervalSec = (tlSpeed || 500) / 1000;

        gifshot.createGIF({
            images: frameUrls,
            gifWidth: gifWidth,
            gifHeight: gifHeight,
            interval: intervalSec,
            numWorkers: 3,
            sampleInterval: 10,
            progressCallback: (captureProgress) => {
                const totalPercent = 50 + Math.round(captureProgress * 50);
                if (btn) btn.innerText = `${totalPercent}%`;
            }
        }, function (obj) {
            btn.disabled = false;
            btn.innerText = t('export_gif');
            if (!obj.error) {
                const a = document.createElement('a');
                a.href = obj.image;
                a.download = `dewy_timeline_${new Date().toISOString().slice(0, 10)}.gif`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                showToast(t('gif_success'), 'success');
            } else {
                showToast(t('gif_error'), 'error');
            }
        });
    } catch (e) {
        console.error("Failed during GIF export", e);
        btn.disabled = false;
        btn.innerText = t('export_gif');
        showToast(t('gif_error'), 'error');
    }
}

export async function viewFullPhoto() {
    if (!tlPhotos || tlPhotos.length === 0 || tlCurrentIdx < 0 || tlCurrentIdx >= tlPhotos.length) return;
    const photo = tlPhotos[tlCurrentIdx];
    const modal = document.getElementById('hd-modal');
    const loader = document.getElementById('hd-loader');
    const statusText = document.getElementById('hd-status');
    const hdImg = document.getElementById('hd-img');
    const hdTs = document.getElementById('hd-timestamp');

    if (tlPlaying) toggleTimelinePlay();

    modal.style.display = 'flex';
    hdImg.style.display = 'none';
    hdTs.classList.add('hidden');
    loader.style.display = 'block';
    statusText.innerText = 'loading...';
    statusText.style.display = 'block';
    statusText.style.color = 'var(--text-main)';

    try {
        const ver = getPhotoVersion(photo);
        const res = await apiGet(`/api/photos/${photo.date}?thumb=0${ver ? '&v=' + ver : ''}`);
        if (!res.ok) throw new Error('failed to load full photo');
        const blob = await res.blob();
        hdImg.onload = () => {
            statusText.style.display = 'none';
            loader.style.display = 'none';
            hdImg.style.display = 'block';
            hdTs.innerText = '📅 ' + photo.date;
            hdTs.classList.remove('hidden');
        };
        hdImg.src = URL.createObjectURL(blob);
    } catch (e) {
        loader.style.display = 'none';
        statusText.style.display = 'block';
        statusText.innerText = t('fail_hd');
        statusText.style.color = '#ef4444';
    }
}
