"""统一路径解析。所有路径由本文件位置推导，不写死用户名或部署目录。

PROJECT_ROOT 取自 __file__（core/paths.py 的上一级），因此无论从哪个
工作目录启动、以哪个用户运行，都指向真实的仓库根目录。

环境变量（用于把数据放到仓库之外，例如挂载的 U 盘）：
    DEWY_DATA_DIR      覆盖数据目录，默认 <PROJECT_ROOT>/data
    DEWY_POWER_SAVER   覆盖省电脚本路径，默认 <PROJECT_ROOT>/power_saver.sh
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.abspath(os.environ.get("DEWY_DATA_DIR") or os.path.join(PROJECT_ROOT, "data"))

DB_FILE = os.path.join(DATA_DIR, "plant_history.db")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
TOKEN_FILE = os.path.join(DATA_DIR, "secret_token")
TMP_IMG_PATH = os.path.join(DATA_DIR, "live.jpg")
TMP_IMG_HQ_PATH = os.path.join(DATA_DIR, "live_hq.jpg")
PHOTO_DIR = os.path.join(DATA_DIR, "photos")
THUMB_DIR = os.path.join(PHOTO_DIR, "thumbs")

POWER_SAVER_SCRIPT = os.environ.get("DEWY_POWER_SAVER") or os.path.join(PROJECT_ROOT, "power_saver.sh")


def ensure_dirs():
    """创建运行期需要的目录。幂等。"""
    for d in (DATA_DIR, PHOTO_DIR, THUMB_DIR):
        os.makedirs(d, exist_ok=True)
