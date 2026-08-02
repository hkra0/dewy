"""每日照片拍摄与磁盘不足时的对数稀疏化清理。"""

import logging
import math
import os
import time
from datetime import datetime

import core.state as state
import core.config as config
import core.database as db
from core.logic.system import get_free_disk_gb

logger = logging.getLogger(__name__)

RECENT_KEEP_DAYS = 7        # 保护区：这段时间内的照片永不删除
MIN_PHOTOS_TO_CLEAN = 30    # 总数不超过此值时不做任何清理
DELETE_BATCH_SIZE = 5       # 每删这么多张检查一次磁盘


def daily_photo_capture():
    """每日定时拍摄一张 HQ 植物照片并生成缩略图。"""
    now = datetime.now()
    photo_cfg = config.global_config["daily_photo"]

    if now.hour < photo_cfg["hour"]:
        return

    today_str = now.strftime("%Y-%m-%d")
    filename = f"{today_str}.jpg"

    # 检查今天是否已拍
    if db.photo_exists(today_str):
        return

    photo_path = os.path.join(state.PHOTO_DIR, filename)
    thumb_path = os.path.join(state.THUMB_DIR, filename)

    logger.info("📷 每日照片拍摄中...")

    try:
        # 临时开灯（如果灯未开且 MQTT 可用）
        needs_temp_light = (state.light_status != "ON") and state.global_mqtt_client
        l_node = config.global_config["auto_light"]["node_id"]
        l_act = config.global_config["auto_light"]["actuator_id"]

        if needs_temp_light:
            state.ignore_light_feedback_until = time.time() + 7
            try:
                state.hardware_manager.trigger_actuator(l_node, l_act, mqtt_client=state.global_mqtt_client, duration=4)
                time.sleep(0.6)
            except Exception as e:
                # 补光失败不影响拍照，只是照片会偏暗
                logger.warning("拍照前临时补光失败: %s", e)

        camera = state.hardware_manager.get_camera()
        if camera is None:
            logger.error("❌ 每日照片拍摄失败：未配置任何相机")
            return

        with state.camera_lock:
            camera.capture(photo_path, hq=True)

        if not os.path.exists(photo_path):
            logger.error("❌ 每日照片拍摄失败：相机未生成 %s", photo_path)
            return

        file_size = os.path.getsize(photo_path)

        # 生成缩略图
        thumb_size = 0
        try:
            from PIL import Image
            with Image.open(photo_path) as img:
                img.thumbnail((320, 240))
                img.save(thumb_path, "JPEG", quality=70)
            thumb_size = os.path.getsize(thumb_path)
        except ImportError:
            logger.warning("⚠️ Pillow 未安装，跳过缩略图生成")
        except Exception as e:
            logger.warning("⚠️ 缩略图生成失败: %s", e)

        # 写入数据库（并发重复插入由 DAL 静默忽略）
        db.insert_photo(today_str, filename, file_size, thumb_size)

        logger.info("✅ 每日照片已保存: %s (%dKB, 缩略图 %dKB)", filename, file_size // 1024, thumb_size // 1024)

        # 拍照完成后检查是否需要清理
        cleanup_old_photos()

    except Exception:
        logger.exception("❌ 每日照片拍摄异常")


def _select_photos_to_delete(rows, today):
    """按对数曲线挑出可删除的照片：越久远，允许的间隔越大。

    min_gap(d) = max(1, floor(3 * ln(d + 1)))
    """
    to_delete = []
    last_kept_date = None

    for date_str, filename in rows:
        try:
            photo_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        age = (today - photo_date).days

        # 保护区：最近若干天永不删除
        if age <= RECENT_KEEP_DAYS:
            last_kept_date = photo_date
            continue

        # 最旧照片：始终保留作为起点
        if last_kept_date is None:
            last_kept_date = photo_date
            continue

        min_gap = max(1, int(3 * math.log(age + 1)))
        actual_gap = (photo_date - last_kept_date).days

        if actual_gap < min_gap:
            to_delete.append((date_str, filename))
        else:
            last_kept_date = photo_date

    return to_delete


def cleanup_old_photos():
    """磁盘不足时按对数曲线稀疏化历史照片：近期密集保留，远期逐渐稀疏。

    触发条件：剩余磁盘空间 <= disk_limit_free_gb（默认 20GB）。
    注意：MIN_PHOTOS_TO_CLEAN 只在入口判断一次，不是删除下限——
    一旦触发，会沿曲线一直删到磁盘够用为止。
    """
    limit_gb = config.global_config["daily_photo"].get("disk_limit_free_gb", 20)
    free_gb = get_free_disk_gb()

    if free_gb > limit_gb:
        return

    logger.warning("⚠️ 剩余磁盘空间 %.1fGB <= %sGB，启动对数稀疏化清理", free_gb, limit_gb)

    rows = db.query_photos_asc()
    if len(rows) <= MIN_PHOTOS_TO_CLEAN:
        return

    to_delete = _select_photos_to_delete(rows, datetime.now().date())

    # 分批处理：先删文件，再删记录，然后检查磁盘是否已够用。
    # 分批而非全程持锁，避免清理期间长时间阻塞 API 的数据库读取。
    deleted_count = 0
    for i in range(0, len(to_delete), DELETE_BATCH_SIZE):
        batch = to_delete[i:i + DELETE_BATCH_SIZE]
        for date_str, filename in batch:
            photo_path = os.path.join(state.PHOTO_DIR, filename)
            if os.path.exists(photo_path):
                os.remove(photo_path)
            thumb_path = os.path.join(state.THUMB_DIR, filename)
            if os.path.exists(thumb_path):
                os.remove(thumb_path)

        db.delete_photos([d for d, _ in batch])
        deleted_count += len(batch)

        if get_free_disk_gb() > limit_gb:
            break

    logger.info("✅ 清理完成，删除 %d 张照片，剩余空间 %.1fGB", deleted_count, get_free_disk_gb())
