"""后台主循环：灯控 → 采样归档 → 自动浇水 → 每日照片。

每轮结束后对齐到整点/整十分钟再休眠，使采样时刻稳定，
便于历史图表按固定间隔聚合。
"""

import logging
import time
from datetime import datetime

import core.state as state
import core.config as config
import core.database as db

logger = logging.getLogger(__name__)
from core.database import init_db
from core.logic.light import apply_light_schedule
from core.logic.photo import daily_photo_capture
from core.logic.photo_export import clean_expired_exports
from core.logic.soil_abc import run_abc_calibration
from core.logic.watering import check_auto_watering, clean_soil_anomalies

NORMAL_INTERVAL_SEC = 600    # 正常模式：每 10 分钟一轮
POWER_SAVE_INTERVAL_SEC = 3600  # 省电模式：每小时一轮
ABC_HOUR = 3                 # 每天此时刻之后执行一次土壤 ABC 校准，避开浇水/拍照高峰


def _prune_if_new_day(now, last_prune_date):
    """每天清理一次超期采样与前日导出暂存，返回新的 last_prune_date。

    失败不能影响本轮的其它工作，因此单独兜住异常——
    清理不掉最多是表继续变大，下一天还会再试。
    """
    today = now.date()
    if last_prune_date == today:
        return last_prune_date
    try:
        removed = db.prune_node_data()
        if removed:
            logger.info("🧹 清理超期采样 %d 条（保留 %d 天）",
                        removed, db.NODE_DATA_RETENTION_DAYS)
        clean_expired_exports()
    except Exception:
        logger.exception("清理超期采样与暂存失败，下一天重试")
    return today


def _run_abc_if_new_day(now, last_abc_date):
    """每天 ABC_HOUR 点后执行一次土壤 ABC 校准，返回新的 last_abc_date。

    与 _prune_if_new_day 同一套节流模式：按本地日期变化触发，
    单独兜住异常，一天失败不影响下一天重试。
    """
    today = now.date()
    if last_abc_date == today or now.hour < ABC_HOUR:
        return last_abc_date
    try:
        run_abc_calibration()
    except Exception:
        logger.exception("土壤 ABC 校准失败，下一天重试")
    return today


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
    last_prune_date = None
    last_abc_date = None
    while True:
        try:
            now = datetime.now()

            apply_light_schedule(now)

            node_data_to_save = _collect_node_data(now)
            db.insert_node_data(node_data_to_save)

            for d in node_data_to_save:
                clean_soil_anomalies(d.get("node_id"))

            logger.info("💾 数据归档 (%d 个节点)", len(node_data_to_save))

            # 每日照片拍摄（省电模式下跳过）
            if not state.power_save_mode and config.global_config["daily_photo"]["enabled"]:
                try:
                    daily_photo_capture()
                except Exception:
                    logger.exception("每日照片拍摄失败")

            # 放在本轮最后：清理与 ABC 校准都是维护工作，不该拖慢灯控与采样归档
            last_prune_date = _prune_if_new_day(now, last_prune_date)
            last_abc_date = _run_abc_if_new_day(now, last_abc_date)

        except Exception:
            # 兜底：任何未预料的异常都不能让后台循环退出
            logger.exception("后台记录本轮失败，将在下一轮重试")

        _sleep_until_next_slot()
