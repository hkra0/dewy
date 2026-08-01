"""浇水控制与土壤读数的离群值过滤。"""

from datetime import datetime

import core.state as state
import core.config as config
import core.database as db

MIN_WATER_INTERVAL_HOURS = 12   # 两次自动浇水的最小间隔
AUTO_WATER_HOUR = 6             # 每天检查自动浇水的时刻
PUMP_ACTUATOR_ID = "pump"


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


def can_water_now(node_id):
    """距上次浇水是否已超过最小间隔。读库失败时返回 False（宁可不浇）。"""
    try:
        last_ts = db.query_last_watering_time(node_id)
        if not last_ts: return True
        last_utc = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
        diff_hours = (datetime.utcnow() - last_utc).total_seconds() / 3600
        return diff_hours > MIN_WATER_INTERVAL_HOURS
    except Exception:
        return False


def trigger_watering(node_id, soil_before, duration=None):
    """驱动水泵并记录浇水日志。手动浇水与自动浇水共用此入口。"""
    if duration is None: duration = config.global_config["auto_water"]["duration"]

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 💦 开启水泵 (Node: {node_id}), 时长: {duration}s")
    success = state.hardware_manager.trigger_actuator(node_id, PUMP_ACTUATOR_ID, duration=duration)

    if success:
        db.insert_watering(node_id, duration, soil_before)
        return True
    else:
        print(f"❌ 浇水异常或未配置对应继电器")
        return False


def check_auto_watering(node_id, data, now):
    """每轮采样后判断该节点是否需要自动浇水。"""
    cfg = config.global_config["auto_water"]
    if state.power_save_mode or not cfg["enabled"] or cfg["node_id"] != node_id:
        return

    if now.hour == AUTO_WATER_HOUR and can_water_now(node_id):
        soil_pct = data.get("soil_moisture")
        if soil_pct is not None and soil_pct < cfg["threshold"]:
            trigger_watering(node_id, soil_pct, cfg["duration"])
