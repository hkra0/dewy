import copy
import json
import logging
import os

import core.state as state

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "auto_water": {
        "enabled": True, "duration": 0.5, "threshold": 65.0,
        "target_moisture": 85.0, "pulse_interval": 60, "max_pulses": 10,
        "min_interval_hours": 12, "start_hour": 6, "end_hour": 20,
        "node_id": "main", "actuator_id": "pump",
        # 传感器疑似离土联锁：当前值接近空气读数，且相对上一条归档骤降，
        # 才会锁泵。恢复必须先出现明显回升，再连续多轮稳定高于恢复线。
        "sensor_air_threshold": 15.0,
        "sensor_drop_threshold": 40.0,
        "sensor_recovery_threshold": 30.0,
        "sensor_recovery_rise": 15.0,
        "sensor_recovery_samples": 3,
    },
    # 补光灯按节点分段：{node_id: {...LIGHT_DEFAULTS}}。每株植物（每个鱼缸）
    # 的光照时段各不相同，一份全局时段管不了两盏灯。具体分段由 merge_defaults
    # 按"哪些节点挂了灯"补齐，这里只给空表。
    "auto_light": {},
    # 拍照的通用设置。补光放这里而不是 daily_photo 里：实时预览、高清抓拍、
    # 每日照片走的是同一个 fill_light_for_capture()，它对三条路径一起生效，
    # 挂在 daily_photo 下会让人以为只管定时那一张。
    "camera": {"fill_light": True},
    "daily_photo": {"enabled": True, "hour": 12, "disk_limit_free_gb": 20},
    # 土壤湿度 ABC（自动基准校准）的用户可调项，全局生效于所有可校准传感器
    # （见 core/logic/soil_abc.py）——没有多株植物需要各自不同窗口期的真实
    # 场景，一个全局开关比每传感器一份配置更简单。
    "soil_calibration": {"enabled": True, "window_days": 30, "max_drift_ratio": 0.15},
    # 远程 ESP32 节点设置（按 node_id 分组，值由 settings_schema.default 补齐）
    "node_settings": {},
}
# 单个节点的补光灯配置。actuator_id 是该节点上灯的执行器 id。
LIGHT_DEFAULTS = {
    "enabled": True, "mode": "fixed", "on_time": "07:30", "off_time": "21:30",
    "sun_on_offset": 0, "sun_off_offset": 0, "lat": "", "lng": "",
    "actuator_id": "light",
}


def _merge_light_defaults(cfg):
    """把 auto_light 整理成 {node_id: 完整配置}。

    旧版本是单盏灯的扁平结构（{"enabled":…, "node_id": "main", …}），
    读到时原样挪进它的 node_id 名下，用户的时段设置不丢。
    挂了默认 id（"light"）执行器的节点自动获得一份默认配置；
    用别的 id 的节点需要在 config.json 里手写一段并填 actuator_id。
    """
    lights = cfg.get("auto_light")
    if not isinstance(lights, dict):
        lights = {}
    # 只挪非 dict 的键：新版 Pi 配旧版前端（Worker 晚一步部署、浏览器缓存）时，
    # 旧前端会把扁平字段铺在新的节点表上一起提交，整表当旧格式会把各节点
    # 的配置套进 main 名下。
    flat = {k: lights.pop(k) for k in list(lights) if not isinstance(lights[k], dict)}
    if flat:
        lights.setdefault(flat.pop("node_id", "main"), {}).update(flat)

    hm = getattr(state, "hardware_manager", None)
    actuators = getattr(hm, "actuators", None)
    if isinstance(actuators, dict):
        for node_id, acts in actuators.items():
            if LIGHT_DEFAULTS["actuator_id"] in acts:
                lights.setdefault(node_id, {})

    for node_cfg in lights.values():
        if isinstance(node_cfg, dict):
            for k, v in LIGHT_DEFAULTS.items():
                node_cfg.setdefault(k, v)
    cfg["auto_light"] = lights


# deepcopy 而非 copy：浅拷贝下 global_config 的各段就是 DEFAULT_CONFIG
# 里那个 dict，IP 定位回写 lat/lng 会连默认值一起改掉。
global_config = copy.deepcopy(DEFAULT_CONFIG)

def merge_defaults(cfg):
    """把 DEFAULT_CONFIG 里缺失的键补进 cfg（就地修改并返回）。

    读盘与写入都要走一遍：**前端只提交它自己渲染的那几段**，
    没有 UI 的段（以及新版本刚加的字段）不会出现在请求体里。
    不补的话一次保存就能让 global_config 少掉整个 daily_photo 段，
    后台循环下一轮直接 KeyError——而且要重启才能恢复。
    """
    # ---- 自动浇水字段迁移 ----
    if "auto_water" in cfg:
        aw = cfg["auto_water"]
        if "hour" in aw:
            if "start_hour" not in aw:
                aw["start_hour"] = aw["hour"]
            del aw["hour"]

    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(cfg[k], dict):
            for subk, subv in v.items():
                if subk not in cfg[k]: cfg[k][subk] = subv

    _merge_light_defaults(cfg)

    # ---- 远程节点设置默认值填充 ----
    if hasattr(state, "hardware_manager") and getattr(state.hardware_manager, "mqtt_nodes", None):
        ns = cfg.setdefault("node_settings", {})
        for node_id, node_info in state.hardware_manager.mqtt_nodes.items():
            schema = node_info.get("settings_schema", {})
            if not schema:
                continue
            node_cfg = ns.setdefault(node_id, {})
            # Existing nodes stay daily. Only a newly configured node receives its
            # schema's explicit policy; defaults must not silently change a deployment.
            if node_cfg and "feeding_mode" in schema and "feeding_mode" not in node_cfg:
                node_cfg["feeding_mode"] = "daily"
                if "low_alarm_enabled" in schema:
                    node_cfg.setdefault("low_alarm_enabled", True)
                if "feed_max_temp" in schema and "temp_alarm_high" in node_cfg:
                    node_cfg.setdefault("feed_max_temp", node_cfg["temp_alarm_high"])
            if "feed_reset_hour" in node_cfg and "feed_start_hour" not in node_cfg:
                node_cfg["feed_start_hour"] = node_cfg["feed_reset_hour"]
            for key, meta in schema.items():
                if key not in node_cfg and isinstance(meta, dict) and "default" in meta:
                    node_cfg[key] = meta["default"]

    return cfg


def load_config():
    global global_config
    if os.path.exists(state.CONFIG_FILE):
        try:
            with open(state.CONFIG_FILE, "r") as f:
                global_config = merge_defaults(json.load(f))
        except (OSError, ValueError) as e:
            # 配置文件损坏或不可读：保留内存里的默认值继续跑，不要让服务起不来
            logger.error("配置文件 %s 读取失败，沿用默认配置: %s", state.CONFIG_FILE, e)
    else:
        save_config(global_config)

def save_config(cfg):
    global global_config
    global_config = merge_defaults(cfg)
    try:
        with open(state.CONFIG_FILE, "w") as f: json.dump(cfg, f, indent=4)
    except (OSError, TypeError) as e:
        # 落盘失败不影响本次运行（内存里已生效），但重启会丢，必须让用户看见
        logger.error("配置写入 %s 失败，重启后将丢失: %s", state.CONFIG_FILE, e)
