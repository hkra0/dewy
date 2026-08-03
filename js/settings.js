// 设置页：自动浇水 / 补光灯 / 每日照片配置的读取与保存。
import { t } from './i18n.js';
import { showToast } from './ui.js';
import { getWaterKey } from './state.js';
import { apiWater, apiWaterPost } from './api.js';
import { loadPhotoTimeline } from './timeline.js';

export function toggleLightMode() {
    const mode = document.getElementById('cfg-light-mode').value;
    if (mode === 'fixed') {
        document.getElementById('cfg-light-fixed-group').classList.remove('hidden');
        document.getElementById('cfg-light-sun-group').classList.add('hidden');
    } else {
        document.getElementById('cfg-light-fixed-group').classList.add('hidden');
        document.getElementById('cfg-light-sun-group').classList.remove('hidden');
    }
}

/** 每日照片的子设置（拍照时刻、重新拍摄）跟着开关一起显隐。
 *
 *  与 toggleLightMode 同一套做法：本地即时反馈，不等保存。关掉时收起是因为
 *  这两项此时都没有意义——尤其"重新拍摄"，它拍出来的照片会落进一个同样被
 *  隐藏的时间轴，等于拍了看不到。
 */
export function toggleDailyPhoto() {
    const on = document.getElementById('cfg-photo-enabled').checked;
    document.getElementById('cfg-photo-daily-group').classList.toggle('hidden', !on);
}

export async function fetchConfig() {
    try {
        const res = await apiWater('/api/config');

        // 设置页只对持有浇水密钥的人可见，所以这里的失败不是访客路径——
        // 多半是密钥失效或树莓派掉线，必须让用户看见。
        // 不检查 res.ok 的话，403 会静默返回，留下一屏空输入框。
        if (!res.ok) { showToast(t('fail_load_cfg'), 'error'); return; }

        const data = await res.json();
        if (data.error) { showToast(t('fail_load_cfg'), 'error'); return; }

        document.getElementById('cfg-water-enabled').checked = data.auto_water.enabled;
        document.getElementById('cfg-water-threshold').value = data.auto_water.threshold;
        document.getElementById('cfg-water-duration').value = data.auto_water.duration;
        document.getElementById('cfg-light-enabled').checked = data.auto_light.enabled;
        document.getElementById('cfg-light-mode').value = data.auto_light.mode;
        document.getElementById('cfg-light-on').value = data.auto_light.on_time;
        document.getElementById('cfg-light-off').value = data.auto_light.off_time;
        document.getElementById('cfg-light-on-offset').value = data.auto_light.sun_on_offset;
        document.getElementById('cfg-light-off-offset').value = data.auto_light.sun_off_offset;
        document.getElementById('cfg-light-lat').value = data.auto_light.lat || "";
        document.getElementById('cfg-light-lng').value = data.auto_light.lng || "";
        if (data.effective_light_on && data.effective_light_off) document.getElementById('cfg-light-effective-times').innerText = `` + t('currently_scheduled', { on: data.effective_light_on, off: data.effective_light_off }) + ``;

        // 两个段都可能来自旧版本配置文件，取不到时用后端默认值兜底。
        // 补光在 camera 段而不是 daily_photo 段：它对所有拍摄路径生效。
        const photo = data.daily_photo || {};
        const cam = data.camera || {};
        document.getElementById('cfg-photo-fill-light').checked = cam.fill_light !== false;
        document.getElementById('cfg-photo-enabled').checked = photo.enabled !== false;
        document.getElementById('cfg-photo-hour').value = photo.hour ?? 12;

        toggleLightMode();
        toggleDailyPhoto();
    } catch (e) {
        console.error(e);
        showToast(t('fail_load_cfg'), 'error');
    }
}

/** 保存设置页的全部配置。返回是否保存成功——调用方据此决定要不要重算
 *  界面显隐（每日照片开关会改变"照片"子页签的存在与否）。 */
