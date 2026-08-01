"""UPS 供电监测与省电模式切换。

判据：INA219 电流长期为负（放电）且无网络 → 进入省电模式。
恢复需连续 CONFIRM_THRESHOLD 次确认，避免电流抖动导致反复切换。
"""

import logging
import subprocess
import time

import core.state as state
from core.logic.system import is_wifi_connected
from core.paths import POWER_SAVER_SCRIPT

logger = logging.getLogger(__name__)

DISCHARGE_CURRENT_MA = -300     # 低于此值视为放电
RECOVER_CURRENT_MA = -100       # 高于此值视为供电恢复
DISCHARGE_CONFIRM_SEC = 120     # 放电持续多久才进省电
CONFIRM_THRESHOLD = 3           # 退出省电所需的连续确认次数


def local_sensor_updater():
    ups_discharge_start_time = None
    power_save_exit_count = 0

    try:
        subprocess.run([POWER_SAVER_SCRIPT, "disable"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info("🔄 系统启动，初始化电源模式为正常")
    except OSError as e:
        logger.error("初始化省电模式失败（脚本 %s 不可执行？）: %s", POWER_SAVER_SCRIPT, e)

    while True:
        try:
            for node_id in state.hardware_manager.local_sensors:
                data = state.hardware_manager.read_local_node(node_id)
                if data:
                    state.local_latest_data[node_id] = data

            if "main" in state.local_latest_data:
                current = state.local_latest_data["main"].get("current", 0)
                if current is not None:
                    if current < DISCHARGE_CURRENT_MA:
                        if ups_discharge_start_time is None:
                            ups_discharge_start_time = time.time()
                    else:
                        ups_discharge_start_time = None

                    if not state.power_save_mode:
                        if ups_discharge_start_time and (time.time() - ups_discharge_start_time) > DISCHARGE_CONFIRM_SEC:
                            if not is_wifi_connected():
                                logger.warning("⚠️ UPS 长期放电 (电流: %smA) 且无网络，进入省电模式", current)
                                state.power_save_mode = True
                                power_save_exit_count = 0
                                subprocess.run([POWER_SAVER_SCRIPT, "enable"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    elif state.power_save_mode:
                        if current > RECOVER_CURRENT_MA or is_wifi_connected():
                            power_save_exit_count += 1
                            if power_save_exit_count >= CONFIRM_THRESHOLD:
                                logger.info("🔌 电源或网络恢复 (电流: %smA)，连续 %d 次确认，退出省电模式",
                                            current, CONFIRM_THRESHOLD)
                                state.power_save_mode = False
                                power_save_exit_count = 0
                                ups_discharge_start_time = None
                                subprocess.run([POWER_SAVER_SCRIPT, "disable"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        else:
                            power_save_exit_count = 0
        except Exception:
            # 本循环每 2 秒一轮，I2C 偶发失败很常见；
            # 用 debug 避免刷屏，排查时设 DEWY_LOG_LEVEL=DEBUG 即可看到
            logger.debug("传感器轮询异常", exc_info=True)

        if state.power_save_mode:
            time.sleep(60.0)
        else:
            time.sleep(2.0)
