// 中英双语文案与翻译工具。无依赖。
const translations = {
    en: {
        env: "environment", sys: "system", hist: "history", settings: "settings",
        camera: "camera", manual_water: "manual watering", duration_s: "Duration (s):", water_btn: "Water",
        power_status: "power status", cpu_temp: "cpu temp", ram_used: "ram used", disk_used: "disk storage used",
        env_trends: "environmental trends", past_24h: "24h", daily_avg: "day", watering_log: "water", chart_loading: "loading...",
        auto_water: "Auto Watering", threshold: "Trigger Threshold (%)", water_target: "Target Moisture (%)", duration: "Pulse Duration (s)", water_pulse_interval: "Pulse Interval (s)", water_max_pulses: "Max Pulses", water_min_interval: "Min Interval (hours)", water_thresholds: "Moisture Thresholds", water_pulse_config: "Pulse Config", water_limits: "Limits", water_time_window: "Operating Window", fill_light: "Fill Light",
        water_threshold_hint: "Due to pulse settings and soil characteristics, actual moisture will generally settle higher than the target threshold.",
        sentence_pump: "Pump", sentence_sec_wait: "s, wait", sentence_sec: "s", sentence_max: "Max", sentence_pulses_wait: "pulses. Min wait", sentence_hours: "h",
        mode: "Mode", fixed_time: "Fixed Time", sunrise_sunset: "Sunrise & Sunset", turn_on: "Turn On", turn_off: "Turn Off",
        lat: "Latitude", lng: "Longitude", on_offset: "On Offset (min)", off_offset: "Off Offset (min)", currently_scheduled: "Currently scheduled: {on} to {off}",
        photo_capture: "Photo Capture", photo_fill_light: "Fill Light While Capturing",
        daily_photo: "Daily Photo", photo_hour: "Daily Capture Hour",
        soil_calibration: "Soil Auto-Calibration",
        soil_calibration_desc: "Nightly, offline: scans recent soil ADC history and re-estimates the 100% moisture baseline.",
        calib_window_days: "Statistics Window (days)", calib_max_drift: "Max Drift per Update (%)",
        retake_photo: "Retake Today's Photo", retake_confirm_btn: "Tap Again to Overwrite",
        retake_confirm: "Today already has a photo, tap again to overwrite",
        retaking_btn: "capturing...", retake_success: "Today's photo has been retaken",
        retake_fail: "Failed to retake today's photo",
        save_cfg: "Save Configuration", refresh: "refresh", capturing_hd: "capturing hd image...", close: "close", not_synced: "not synced",
        saving: "saving...", cfg_saved: "Configuration Saved", fail_save: "Failed to save configuration",
        no_data_node: "no data for this node", temp: "temperature", humidity: "humidity", soil_moisture: "soil moisture", soil_adc_raw: "soil ADC", pressure: "pressure",
        light_title: "fill light", watering_cmd: "Command Sent", watering_ing: "watering...", light_on: "Light turned ON", light_off: "Light turned OFF",
        cam_capturing: "Camera is capturing, try again later", light_fail: "Light toggle failed", water_fail: "Watering failed", no_water_records: "no watering records yet",
        table_duration: "Duration (s)", table_soil: "Soil (%)", table_pulses: "Pulses", table_soil_after: "After (%)", table_time: "Time", no_data: "no data available",
        chart_temp: "temp (℃)", chart_hum: "hum (%)", chart_soil: "soil (%)", chart_pres: "pres (hPa)", chart_water: "water (s)", syncing: "syncing...",
        cam_offline: "camera hardware offline or error", net_disconnect: "network disconnected", hd_capture_est: "capturing hd image... (est. 10s+)",
        conn_lost: "connection lost, showing last known data", chart_lib_missing: "chart library unavailable",
        fail_hd: "failed to capture hd image", last_synced: "last synced at {time}",
        photo_log: "photo", no_photos: "no photos yet",
        export_gif: "GIF", exporting: "creating...", gif_start: "Synthesizing GIF timeline, please wait...", gif_success: "GIF downloaded successfully", gif_error: "Failed to generate GIF", gif_lib_missing: "GIF library loading, please try again in a moment",
        load_failed: "failed to load, check connection", fail_load_cfg: "Failed to load configuration", water_clamped: "Duration must be {min}–{max}s, adjusted",
        gif_sampled: "Sampled {n} of {total} photos to keep the GIF manageable",
        other_metrics: "other metrics", booting: "loading...",
        boot_retry: "retry", boot_enter_anyway: "continue anyway",
        boot_err_network: "Can't reach the server, check your network connection and retry",
        boot_err_pi: "Can't reach the Raspberry Pi. It may be offline, or its tunnel isn't running",
        boot_err_key: "This link's access key is invalid or expired. Open the latest share link again",
        boot_err_http: "Failed to load device list (HTTP {status})",
        metric_illuminance: "illuminance", metric_lux: "illuminance", metric_co2: "co₂",
        metric_tvoc: "tvoc", metric_ec: "conductivity", metric_ph: "ph",
        metric_altitude: "altitude", metric_gas_resistance: "gas resistance",
        metric_battery: "battery", metric_uv_index: "uv index",
        metric_pm25: "pm2.5", metric_pm10: "pm10", metric_rssi: "signal",
    },
    zh: {
        env: "环境", sys: "系统", hist: "历史", settings: "设置",
        camera: "相机", manual_water: "手动浇水", duration_s: "时长 (秒):", water_btn: "浇水",
        power_status: "电源状态", cpu_temp: "处理器温度", ram_used: "内存使用率", disk_used: "存储使用率",
        env_trends: "环境趋势", past_24h: "24h", daily_avg: "日均", watering_log: "浇水", chart_loading: "加载中...",
        auto_water: "自动浇水", threshold: "触发湿度下限 (%)", water_target: "目标湿度上限 (%)", duration: "单次脉冲时长 (秒)", water_pulse_interval: "脉冲间隔 (秒)", water_max_pulses: "最大脉冲数", water_min_interval: "最小间隔 (小时)", water_thresholds: "湿度阈值", water_pulse_config: "脉冲配置", water_limits: "限制", water_time_window: "允许运行时间段", fill_light: "补光灯",
        water_threshold_hint: "由于脉冲设置和土壤特性，实际湿度一般都会高于设定的目标阈值。",
        sentence_pump: "单次抽水", sentence_sec_wait: "秒，等待", sentence_sec: "秒", sentence_max: "最多连续", sentence_pulses_wait: "次脉冲。之后至少等待", sentence_hours: "小时",
        mode: "模式", fixed_time: "定时", sunrise_sunset: "日出 & 日落", turn_on: "开启时间", turn_off: "关闭时间",
        lat: "纬度", lng: "经度", on_offset: "开启偏移 (分钟)", off_offset: "关闭偏移 (分钟)", currently_scheduled: "当前计划: {on} 至 {off}",
        photo_capture: "拍照", photo_fill_light: "拍照时开启补光灯",
        daily_photo: "每日照片", photo_hour: "每日拍照时刻 (整点)",
        soil_calibration: "土壤自动校准",
        soil_calibration_desc: "每天凌晨离线扫描近期土壤 ADC 历史，重新估计 100% 湿度基准。",
        calib_window_days: "统计窗口 (天)", calib_max_drift: "单次最大漂移 (%)",
        retake_photo: "重拍当日照片", retake_confirm_btn: "再次点击以覆盖",
        retake_confirm: "当日已有照片，再次点击确认覆盖",
        retaking_btn: "拍摄中...", retake_success: "当日照片已重新拍摄",
        retake_fail: "重拍失败",
        save_cfg: "保存配置", refresh: "刷新", capturing_hd: "正在拍摄高清图片...", close: "关闭", not_synced: "未同步",
        saving: "保存中...", cfg_saved: "配置已保存", fail_save: "配置保存失败",
        no_data_node: "该节点暂无数据", temp: "温度", humidity: "湿度", soil_moisture: "土壤湿度", soil_adc_raw: "土壤 ADC", pressure: "气压",
        light_title: "补光灯", watering_cmd: "指令已发送", watering_ing: "正在浇水...", light_on: "补光灯已开启", light_off: "补光灯已关闭",
        cam_capturing: "相机正在拍摄中，请稍后再试", light_fail: "补光灯切换失败", water_fail: "浇水失败", no_water_records: "暂无浇水记录",
        table_duration: "时长 (秒)", table_soil: "土壤湿度 (%)", table_pulses: "脉冲数", table_soil_after: "浇后湿度 (%)", table_time: "时间", no_data: "暂无数据",
        chart_temp: "温度 (℃)", chart_hum: "湿度 (%)", chart_soil: "土壤 (%)", chart_pres: "气压 (hPa)", chart_water: "浇水 (秒)", syncing: "同步中...",
        cam_offline: "相机硬件离线或故障", net_disconnect: "网络已断开", hd_capture_est: "正在拍摄高清图片... (约10秒+)",
        conn_lost: "连接已断开，显示最后一次数据", chart_lib_missing: "图表组件加载失败",
        fail_hd: "获取高清图片失败", last_synced: "最后同步时间: {time}",
        photo_log: "照片", no_photos: "暂无照片",
        export_gif: "导出 GIF", exporting: "合成中...", gif_start: "正在高速合成延时动图，请稍候...", gif_success: "GIF 动图已生成", gif_error: "GIF 合成失败，请重试", gif_lib_missing: "动图组件准备中，请稍后再试",
        load_failed: "加载失败，请检查连接", fail_load_cfg: "配置读取失败", water_clamped: "浇水时长需在 {min}–{max} 秒之间，已自动调整",
        gif_sampled: "照片较多，已从 {total} 张中均匀抽取 {n} 张合成",
        other_metrics: "其它指标", booting: "加载中...",
        boot_retry: "重试", boot_enter_anyway: "仍然进入",
        boot_err_network: "连不上服务器，请检查网络连接后重试",
        boot_err_pi: "无法连接到树莓派：设备可能已离线，或隧道未运行",
        boot_err_key: "访问密钥无效或已过期，请用最新的分享链接重新打开",
        boot_err_http: "设备列表加载失败（HTTP {status}）",
        metric_illuminance: "光照强度", metric_lux: "光照强度", metric_co2: "二氧化碳",
        metric_tvoc: "挥发性有机物", metric_ec: "电导率", metric_ph: "酸碱度",
        metric_altitude: "海拔", metric_gas_resistance: "气体电阻",
        metric_battery: "电量", metric_uv_index: "紫外线指数",
        metric_pm25: "pm2.5", metric_pm10: "pm10", metric_rssi: "信号强度",
    }
};


