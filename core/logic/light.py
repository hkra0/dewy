"""补光灯定时控制。

两种模式：fixed（固定时刻）与日出日落（按经纬度实时推算，支持偏移量）。
手动切灯会置 manual_override，到下一个开/关边界自动失效。
"""

import json
import logging
import math
import time
import urllib.error
import urllib.request
from datetime import timedelta

import core.state as state
import core.config as config

logger = logging.getLogger(__name__)

DEFAULT_ON_MINUTES = 7 * 60 + 30    # 推算失败时的兜底：07:30
DEFAULT_OFF_MINUTES = 21 * 60 + 30  # 兜底：21:30


def compute_next_boundary(now, on_minutes, off_minutes):
    """手动覆盖的失效时刻：下一个开灯或关灯边界。"""
    current_minutes = now.hour * 60 + now.minute
    boundaries = [on_minutes, off_minutes]

    next_boundary = None
    for b in sorted(boundaries):
        if b > current_minutes:
            next_boundary = b
            break

    if next_boundary is None:
        next_boundary = min(boundaries)
        target = now.replace(hour=next_boundary // 60, minute=next_boundary % 60, second=0, microsecond=0)
        target += timedelta(days=1)
    else:
        target = now.replace(hour=next_boundary // 60, minute=next_boundary % 60, second=0, microsecond=0)

    return target


def fetch_ip_location():
    """按出口 IP 猜经纬度。失败返回 (None, None)，调用方会退回默认时段。"""
    try:
        req = urllib.request.urlopen("http://ip-api.com/json", timeout=3)
        data = json.loads(req.read())
        return data.get("lat"), data.get("lon")
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.warning("IP 定位失败，无法推算日出日落: %s", e)
        return None, None


def get_effective_light_times():
    """返回当天生效的 (开灯分钟数, 关灯分钟数)。任何异常都退回默认时段。"""
    cfg = config.global_config["auto_light"]
    if cfg["mode"] == "fixed":
        try:
            on_h, on_m = map(int, cfg["on_time"].split(":"))
            off_h, off_m = map(int, cfg["off_time"].split(":"))
            return on_h * 60 + on_m, off_h * 60 + off_m
        except (KeyError, ValueError, AttributeError) as e:
            logger.error("固定时段配置非法 (on=%r off=%r)，退回默认 07:30-21:30: %s",
                         cfg.get("on_time"), cfg.get("off_time"), e)
            return DEFAULT_ON_MINUTES, DEFAULT_OFF_MINUTES
    else:
        lat, lng = cfg.get("lat"), cfg.get("lng")
        if not lat or not lng:
            lat, lng = fetch_ip_location()
            if lat and lng:
                cfg["lat"], cfg["lng"] = str(lat), str(lng)
                config.save_config(config.global_config)
            else: return DEFAULT_ON_MINUTES, DEFAULT_OFF_MINUTES
        try:
            lat_f, lng_f = float(lat), float(lng)
            from datetime import date
            N = date.today().timetuple().tm_yday
            B = math.radians((360 / 365) * (N - 81))
            decl = 23.45 * math.sin(B)
            cos_ha = (math.cos(math.radians(90.8333)) - (math.sin(math.radians(lat_f)) * math.sin(math.radians(decl)))) / (math.cos(math.radians(lat_f)) * math.cos(math.radians(decl)))
            if cos_ha > 1 or cos_ha < -1:
                # 极昼/极夜：该纬度当天没有日出或日落
                logger.info("当前纬度 %.2f 今日无日出/日落，使用默认时段", lat_f)
                return DEFAULT_ON_MINUTES, DEFAULT_OFF_MINUTES
            ha = math.degrees(math.acos(cos_ha))
            eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)
            solar_noon_utc = 12 - (lng_f / 15) - (eot / 60)
            is_dst = time.daylight and time.localtime().tm_isdst > 0
            utc_offset = - (time.altzone if is_dst else time.timezone) / 3600
            sr_local = (solar_noon_utc - (ha / 15) + utc_offset) % 24
            ss_local = (solar_noon_utc + (ha / 15) + utc_offset) % 24
            on_time = int(sr_local * 60) + int(cfg.get("sun_on_offset", 0))
            off_time = int(ss_local * 60) + int(cfg.get("sun_off_offset", 0))
            return on_time, off_time
        except (TypeError, ValueError, ZeroDivisionError) as e:
            logger.error("日出日落推算失败 (lat=%r lng=%r)，退回默认时段: %s", lat, lng, e)
            return DEFAULT_ON_MINUTES, DEFAULT_OFF_MINUTES


def set_light(on, retain=False):
    """开灯或关灯。具体下发什么指令由继电器驱动按配置决定。"""
    l_node = config.global_config["auto_light"]["node_id"]
    l_act = config.global_config["auto_light"]["actuator_id"]
    return state.hardware_manager.trigger_actuator(
        l_node, l_act, mqtt_client=state.global_mqtt_client, state=on, retain=retain
    )


def fill_light_for_capture(duration):
    """拍照前的临时补光：点亮补光灯 `duration` 秒，并等它真正亮起来。

    **所有拍摄路径共用这一个入口**：实时预览、高清抓拍、每日照片、手动重拍。
    三处都要判断"灯是否已开、MQTT 是否连着、要不要忽略回报"，各写一份迟早跑偏
    （此前 photo.py 把忽略窗口写死成 7 秒，routers.py 写的是 duration+3，
    同样的 duration=4 却是两个值）。

    由 `camera.fill_light` 控制（默认开），因此是一个全局的拍照设置，
    不隶属于每日照片。关掉它的场景是灯离镜头太近导致过曝、或者灯与相机
    根本不在同一株植物上——那时宁可要一张偏暗的原色照片。

    返回是否真的下发了补光指令。任何失败都只是照片偏暗，不该让拍照本身失败。
    """
    if not config.global_config.get("camera", {}).get("fill_light", True):
        return False
    if state.light_status == "ON" or not state.global_mqtt_client:
        return False

    # 这盏灯几秒后会自己灭，期间 ESP32 回报的 "ON" 不代表用户开了灯，
    # 忽略窗口要盖住整个点亮时长再加一点余量。
    state.ignore_light_feedback_until = time.time() + duration + 3
    l_node = config.global_config["auto_light"]["node_id"]
    l_act = config.global_config["auto_light"]["actuator_id"]
    try:
        state.hardware_manager.trigger_actuator(
            l_node, l_act, mqtt_client=state.global_mqtt_client, duration=duration
        )
        time.sleep(0.6)
        return True
    except Exception as e:
        logger.warning("拍照前临时补光失败: %s", e)
        return False


def apply_light_schedule(now):
    """按当前时刻推进一次灯控状态机。由 background_logger 每轮调用。

    每轮都重发一次 MQTT 指令（而非只在状态变化时发），
    这样 ESP32 掉电重启后能在下一轮自动恢复到正确状态。
    """
    if not config.global_config["auto_light"]["enabled"]:
        return

    on_time, off_time = get_effective_light_times()
    time_val = now.hour * 60 + now.minute
    if on_time < off_time:
        is_light_time = on_time <= time_val < off_time
    else:
        # 跨午夜时段
        is_light_time = time_val >= on_time or time_val < off_time

    if not state.global_mqtt_client:
        return

    if state.manual_override:
        if state.manual_override_until and now >= state.manual_override_until:
            # 覆盖到期，交还给定时控制
            state.manual_override = False
            state.manual_override_until = None
            logger.info("🔄 手动覆盖已到期，恢复定时控制")

            desired = "ON" if is_light_time else "OFF"
            set_light(desired == "ON")
            state.light_status = desired
        else:
            # 覆盖期内：维持用户选定的状态
            set_light(state.light_status == "ON")

    if not state.manual_override:
        desired = "ON" if is_light_time else "OFF"

        if state.light_status != desired:
            logger.info("💡 定时灯控: %s", desired)
            state.light_status = desired

        set_light(desired == "ON")