export async function saveConfig() {
    if (!getWaterKey()) return false;

    const btn = document.getElementById('save-cfg-btn');
    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = t('saving');

    const cfg = {
        auto_water: {
            enabled: document.getElementById('cfg-water-enabled').checked,
            threshold: parseFloat(document.getElementById('cfg-water-threshold').value) || 50.0,
            duration: parseFloat(document.getElementById('cfg-water-duration').value) || 0.5
        },
        auto_light: {
            enabled: document.getElementById('cfg-light-enabled').checked,
            mode: document.getElementById('cfg-light-mode').value,
            on_time: document.getElementById('cfg-light-on').value,
            off_time: document.getElementById('cfg-light-off').value,
            sun_on_offset: parseInt(document.getElementById('cfg-light-on-offset').value) || 0,
            sun_off_offset: parseInt(document.getElementById('cfg-light-off-offset').value) || 0,
            lat: document.getElementById('cfg-light-lat').value,
            lng: document.getElementById('cfg-light-lng').value
        },
        camera: {
            fill_light: document.getElementById('cfg-photo-fill-light').checked
        },
        daily_photo: {
            enabled: document.getElementById('cfg-photo-enabled').checked,
            // 后端按整点判断（背景循环 10 分钟一轮），越界值会让每日照片永远拍不成
            hour: Math.min(23, Math.max(0, parseInt(document.getElementById('cfg-photo-hour').value) || 0))
        }
    };

    try {
        const res = await apiWaterPost('/api/config', cfg);
        if (res.ok) {
            showToast(t('cfg_saved'), 'success');

            setTimeout(() => {
                btn.innerText = originalText;

                btn.disabled = false;
            }, 2000);
            return true;
        } else {
            throw new Error('Failed');
        }
    } catch (e) {
        showToast(t('fail_save'), 'error');

        setTimeout(() => {
            btn.innerText = originalText;

            btn.disabled = false;
        }, 2000);
        return false;
    }
}

// —— 重新拍摄当日照片 ——
//
// 覆盖不可撤销（原图与缩略图都会被换掉），所以要二次确认。确认没有做成
// confirm() 弹窗：那个模态框会打断整页、在移动端尤其突兀，而这里只是一个
// 次要操作。改成"按钮自己变成确认态，三秒后自动退回"——不点第二下就等于取消，
// 不需要用户去点"否"。
//
// 当日**没有**照片时不问：那一下不会覆盖任何东西，弹确认属于噪音。
// 是否已有照片由后端判定（409），不看前端那份可能过期的照片列表——
// 时间轴的缓存有五分钟，靠它判断会漏掉"刚到点自动拍了一张"的情况。
const RETAKE_CONFIRM_MS = 3000;
let retakeConfirmTimer = null;

function disarmRetake(btn) {
    clearTimeout(retakeConfirmTimer);
    retakeConfirmTimer = null;
    btn.classList.remove('confirming');
    btn.innerText = t('retake_photo');
}

function armRetake(btn) {
    btn.classList.add('confirming');
    btn.innerText = t('retake_confirm_btn');
    showToast(t('retake_confirm'), 'error');
    retakeConfirmTimer = setTimeout(() => disarmRetake(btn), RETAKE_CONFIRM_MS);
}

export async function retakeTodayPhoto() {
    if (!getWaterKey()) return;

    const btn = document.getElementById('retake-photo-btn');
    // 处于确认态说明这是三秒内的第二次点击：直接带 force 覆盖。
    const force = retakeConfirmTimer !== null;
    if (force) disarmRetake(btn);

    btn.disabled = true;
    btn.innerText = t('retaking_btn');
    // 这里**不**弹"拍摄中"提示：第一次点击有可能只是撞上 409（当天已有照片，
    // 什么都没拍），弹了就是假消息。HQ 抓拍的十几秒由按钮自己显示状态，
    // 与保存按钮的 saving… 是同一套做法。
    try {
        const res = await apiWaterPost('/api/photo/retake' + (force ? '?force=true' : ''));

        if (res.status === 409) {
            // 当日已有照片，等用户再点一次确认覆盖
            btn.disabled = false;
            armRetake(btn);
            return;
        }

        btn.disabled = false;
        btn.innerText = t('retake_photo');

        if (res.status === 423) { showToast(t('cam_capturing'), 'error'); return; }
        if (!res.ok) { showToast(t('retake_fail'), 'error'); return; }

        showToast(t('retake_success'), 'success');
        // 时间轴的缩略图缓存按 timestamp_size_thumbSize 失效，
        // 重拍已经刷新了 timestamp，这里强拉一次列表就能换成新图。
        loadPhotoTimeline(true);
    } catch (e) {
        console.error(e);
        btn.disabled = false;
        btn.innerText = t('retake_photo');
        showToast(t('retake_fail'), 'error');
    }
}
