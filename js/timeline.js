// 照片时间轴播放器与 GIF 导出。
import { t } from './i18n.js';
import { showToast } from './ui.js';
import { state, getViewerKey, nodeCaps } from './state.js';
import { apiGet } from './api.js';
import { ensureGifshot } from './cdn.js';

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
    if (!getViewerKey() || !nodeCaps().daily_photo) return;

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
    // alt 不能留空串：这张图是页面主内容，不是装饰
    imgEl.alt = `plant photo ${photo.date}`;
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

// GIF 导出的两道闸门。
//
// 每张照片都是一次 浏览器→Cloudflare→隧道→树莓派 的往返。不限帧数、不控并发
// 的话，几百张就是几百次串行往返，而且几百个 data URL 会同时驻留内存喂给
// gifshot——手机上基本等于卡死或标签页崩溃。
//
// 按项目自己的保留策略（近 7 天必留 + 对数稀疏化），照片总数只增不减，
// 所以上限是必需的，不是保险。
const GIF_MAX_FRAMES = 120;
const GIF_FETCH_CONCURRENCY = 5;

/** 超过上限时均匀抽样，并保证首尾两帧一定入选（延时动图的起止最有信息量）。 */
export function selectGifFrames(photos, max = GIF_MAX_FRAMES) {
    if (photos.length <= max) return photos;
    const step = (photos.length - 1) / (max - 1);
    const picked = [];
    for (let i = 0; i < max; i++) picked.push(photos[Math.round(i * step)]);
    return picked;
}

/** 并发拉取并水印化所有帧，返回值按原顺序排列（失败的帧被剔除）。 */
async function buildGifFrames(photos, onProgress) {
    const frames = new Array(photos.length).fill(null);
    let nextIdx = 0;
    let done = 0;

    // 单线程 JS：nextIdx++ 与后面的 await 之间没有让出点，不会取到重复下标。
    async function worker() {
        for (let i = nextIdx++; i < photos.length; i = nextIdx++) {
            const photo = photos[i];
            let imgUrl = tlThumbCache.get(photo.date);
            let tempBlobUrl = null;

            if (!imgUrl) {
                try {
                    const ver = getPhotoVersion(photo);
                    const res = await apiGet(`/api/photos/${photo.date}?thumb=1${ver ? '&v=' + ver : ''}`);
                    if (res.ok) {
                        tempBlobUrl = URL.createObjectURL(await res.blob());
                        imgUrl = tempBlobUrl;
                    }
                } catch (err) {
                    console.error(`Error fetching frame ${photo.date}`, err);
                }
            }

            if (imgUrl) frames[i] = await createWatermarkedFrame(imgUrl, photo.date);
            // 临时 blob 用完即释放，不进 tlThumbCache（那是播放器的 LRU，
            // 导出一次就把它冲掉不划算）
            if (tempBlobUrl) URL.revokeObjectURL(tempBlobUrl);

            onProgress(++done);
        }
    }

    const pool = Math.min(GIF_FETCH_CONCURRENCY, photos.length);
    await Promise.all(Array.from({ length: pool }, worker));
    return frames.filter(Boolean);
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

export async function exportTimelineGIF() {
    if (!tlPhotos || tlPhotos.length === 0) return;
    const btn = document.getElementById('tl-export-btn');
    if (!btn || btn.disabled) return;

    if (typeof gifshot === 'undefined') {
        showToast(t('gif_lib_missing'), 'info');
        btn.disabled = true;
        btn.innerText = '⏳...';
        const loaded = await ensureGifshot();
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

    let gifWidth = 480, gifHeight = 360;

    try {
        const selected = selectGifFrames(tlPhotos);
        if (selected.length < tlPhotos.length) {
            showToast(t('gif_sampled', { n: selected.length, total: tlPhotos.length }), 'info');
        }

        // 前 50% 进度用于拉取+水印，后 50% 交给 gifshot 的 progressCallback
        const frames = await buildGifFrames(selected, (done) => {
            btn.innerText = `${Math.round((done / selected.length) * 50)}%`;
        });

        if (frames.length === 0) {
            throw new Error("No frames loaded");
        }

        const frameUrls = frames.map(f => f.dataUrl);
        gifWidth = frames[0].width;
        gifHeight = frames[0].height;

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
        statusText.style.color = 'var(--danger)';
    }
}