export const LANG_KEY = 'dewy_lang';
export const SUPPORTED_LANGS = ['en', 'zh'];

// 语言默认跟 navigator.language，没有界面控件——**这是刻意的**。
//
// 页面本身只有四个 tab，任何常驻的语言开关都会和主导航抢视觉权重，
// 显得比实际功能还重要；而设置页要浇水密钥才可见，访客够不着。
// 覆盖走链接参数（见 navigation.js 的 checkMagicLink）：
//     https://…/?lang=zh    或    https://…/#key=xxx&lang=zh
// 这跟本项目已有的魔法链接是同一套习惯，不是新机制，而且零像素占用。
// 覆盖值落进 localStorage，之后一直生效，链接只需要发一次。
function detectLang() {
    try {
        const saved = localStorage.getItem(LANG_KEY);
        if (SUPPORTED_LANGS.includes(saved)) return saved;
    } catch (e) {
        // 隐私模式下 localStorage 可能抛异常，退回浏览器语言即可
    }
    const nav = typeof navigator !== 'undefined' ? navigator.language : '';
    return (nav && nav.startsWith('zh')) ? 'zh' : 'en';
}

let currentLang = detectLang();

/** 记住语言覆盖。由 checkMagicLink 在首屏渲染前调用，所以不需要重绘。
 *
 *  返回"生效语言是否发生了变化"。
 */
