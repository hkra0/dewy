"""浇水控制：脉冲式闭环浇水与土壤读数的离群值过滤。

脉冲浇水流程：
  触发条件：soil_moisture < threshold（触发下限）且距上次浇水超过 min_interval_hours
  执行过程：循环（最多 max_pulses 次）→ 启泵 duration 秒 → 等待 pulse_interval 秒
            → 读取实时土壤湿度 → 达到 target_moisture（目标上限）即停止
  安全机制：最大脉冲数限制防止传感器故障导致无限泵水
"""

import logging
import time
from datetime import datetime

import core.state as state
import core.config as config
import core.database as db

logger = logging.getLogger(__name__)

DEFAULT_PUMP_ACTUATOR_ID = "pump"


def _pump_actuator_id():
    """水泵执行器在 hardware_config 里的 id。

    别人的接线未必也叫 pump（多株植物常见 pump_a / pump_b），
    因此可在 data/config.json 的 auto_water.actuator_id 里改。
    """
    return config.global_config["auto_water"].get("actuator_id", DEFAULT_PUMP_ACTUATOR_ID)


def clean_soil_anomalies(node_id):
    """浇水后土壤读数会短暂跳变，把这类突刺标记为离群值以免污染图表。"""
    rows = db.query_recent_soil(node_id, limit=5)

    if len(rows) < 3: return
    current_soil = rows[0][1]
    last_soil = rows[1][1]

    if current_soil is not None and last_soil is not None and current_soil - last_soil > 10:
        anomaly_ids = []
        if last_soil < 10 and len(rows) >= 3 and rows[2][1] is not None and (rows[2][1] - last_soil > 5): anomaly_ids = [rows[1][0]]
        elif last_soil < 10 and len(rows) >= 4 and rows[2][1] is not None and rows[2][1] < 10 and rows[3][1] is not None and (rows[3][1] - rows[2][1] > 5): anomaly_ids = [rows[1][0], rows[2][0]]
        elif last_soil < 10 and len(rows) >= 5 and rows[2][1] is not None and rows[2][1] < 10 and rows[3][1] is not None and rows[3][1] < 10 and rows[4][1] is not None and (rows[4][1] - rows[3][1] > 5): anomaly_ids = [rows[1][0], rows[2][0], rows[3][0]]

        db.mark_anomalies(anomaly_ids)


def can_water_now(node_id, min_interval_hours=12):
    """距上次浇水是否已超过最小间隔。读库失败时返回 False（宁可不浇）。"""
    try:
        last_ts = db.query_last_watering_time(node_id)
        if not last_ts: return True
        last_utc = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
        diff_hours = (datetime.utcnow() - last_utc).total_seconds() / 3600
        return diff_hours > min_interval_hours
    except Exception:
        logger.exception("浇水间隔判定失败，本次不浇水")
        return False


def trigger_watering(node_id, soil_before, duration=None,
                     pulse_count=1, soil_after=None):
    """驱动水泵并记录浇水日志。手动浇水与自动浇水共用此入口。

    pulse_count / soil_after 由脉冲浇水在结束后传入，
    手动浇水保持默认值（pulse_count=1, soil_after=None）。
    """
    if duration is None: duration = config.global_config["auto_water"]["duration"]

    pump_id = _pump_actuator_id()
    logger.info("💦 开启水泵 (Node: %s), 时长: %ss", node_id, duration)
    success = state.hardware_manager.trigger_actuator(node_id, pump_id, duration=duration)

    if success:
        db.insert_watering(node_id, duration, soil_before,
                           pulse_count=pulse_count, soil_after=soil_after)
        return True
    else:
        logger.error("❌ 浇水失败：节点 %s 未配置 %s 继电器或硬件异常", node_id, pump_id)
        return False


def _read_soil_moisture(node_id):
    """实时读取土壤湿度。读取失败返回 None。"""
    try:
        data = state.hardware_manager.read_local_node(node_id)
        if data:
            # 同时更新 local_latest_data，使前端轮询也能看到最新值
            state.local_latest_data[node_id] = data
            return data.get("soil_moisture")
    except Exception:
        logger.exception("脉冲浇水期间读取土壤湿度失败 (Node: %s)", node_id)
    return None


