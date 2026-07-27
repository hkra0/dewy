import os
import threading
from hardware.manager import HardwareManager

# ==================== 统一路径与硬件锁配置 ====================
DATA_DIR = "/home/hkra/dewy/data"
TMP_IMG_PATH = f"{DATA_DIR}/live.jpg"
TMP_IMG_HQ_PATH = f"{DATA_DIR}/live_hq.jpg"
DB_FILE = f"{DATA_DIR}/plant_history.db"
CONFIG_FILE = f"{DATA_DIR}/config.json"
PHOTO_DIR = f"{DATA_DIR}/photos"
THUMB_DIR = f"{DATA_DIR}/photos/thumbs"

PI_SECRET_TOKEN = "hKra_Secure_Sensor_2026_Token"

camera_lock = threading.Lock()
db_lock = threading.Lock()

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)

# 初始化硬件抽象层
hardware_manager = HardwareManager(DATA_DIR)

global_mqtt_client = None
light_status = "--"
manual_override = False
manual_override_until = None
camera_in_progress = False
ignore_light_feedback_until = 0
power_save_mode = False

mqtt_topic_to_node = {}
for n_id, info in hardware_manager.mqtt_nodes.items():
    if "topic" in info:
        mqtt_topic_to_node[info["topic"]] = n_id

mqtt_latest_data = {n_id: {"data": {}, "updated": False} for n_id in hardware_manager.mqtt_nodes}
local_latest_data = {n_id: {} for n_id in hardware_manager.local_sensors}
