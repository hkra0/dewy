// 设置页：自动浇水 / 补光灯配置的读取与保存。
import { t } from './i18n.js';
import { showToast } from './ui.js';
import { getWaterKey } from './state.js';
import { apiWater, apiWaterPost } from './api.js';

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

export async function fetchConfig() {
    try {
        const res = await apiWater('/api/config');
        const data = await res.json();
        if (data.error) return;

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
        toggleLightMode();
    } catch (e) { console.error(e); }
}

export async function saveConfig() {
    if (!getWaterKey()) return;

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
        } else {
            throw new Error('Failed');
        }
    } catch (e) {
        showToast(t('fail_save'), 'error');

        setTimeout(() => {
            btn.innerText = originalText;

            btn.disabled = false;
        }, 2000);
    }
}
