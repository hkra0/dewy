// 中英文案与 t()。
const translations = {
    en: {
        // 主导航与通用
        env: "environment", sys: "system", hist: "history", settings: "settings",
        views: "views", device: "device", loading: "loading...", booting: "loading...",
        boot_retry: "retry", boot_enter_anyway: "continue anyway",
        boot_err_network: "cannot reach server, check connection and retry",
        boot_err_pi: "cannot connect to Pi: device offline or tunnel down",
        boot_err_key: "access key invalid or expired, please reopen with latest link",
        boot_err_http: "failed to load node list (HTTP {status})",
        refresh: "refresh", not_synced: "not synced",
        last_synced: "last synced at {time}", conn_lost: "connection lost, showing last known data",

        // 环境视图与卡片
        no_data_node: "no data for this node", temp: "temperature", humidity: "humidity",
        soil_moisture: "soil moisture", soil_adc_raw: "soil ADC", pressure: "pressure",
        other_metrics: "other metrics",
        camera: "camera", cam_alt: "live preview, click to capture high-res image",
        capturing_hd: "capturing hd image...", hd_capture_est: "capturing hd image... (est. 10s+)",
        cam_capturing: "camera is capturing, please wait", cam_offline: "camera hardware offline or error",
        net_disconnect: "network disconnected", fail_hd: "failed to capture hd image",
        photo_viewer: "photo viewer", hd_view: "high-res view", close: "close",
        light_title: "grow light", light_on: "grow light turned on", light_off: "grow light turned off",
        light_fail: "failed to toggle light", state_on: "ON", state_off: "OFF",
        manual_water: "manual watering", duration_s: "Duration (s):", water_btn: "Water",
        watering_cmd: "watering command sent", watering_ing: "watering...", water_fail: "failed to water",
        water_clamped: "Duration must be {min}–{max}s, adjusted",

        // 系统视图
        power_status: "power status", cpu_temp: "cpu temp", ram_used: "ram used", disk_used: "disk storage used",

        // 历史视图
        env_trends: "environmental trends", past_24h: "24h", daily_avg: "day", watering_log: "water",
        photo_log: "photo", chart_loading: "loading...", no_data: "no data available",
        no_water_records: "no watering records found", load_failed: "failed to load, check connection",
        chart_lib_missing: "chart library unavailable",
        chart_temp: "Temp (℃)", chart_hum: "Humidity (%)", chart_soil: "Soil (%)",
        chart_pres: "Pressure (hPa)", chart_water: "Water (s)",
        table_duration: "Duration (s)", table_soil: "Soil Moisture (%)", table_pulses: "Pulses",
        table_soil_after: "Soil After (%)", table_time: "Time", syncing: "syncing...",

        // 照片时间轴与延时导出
        no_photos: "no photos yet", prev_photo: "Previous", play_timelapse: "Play Timelapse",
        next_photo: "Next", playback_speed: "Playback Speed",
        export_timelapse: "Export Timelapse", export_title: "Export Timelapse",
        export_format_label: "Export Format", format_mp4_title: "MP4 Video",
        format_mp4_desc: "High definition, smooth playback, tiny file size",
        format_gif_title: "GIF Animation", format_gif_desc: "Animated image, best for social sharing",
        recommended: "Recommended", export_quality_label: "Quality",
        quality_hd_title: "HD Original (1080p)", quality_hd_desc: "Rendered on Pi from original photos",
        quality_sd_title: "Standard / Fast (480p)", quality_sd_desc: "Rendered from thumbnails, smaller file and faster",
        export_speed_label: "Playback Speed",
        speed_1fps: "1 FPS (1.0s / day)", speed_2fps: "2 FPS (0.5s / day)",
        speed_4fps: "4 FPS (0.25s / day)", speed_8fps: "8 FPS (0.125s / day)",
        export_watermark_label: "Include date watermark",
        export_generating: "Rendering timelapse...", export_generating_hint: "Rendering on Pi server...",
        export_run_in_bg: "Run in Background", export_completed: "Export Completed",
        export_completed_toast: "Timelapse export completed! Click to download.",
        export_notif_title: "Plant Timelapse Ready",
        export_notif_body: "Your plant timelapse is ready. Click to download!",
        export_re_export: "New Export", export_download: "Download Export",
        export_download_ready: "Export Ready ({size})", export_file_size: "File Size: {size}",
        cancel: "Cancel", start_export: "Start Export",
        export_success: "Export completed and downloaded successfully", export_fail: "Export failed: {msg}",
        export_started_toast: "Export started in background. You'll be notified when ready.",
        export_in_progress: "Rendering timelapse ({percent}%)...",
        export_frames_progress: "{current} / {total} frames ({percent}%)",
        export_busy: "An export task is already in progress, please wait",
        export_gif: "GIF", exporting: "creating...", gif_start: "Synthesizing GIF timeline, please wait...",
        gif_success: "GIF downloaded successfully", gif_error: "Failed to generate GIF",
        gif_lib_missing: "GIF library loading, please try again in a moment",
        gif_sampled: "Photos sampled to {n} frames from {total} to prevent memory overflow",

        // 设置页
        auto_water: "Automatic Watering",
        threshold: "Trigger Threshold (%)", water_target: "Target Moisture (%)",
        duration: "Pulse Duration (s)", water_pulse_interval: "Pulse Interval (s)",
        water_max_pulses: "Max Pulses", water_min_interval: "Min Interval (hours)",
        water_thresholds: "Moisture Thresholds",
        water_threshold_hint: "Due to pulse settings and soil characteristics, actual moisture will generally settle higher than the target threshold.",
        water_pulse_config: "Pulse Config",
        sentence_pump: "Pump", sentence_sec_wait: "s, wait", sentence_sec: "s",
        water_limits: "Limits", sentence_max: "Max", sentence_pulses_wait: "pulses. Min wait",
        sentence_hours: "h", water_time_window: "Operating Window",
        pump_safety: "Pump Safety", pump_safety_loading: "Checking safety state...",
        pump_ready: "Ready. Manual and automatic watering are allowed.",
        pump_manual_stopped: "Manual emergency stop is active. All pump commands are blocked.",
        pump_sensor_locked: "Sensor safety interlock is active (recovery {count}/{needed}).",
        pump_both_locked: "Manual emergency stop and sensor safety interlock are both active.",
        pump_emergency_stop: "Emergency stop pump", pump_emergency_release: "Release manual stop",
        pump_stop_set: "Pump emergency stop engaged", pump_stop_released: "Manual stop released",
        pump_stop_fail: "Failed to update pump safety state",
        pump_off_fail: "Safety lock engaged, but the hardware OFF command failed",
        start_hour: "Start Hour", end_hour: "End Hour",
        soil_calibration: "Soil Auto Calibration",
        soil_calibration_desc: "Runs daily in early morning, scanning recent soil ADC history to re-estimate 100% moisture baseline.",
        calib_window_days: "Statistics Window (days)", calib_max_drift: "Max Drift per Update (%)",
        fill_light: "Fill Light", mode: "Mode", fixed_time: "Fixed Time",
        sunrise_sunset: "Sunrise & Sunset", turn_on: "Turn On", turn_off: "Turn Off",
        lat: "Latitude", lng: "Longitude", auto: "auto",
        on_offset: "On Offset (min)", off_offset: "Off Offset (min)",
        currently_scheduled: "Currently scheduled: {on} to {off}",
        photo_capture: "Photo Capture", photo_fill_light: "Fill Light While Capturing",
        daily_photo: "Daily Photo", photo_hour: "Capture Hour (0-23)",
        retake_photo: "Retake Today's Photo", retake_confirm_btn: "Click again to overwrite",
        retake_confirm: "Photo already exists for today. Click again within 3s to overwrite.",
        retaking_btn: "Capturing...", retake_success: "Photo retaken successfully",
        retake_fail: "Retake failed",
        save_cfg: "Save Configuration", saving: "saving...",
        cfg_saved: "Configuration Saved", fail_save: "Failed to save configuration",
        fail_load_cfg: "Failed to load configuration",

        // 节点设置
        node_settings_title: "Node Settings",
        node_settings_desc: "Remote parameters synced to ESP32 node via MQTT",
        cfg_temp_alarm_high: "High Temp Alarm",
        cfg_temp_alarm_low: "Low Temp Alarm",
        cfg_feed_reset_hour: "Daily Feeding Reset Hour",
        fed_yes: "Fed",
        fed_no: "Not Fed",

        // 传感器额外指标
        metric_illuminance: "Illuminance", metric_lux: "Illuminance", metric_co2: "CO₂",
        metric_tvoc: "TVOC", metric_ec: "EC", metric_ph: "pH",
        metric_altitude: "Altitude", metric_gas_resistance: "Gas Resistance",
        metric_battery: "Battery", metric_battery_percent: "Battery", metric_uv_index: "UV Index",
        metric_power: "Power", metric_energy: "Energy",
        metric_pm25: "PM2.5", metric_pm10: "PM10", metric_rssi: "Signal",
        metric_wind_speed: "Wind Speed", metric_rainfall: "Rainfall", metric_noise: "Noise",
        metric_water_temp: "Water Temp", metric_fed: "Feeding Status",
    },
    zh: {
        // 主导航与通用
        env: "环境", sys: "系统", hist: "历史", settings: "设置",
        views: "视图", device: "设备", loading: "加载中...", booting: "加载中...",
        boot_retry: "重试", boot_enter_anyway: "仍然进入",
        boot_err_network: "连不上服务器，请检查网络连接后重试",
        boot_err_pi: "无法连接到树莓派：设备可能已离线，或隧道未运行",
        boot_err_key: "访问密钥无效或已过期，请用最新的分享链接重新打开",
        boot_err_http: "设备列表加载失败（HTTP {status}）",
        refresh: "刷新", not_synced: "未同步",
        last_synced: "最后同步时间: {time}", conn_lost: "连接已断开，显示最后一次数据",

        // 环境视图与卡片
        no_data_node: "该节点暂无数据", temp: "温度", humidity: "湿度",
        soil_moisture: "土壤湿度", soil_adc_raw: "土壤 ADC", pressure: "气压",
        other_metrics: "其它指标",
        camera: "相机", cam_alt: "实时画面，点击获取高清抓拍",
        capturing_hd: "正在拍摄高清图片...", hd_capture_est: "正在拍摄高清图片... (约10秒+)",
        cam_capturing: "相机正在拍摄中，请稍后再试", cam_offline: "相机硬件离线或故障",
        net_disconnect: "网络已断开", fail_hd: "获取高清图片失败",
        photo_viewer: "照片查看器", hd_view: "高清视图", close: "关闭",
        light_title: "补光灯", light_on: "补光灯已开启", light_off: "补光灯已关闭",
        light_fail: "补光灯切换失败", state_on: "开", state_off: "关",
        manual_water: "手动浇水", duration_s: "时长 (秒):", water_btn: "浇水",
        watering_cmd: "指令已发送", watering_ing: "正在浇水...", water_fail: "浇水失败",
        water_clamped: "浇水时长需在 {min}–{max} 秒之间，已自动调整",

        // 系统视图
        power_status: "电源状态", cpu_temp: "处理器温度", ram_used: "内存使用率", disk_used: "存储使用率",

        // 历史视图
        env_trends: "环境趋势", past_24h: "24h", daily_avg: "日均", watering_log: "浇水",
        photo_log: "照片", chart_loading: "图表数据加载中...", no_data: "暂无数据",
        no_water_records: "暂无浇水记录", load_failed: "加载失败，请检查连接",
        chart_lib_missing: "图表组件加载失败",
        chart_temp: "温度 (℃)", chart_hum: "湿度 (%)", chart_soil: "土壤 (%)",
        chart_pres: "气压 (hPa)", chart_water: "浇水 (秒)",
        table_duration: "时长 (秒)", table_soil: "土壤湿度 (%)", table_pulses: "脉冲数",
        table_soil_after: "浇后湿度 (%)", table_time: "时间", syncing: "同步中...",

        // 照片时间轴与延时导出
        no_photos: "暂无照片", prev_photo: "上一张", play_timelapse: "播放延时",
        next_photo: "下一张", playback_speed: "播放速度",
        export_timelapse: "导出延时", export_title: "导出延时摄影",
        export_format_label: "导出格式", format_mp4_title: "MP4 视频",
        format_mp4_desc: "全平台兼容，高画质，体积极小，播放极其流畅",
        format_gif_title: "GIF 动图", format_gif_desc: "动态图片，适合社交分享与动图展示",
        recommended: "推荐", export_quality_label: "画面质量",
        quality_hd_title: "高清原图 (1080p)", quality_hd_desc: "树莓派端基于高清原图流式合成，画面清晰细腻",
        quality_sd_title: "标清快速 (480p)", quality_sd_desc: "使用缩略图合成，文件更小、生成速度更快",
        export_speed_label: "播放速度",
        speed_1fps: "1 FPS (1.0秒 / 天)", speed_2fps: "2 FPS (0.5秒 / 天)",
        speed_4fps: "4 FPS (0.25秒 / 天)", speed_8fps: "8 FPS (0.125秒 / 天)",
        export_watermark_label: "包含日期水印",
        export_generating: "正在合成延时...", export_generating_hint: "由树莓派服务端流式合成中，无需下载海量原图...",
        export_run_in_bg: "后台运行", export_completed: "导出完成",
        export_completed_toast: "延时已生成！点击立即下载",
        export_notif_title: "延时摄影已生成",
        export_notif_body: "植物延时已合成完毕，点击即可下载！",
        export_re_export: "重新导出", export_download: "下载文件",
        export_download_ready: "已有生成好的文件 ({size})", export_file_size: "文件大小: {size}",
        cancel: "取消", start_export: "开始导出",
        export_success: "导出完成，已触发下载", export_fail: "导出失败: {msg}",
        export_started_toast: "已在后台开始导出，完成后将通知您",
        export_in_progress: "正在后台合成延时 ({percent}%)...",
        export_frames_progress: "{current} / {total} 帧 ({percent}%)",
        export_busy: "当前已有导出任务正在进行中，请稍候",
        export_gif: "导出 GIF", exporting: "合成中...", gif_start: "正在合成延时动图，请稍候...",
        gif_success: "GIF 动图已生成", gif_error: "GIF 合成失败，请重试",
        gif_lib_missing: "动图组件准备中，请稍后再试",
        gif_sampled: "照片较多，已从 {total} 张中均匀抽取 {n} 张合成",

        // 设置页
        auto_water: "自动浇水",
        threshold: "触发湿度下限 (%)", water_target: "目标湿度上限 (%)",
        duration: "单次脉冲时长 (秒)", water_pulse_interval: "脉冲间隔 (秒)",
        water_max_pulses: "最大脉冲数", water_min_interval: "最小间隔 (小时)",
        water_thresholds: "湿度阈值",
        water_threshold_hint: "由于脉冲设置和土壤特性，实际湿度一般都会高于设定的目标阈值。",
        water_pulse_config: "脉冲配置",
        sentence_pump: "单次抽水", sentence_sec_wait: "秒，等待", sentence_sec: "秒",
        water_limits: "限制", sentence_max: "最多连续", sentence_pulses_wait: "次脉冲。之后至少等待",
        sentence_hours: "小时", water_time_window: "允许运行时间段",
        pump_safety: "水泵安全", pump_safety_loading: "正在检查安全状态…",
        pump_ready: "安全状态正常，允许手动及自动浇水。",
        pump_manual_stopped: "人工急停已启用，所有水泵指令均被阻止。",
        pump_sensor_locked: "传感器安全联锁已启用（恢复确认 {count}/{needed}）。",
        pump_both_locked: "人工急停与传感器安全联锁均已启用。",
        pump_emergency_stop: "水泵急停", pump_emergency_release: "解除人工急停",
        pump_stop_set: "水泵急停已启用", pump_stop_released: "人工急停已解除",
        pump_stop_fail: "水泵安全状态更新失败",
        pump_off_fail: "安全锁已启用，但硬件断电指令下发失败",
        start_hour: "开始时间 (整点)", end_hour: "结束时间 (整点)",
        soil_calibration: "土壤自动校准",
        soil_calibration_desc: "每天凌晨离线扫描近期土壤 ADC 历史，重新估计 100% 湿度基准。",
        calib_window_days: "统计窗口 (天)", calib_max_drift: "单次最大漂移 (%)",
        fill_light: "补光灯", mode: "模式", fixed_time: "定时",
        sunrise_sunset: "日出 & 日落", turn_on: "开启时间", turn_off: "关闭时间",
        lat: "纬度", lng: "经度", auto: "自动",
        on_offset: "开启偏移 (分钟)", off_offset: "关闭偏移 (分钟)",
        currently_scheduled: "当前计划: {on} 至 {off}",
        photo_capture: "拍照", photo_fill_light: "拍照时开启补光灯",
        daily_photo: "每日照片", photo_hour: "每日拍照时刻 (整点)",
        retake_photo: "重拍当日照片", retake_confirm_btn: "再次点击以覆盖",
        retake_confirm: "当日已有照片，再次点击确认覆盖",
        retaking_btn: "拍摄中...", retake_success: "当日照片已重新拍摄",
        retake_fail: "重拍失败",
        save_cfg: "保存配置", saving: "保存中...",
        cfg_saved: "配置已保存", fail_save: "配置保存失败",
        fail_load_cfg: "配置读取失败",

        // 节点设置
        node_settings_title: "节点设置",
        node_settings_desc: "通过 MQTT 实时同步到 ESP32 节点的运行参数",
        cfg_temp_alarm_high: "高温报警阈值",
        cfg_temp_alarm_low: "低温报警阈值",
        cfg_feed_reset_hour: "每日喂食重置时刻",
        fed_yes: "已喂食",
        fed_no: "未喂食",

        // 传感器额外指标
        metric_illuminance: "光照强度", metric_lux: "光照强度", metric_co2: "二氧化碳",
        metric_tvoc: "挥发性有机物", metric_ec: "电导率", metric_ph: "酸碱度",
        metric_altitude: "海拔", metric_gas_resistance: "气体电阻",
        metric_battery: "电量", metric_battery_percent: "电量", metric_uv_index: "紫外线指数",
        metric_power: "功率", metric_energy: "用电量",
        metric_pm25: "PM2.5", metric_pm10: "PM10", metric_rssi: "信号强度",
        metric_wind_speed: "风速", metric_rainfall: "降雨量", metric_noise: "噪音",
        metric_water_temp: "水温", metric_fed: "喂食状态",
    }
};

