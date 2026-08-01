import os
import secrets
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
TOKEN_FILE = f"{DATA_DIR}/secret_token"

camera_lock = threading.Lock()
# 可重入：database.get_conn() 会持锁，嵌套调用 DAL 时不至于自锁
db_lock = threading.RLock()

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)


def _load_secret_token():
    """BFF(Worker) -> Pi 的共享密钥。切勿硬编码进代码库。

    优先级：环境变量 PI_SECRET_TOKEN > {DATA_DIR}/secret_token 文件。
    两者都没有时自动生成一个并落盘（权限 600），同时打印出来，
    需手动同步到 Worker：wrangler secret put PI_SECRET_TOKEN
    """
    env_token = os.environ.get("PI_SECRET_TOKEN")
    if env_token:
        return env_token.strip()

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            token = f.read().strip()
        if token:
            return token

    token = secrets.token_urlsafe(32)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    print("=" * 68)
    print("⚠️  未找到 PI_SECRET_TOKEN，已生成新密钥并写入:")
    print(f"    {TOKEN_FILE}")
    print(f"    {token}")
    print("    请同步到 Cloudflare Worker: wrangler secret put PI_SECRET_TOKEN")
    print("=" * 68)
    return token


PI_SECRET_TOKEN = _load_secret_token()

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
