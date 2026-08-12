"""土壤 ABC（自动基准校准）编排：取历史数据 -> 统计估计 -> 门控 -> 推送给驱动。

每日调用一次，替代旧的"浇水触发实时校准"链路。统计算法与门控逻辑是纯函数
（``hardware/soil_calibration.py``），本模块只负责取数、按传感器编排、
读用户在设置页调整的全局开关（``core.config``）、隔离单个传感器的失败与
打日志——这几件事都要碰 core.config / core.database / core.state，
所以放在 core/logic 而不是 hardware 层（见 AGENTS.md 的分层约定）。
"""

import logging

import core.config as config
import core.database as db
import core.state as state
from hardware import soil_calibration

logger = logging.getLogger(__name__)


def _calibrate_sensor(node_id, sensor_id, sensor, cfg):
    """对单个传感器执行一轮 ABC 校准。

    cfg 是全局 soil_calibration 配置段（用户经设置页调整的 window_days /
    max_drift_ratio，见 core/config.py），对所有节点上的所有可校准传感器
    统一生效。
    """
    window_days = cfg.get("window_days") or soil_calibration.DEFAULT_WINDOW_DAYS
    max_drift_ratio = cfg.get("max_drift_ratio") or soil_calibration.DEFAULT_MAX_DRIFT_RATIO

    sensor_state = sensor.calibration_state()
    old_val = sensor_state["val_water"]
    factory_val = sensor_state.get("factory_val_water", old_val)
    val_air = sensor_state["val_air"]

    day_values = db.query_soil_adc_series(node_id, days=window_days)
    candidate, valid_days, total_samples = soil_calibration.field_capacity_estimate(day_values)

    if candidate is None:
        logger.info(
            "🌱 ABC 校准跳过 (节点 %s 传感器 %s)：数据不足（%d 天 / %d 条样本）",
            node_id, sensor_id, valid_days, total_samples,
        )
        return

    new_val, reason = soil_calibration.evaluate_update(
        old_val, factory_val, val_air, candidate, max_drift_ratio=max_drift_ratio,
    )

    if new_val is None:
        logger.warning(
            "⚠️ ABC 校准拒绝更新 (节点 %s 传感器 %s): %s", node_id, sensor_id, reason,
        )
        return

    if sensor.apply_calibration(new_val):
        logger.info(
            "✅ ABC 校准完成 (节点 %s 传感器 %s): VAL_WATER %.1f -> %.1f "
            "(候选=%.1f, %d 天 / %d 条样本)",
            node_id, sensor_id, old_val, new_val, candidate, valid_days, total_samples,
        )
    else:
        logger.error("ABC 校准更新被驱动拒绝 (节点 %s 传感器 %s)", node_id, sensor_id)


def run_abc_calibration():
    """遍历所有可校准传感器，逐个执行一轮 ABC 校准。单个传感器失败不影响其它。

    enabled 是设置页的全局开关（`data/config.json` 的 `soil_calibration.enabled`）——
    关掉时整轮直接跳过，不逐个查询数据库。
    """
    cfg = config.global_config.get("soil_calibration", {})
    if not cfg.get("enabled", True):
        logger.debug("ABC 校准已在设置页禁用，跳过本轮")
        return

    for node_id in state.hardware_manager.local_sensors:
        for sensor_id, sensor in state.hardware_manager.calibratable_sensors(node_id).items():
            try:
                _calibrate_sensor(node_id, sensor_id, sensor, cfg)
            except Exception:
                logger.exception("ABC 校准异常 (节点 %s 传感器 %s)", node_id, sensor_id)