export const LANG_KEY = "dewy_lang";
export const SUPPORTED_LANGS = ["en", "zh"];

function detectLang() {
    try {
        const saved = localStorage.getItem(LANG_KEY);
        if (SUPPORTED_LANGS.includes(saved)) return saved;
    } catch (e) {
        // 隐私模式下 localStorage 可能抛异常，退回浏览器语言即可
    }
    const nav = typeof navigator !== "undefined" ? navigator.language : "";
    return (nav && nav.startsWith("zh")) ? "zh" : "en";
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
    document.querySelectorAll("[data-i18n]").forEach(el => {
        const key = el.getAttribute("data-i18n");
        if (key === "currently_scheduled") return; // Handled dynamically
        el.innerText = t(key);
    });

    document.querySelectorAll("[data-i18n-title]").forEach(el => {
        el.setAttribute("title", t(el.getAttribute("data-i18n-title")));
    });

    document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
        el.setAttribute("placeholder", t(el.getAttribute("data-i18n-placeholder")));
    });

    document.querySelectorAll("[data-i18n-aria]").forEach(el => {
        el.setAttribute("aria-label", t(el.getAttribute("data-i18n-aria")));
    });

    document.querySelectorAll("[data-i18n-alt]").forEach(el => {
        el.setAttribute("alt", t(el.getAttribute("data-i18n-alt")));
    });

    // 让屏幕阅读器与浏览器用对语言
    document.documentElement.lang = currentLang;
}
