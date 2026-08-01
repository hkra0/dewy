import logging
import os
import secrets
import threading

from hardware.manager import HardwareManager
# 路径全部来自 core.paths（由 __file__ 推导），此处转出以保持 state.XXX 的既有用法
from core.paths import (
    DATA_DIR,
    DB_FILE,
    CONFIG_FILE,
    TOKEN_FILE,
    TMP_IMG_PATH,
    TMP_IMG_HQ_PATH,
    PHOTO_DIR,
    THUMB_DIR,
    ensure_dirs,
)

logger = logging.getLogger(__name__)

camera_lock = threading.Lock()
# 可重入：database.get_conn() 会持锁，嵌套调用 DAL 时不至于自锁
db_lock = threading.RLock()

ensure_dirs()


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
    logger.warning(
        "未找到 PI_SECRET_TOKEN，已生成新密钥并写入 %s\n"
        "    %s\n"
        "    请同步到 Cloudflare Worker: wrangler secret put PI_SECRET_TOKEN",
        TOKEN_FILE, token,
    )
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
