"""后台主循环：灯控 → 采样归档 → 自动浇水 → 每日照片。

每轮结束后对齐到整点/整十分钟再休眠，使采样时刻稳定，
便于历史图表按固定间隔聚合。
"""

import time
from datetime import datetime

import core.state as state
import core.config as config
import core.database as db
from core.database import init_db
from core.logic.light import apply_light_schedule
from core.logic.photo import daily_photo_capture
from core.logic.watering import check_auto_watering, clean_soil_anomalies

NORMAL_INTERVAL_SEC = 600    # 正常模式：每 10 分钟一轮
POWER_SAVE_INTERVAL_SEC = 3600  # 省电模式：每小时一轮


def _collect_node_data(now):
    """汇总本地传感器与 MQTT 节点的最新读数，顺带处理自动浇水。"""
    node_data_to_save = []

    for node_id in state.hardware_manager.local_sensors:
        data = state.local_latest_data.get(node_id, {})
        if data:
            data = data.copy()
            data["node_id"] = node_id
            node_data_to_save.append(data)

        check_auto_watering(node_id, data, now)

    for node_id, info in state.mqtt_latest_data.items():
        if info["updated"]:
            data = info["data"].copy()
            data["node_id"] = node_id
            node_data_to_save.append(data)
            info["updated"] = False

    return node_data_to_save


def _sleep_until_next_slot():
    """休眠到下一个对齐时刻。"""
    now = datetime.now()
    seconds_passed = now.minute * 60 + now.second + now.microsecond / 1_000_000

    align_interval = POWER_SAVE_INTERVAL_SEC if state.power_save_mode else NORMAL_INTERVAL_SEC
    sleep_sec = align_interval - (seconds_passed % align_interval)
    time.sleep(max(0.1, sleep_sec))


def background_logger():
    init_db()
    while True:
        try:
            now = datetime.now()

            apply_light_schedule(now)

            node_data_to_save = _collect_node_data(now)
            db.insert_node_data(node_data_to_save)

            for d in node_data_to_save:
                clean_soil_anomalies(d.get("node_id"))

            print(f"[{now.strftime('%H:%M:%S')}] 💾 数据归档")

            # 每日照片拍摄（省电模式下跳过）
            if not state.power_save_mode and config.global_config["daily_photo"]["enabled"]:
                try:
                    daily_photo_capture()
                except Exception as e:
                    print(f"每日照片拍摄失败: {e}")

        except Exception as e:
            print(f"后台记录失败: {e}")

        _sleep_until_next_slot()