def pulse_watering(node_id, soil_before):
    """脉冲式闭环浇水。

    循环：启泵 → 等待渗透 → 读湿度 → 判断是否达标。
    达到目标上限或用完最大脉冲数后停止，记录一条带脉冲数和浇后湿度的日志。

    在 background_logger 的主循环里调用，会阻塞主循环（最多 max_pulses ×
    pulse_interval 秒）。考虑到浇水最多每天一次，且阻塞时间与正常采样间隔
    相当（~10 分钟），不拆成独立线程——水泵与传感器共用 I2C 总线锁，
    异步化的复杂度收益不对等。
    """
    cfg = config.global_config["auto_water"]
    duration = cfg["duration"]
    target = cfg.get("target_moisture", 85.0)
    interval = cfg.get("pulse_interval", 60)
    max_pulses = cfg.get("max_pulses", 10)

    pump_id = _pump_actuator_id()
    pulse_count = 0
    soil_current = soil_before

    logger.info("🌊 开始脉冲浇水 (Node: %s) 起始湿度: %.1f%%, 目标: %.1f%%, "
                "每脉冲 %.1fs, 间隔 %ds, 上限 %d 次",
                node_id, soil_before, target, duration, interval, max_pulses)

    for i in range(max_pulses):
        # 启泵
        logger.info("💦 脉冲 %d/%d (Node: %s), 时长: %.1fs",
                     i + 1, max_pulses, node_id, duration)
        success = state.hardware_manager.trigger_actuator(
            node_id, pump_id, duration=duration)
        if not success:
            logger.error("❌ 脉冲 %d 泵启动失败，终止浇水", i + 1)
            break
        pulse_count += 1

        # 等待水分渗透和传感器响应
        time.sleep(interval)

        # 读取实时湿度
        soil_current = _read_soil_moisture(node_id)
        if soil_current is None:
            logger.warning("⚠️ 脉冲 %d 后读不到土壤湿度，继续下一脉冲", i + 1)
            continue

        logger.info("📊 脉冲 %d 后湿度: %.1f%% (目标: %.1f%%)",
                     i + 1, soil_current, target)

        if soil_current >= target:
            logger.info("✅ 达到目标湿度 (%.1f%% >= %.1f%%)，停止浇水",
                        soil_current, target)
            break
    else:
        logger.warning("⚠️ 已达最大脉冲数 %d 次 (当前湿度: %s%%)",
                       max_pulses,
                       f"{soil_current:.1f}" if soil_current is not None else "N/A")

    # 记录整次浇水会话。duration 记总时长（脉冲数 × 单次时长）。
    total_duration = round(pulse_count * duration, 2)
    db.insert_watering(node_id, total_duration, soil_before,
                       pulse_count=pulse_count, soil_after=soil_current)

    logger.info("📝 浇水完成 (Node: %s): %d 脉冲, 总时长 %.1fs, "
                "湿度 %.1f%% → %s%%",
                node_id, pulse_count, total_duration, soil_before,
                f"{soil_current:.1f}" if soil_current is not None else "N/A")


def check_auto_watering(node_id, data, now):
    """每轮采样后判断该节点是否需要自动浇水。

    判断逻辑：
    1. 未处于省电模式、自动浇水已启用、是配置指定的节点
    2. 当前时刻在 start_hour 和 end_hour 组成的时间窗口内
    3. 距上次浇水已超过 min_interval_hours
    4. 当前土壤湿度 < threshold（触发下限）
    满足以上全部条件后执行脉冲浇水。
    """
    cfg = config.global_config["auto_water"]
    if state.power_save_mode or not cfg["enabled"] or cfg["node_id"] != node_id:
        return

    # 2. 当前时刻在允许浇水的时间窗口内（支持跨天）
    start = cfg.get("start_hour", 6)
    end = cfg.get("end_hour", 20)
    
    if start <= end:
        in_window = start <= now.hour < end
    else:
        # 跨天区间，如 22:00 ~ 06:00
        in_window = now.hour >= start or now.hour < end
        
    if not in_window:
        return

    min_interval = cfg.get("min_interval_hours", 12)
    if not can_water_now(node_id, min_interval):
        return

    soil_pct = data.get("soil_moisture")
    if soil_pct is not None and soil_pct < cfg["threshold"]:
        pulse_watering(node_id, soil_pct)
