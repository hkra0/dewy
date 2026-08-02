// 中英双语文案与翻译工具。无依赖。
const translations = {
    en: {
        env: "environment", sys: "system", hist: "history", settings: "settings",
        camera: "camera", manual_water: "manual watering", duration_s: "Duration (s):", water_btn: "Water",
        power_status: "power status", cpu_temp: "cpu temp", ram_used: "ram used", disk_used: "disk storage used",
        env_trends: "environmental trends", past_24h: "24h", daily_avg: "day", watering_log: "water", chart_loading: "loading...",
        auto_water: "Auto Watering", threshold: "Threshold (%)", duration: "Duration (s)", fill_light: "Fill Light",
        mode: "Mode", fixed_time: "Fixed Time", sunrise_sunset: "Sunrise & Sunset", turn_on: "Turn On", turn_off: "Turn Off",
        lat: "Latitude", lng: "Longitude", on_offset: "On Offset (min)", off_offset: "Off Offset (min)", currently_scheduled: "Currently scheduled: {on} to {off}",
        save_cfg: "Save Configuration", refresh: "refresh", capturing_hd: "capturing hd image...", close: "close", not_synced: "not synced",
        saving: "saving...", cfg_saved: "Configuration Saved!", fail_save: "Failed to save configuration.",
        no_data_node: "no data for this node", temp: "temperature", humidity: "humidity", soil_moisture: "soil moisture", pressure: "pressure",
        light_title: "fill light", watering_cmd: "Watering Command Sent!", watering_ing: "watering...", light_on: "Light turned ON", light_off: "Light turned OFF",
        cam_capturing: "Camera is capturing, try again later", light_fail: "Light toggle failed", no_water_records: "no watering records yet.",
        table_duration: "Duration (s)", table_soil: "Soil (%)", table_time: "Time", no_data: "no data available.",
        chart_temp: "temp (℃)", chart_hum: "hum (%)", chart_soil: "soil (%)", chart_pres: "pres (hPa)", chart_water: "water (s)", syncing: "syncing...",
        cam_offline: "camera hardware offline or error", net_disconnect: "network disconnected", hd_capture_est: "capturing hd image... (est. 10s+)",
        fail_hd: "failed to capture hd image", last_synced: "last synced at {time}",
        photo_log: "photo", no_photos: "no photos yet",
        export_gif: "GIF", exporting: "creating...", gif_start: "Synthesizing GIF timeline, please wait...", gif_success: "GIF downloaded successfully", gif_error: "Failed to generate GIF.", gif_lib_missing: "GIF library loading, please try again in a moment."
    },
    zh: {
        env: "环境", sys: "系统", hist: "历史", settings: "设置",
        camera: "相机", manual_water: "手动浇水", duration_s: "时长 (秒):", water_btn: "浇水",
        power_status: "电源状态", cpu_temp: "处理器温度", ram_used: "内存使用率", disk_used: "存储使用率",
        env_trends: "环境趋势", past_24h: "24h", daily_avg: "日均", watering_log: "浇水", chart_loading: "加载中...",
        auto_water: "自动浇水", threshold: "湿度阈值 (%)", duration: "浇水时长 (秒)", fill_light: "补光灯",
        mode: "模式", fixed_time: "定时", sunrise_sunset: "日出 & 日落", turn_on: "开启时间", turn_off: "关闭时间",
        lat: "纬度", lng: "经度", on_offset: "开启偏移 (分钟)", off_offset: "关闭偏移 (分钟)", currently_scheduled: "当前计划: {on} 至 {off}",
        save_cfg: "保存配置", refresh: "刷新", capturing_hd: "正在拍摄高清图片...", close: "关闭", not_synced: "未同步",
        saving: "保存中...", cfg_saved: "配置已保存！", fail_save: "配置保存失败。",
        no_data_node: "该节点暂无数据", temp: "温度", humidity: "湿度", soil_moisture: "土壤湿度", pressure: "气压",
        light_title: "补光灯", watering_cmd: "浇水指令已发送！", watering_ing: "正在浇水...", light_on: "补光灯已开启", light_off: "补光灯已关闭",
        cam_capturing: "相机正在拍摄中，请稍后再试", light_fail: "补光灯切换失败", no_water_records: "暂无浇水记录。",
        table_duration: "时长 (秒)", table_soil: "土壤湿度 (%)", table_time: "时间", no_data: "暂无数据。",
        chart_temp: "温度 (℃)", chart_hum: "湿度 (%)", chart_soil: "土壤 (%)", chart_pres: "气压 (hPa)", chart_water: "浇水 (秒)", syncing: "同步中...",
        cam_offline: "相机硬件离线或故障", net_disconnect: "网络已断开", hd_capture_est: "正在拍摄高清图片... (约10秒+)",
        fail_hd: "获取高清图片失败。", last_synced: "最后同步时间: {time}",
        photo_log: "照片", no_photos: "暂无照片",
        export_gif: "导出 GIF", exporting: "合成中...", gif_start: "正在高速合成延时动图，请稍候...", gif_success: "GIF 动图已生成", gif_error: "GIF 合成失败，请重试。", gif_lib_missing: "动图组件准备中，请稍后再试"
    }
};


let currentLang = (typeof navigator !== 'undefined' && navigator.language && navigator.language.startsWith('zh')) ? 'zh' : 'en';
function t(key, replacements = {}) {
    let text = translations[currentLang][key] || key;
    for (let k in replacements) {
        text = text.replace(`{${k}}`, replacements[k]);
    }
    return text;
}

export { t };

export function applyTranslations() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (key === 'currently_scheduled') return; // Handled dynamically
        el.innerText = t(key);
    });
}
