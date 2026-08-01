import json
import logging
import os

import core.state as state

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "auto_water": {"enabled": True, "duration": 0.5, "threshold": 50.0, "node_id": "main"},
    "auto_light": {"enabled": True, "mode": "fixed", "on_time": "07:30", "off_time": "21:30", "sun_on_offset": 0, "sun_off_offset": 0, "lat": "", "lng": "", "node_id": "main", "actuator_id": "light"},
    "daily_photo": {"enabled": True, "hour": 12, "disk_limit_free_gb": 20}
}
global_config = DEFAULT_CONFIG.copy()

def load_config():
    global global_config
    if os.path.exists(state.CONFIG_FILE):
        try:
            with open(state.CONFIG_FILE, "r") as f:
                loaded = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    if k not in loaded: loaded[k] = v
                    elif isinstance(v, dict):
                        for subk, subv in v.items():
                            if subk not in loaded[k]: loaded[k][subk] = subv
                global_config = loaded
        except (OSError, ValueError) as e:
            # 配置文件损坏或不可读：保留内存里的默认值继续跑，不要让服务起不来
            logger.error("配置文件 %s 读取失败，沿用默认配置: %s", state.CONFIG_FILE, e)
    else:
        save_config(global_config)

def save_config(cfg):
    global global_config
    global_config = cfg
    try:
        with open(state.CONFIG_FILE, "w") as f: json.dump(cfg, f, indent=4)
    except (OSError, TypeError) as e:
        # 落盘失败不影响本次运行（内存里已生效），但重启会丢，必须让用户看见
        logger.error("配置写入 %s 失败，重启后将丢失: %s", state.CONFIG_FILE, e)