export function setLang(lang) {
    if (!SUPPORTED_LANGS.includes(lang)) return false;

    // 即使与当前生效值相同也要落盘：这是用户的显式选择，不该因为"碰巧和
    // navigator.language 一致"就不被记住——否则哪天浏览器语言变了，
    // 这个选择会静默失效。落盘与"是否需要重绘"是两件事。
    try {
        localStorage.setItem(LANG_KEY, lang);
    } catch (e) {
        // 存不下就只在本次会话生效
    }

    if (lang === currentLang) return false;
    currentLang = lang;
    return true;
}

function t(key, replacements = {}) {
    let text = translations[currentLang][key] || key;
    for (let k in replacements) {
        text = text.replace(`{${k}}`, replacements[k]);
    }
    return text;
}

/** 带兜底的翻译：查不到就用调用方给的 fallback，而不是把 key 显示出来。
 *
 *  给字段名不可预知的场合用（额外指标的标签）——那里 key 是运行时才知道的，
 *  未收录是常态而非疏漏，直接显示 "metric_co2" 才是错的。
 */
export function tf(key, fallback) {
    return translations[currentLang][key] || fallback;
}

export { t };

export function applyTranslations() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (key === 'currently_scheduled') return; // Handled dynamically
        el.innerText = t(key);
    });

    // 让屏幕阅读器与浏览器用对语言（index.html 里写死的是 lang="en"）
    document.documentElement.lang = currentLang;
}
