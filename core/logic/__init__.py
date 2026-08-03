"""业务逻辑层。

按职责拆分为若干模块，此处汇总导出，
调用方仍可统一写 `from core.logic import xxx`：

    system.py       系统/网络状态查询
    capabilities.py 节点能力（界面该显示什么的唯一判据）
    power.py        UPS 监测与省电模式
    light.py        补光灯定时控制
    watering.py     浇水与土壤离群值过滤
    photo.py        每日照片与磁盘清理
    scheduler.py    后台主循环
"""

from core.logic.system import is_wifi_connected, get_system_stats, get_free_disk_gb
from core.logic.capabilities import node_capabilities
from core.logic.power import local_sensor_updater
from core.logic.light import (
    compute_next_boundary,
    fetch_ip_location,
    get_effective_light_times,
    apply_light_schedule,
    set_light,
    fill_light_for_capture,
)
from core.logic.watering import (
    clean_soil_anomalies,
    can_water_now,
    trigger_watering,
    check_auto_watering,
)
from core.logic.photo import daily_photo_capture, cleanup_old_photos
from core.logic.scheduler import background_logger

__all__ = [
    "is_wifi_connected", "get_system_stats", "get_free_disk_gb",
    "node_capabilities",
    "local_sensor_updater",
    "compute_next_boundary", "fetch_ip_location", "get_effective_light_times", "apply_light_schedule", "set_light",
    "fill_light_for_capture",
    "clean_soil_anomalies", "can_water_now", "trigger_watering", "check_auto_watering",
    "daily_photo_capture", "cleanup_old_photos",
    "background_logger",
]
