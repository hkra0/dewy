"""UPS 供电监测与省电模式切换。

判据：INA219 电流长期为负（放电）且无网络 → 进入省电模式。
恢复需连续 CONFIRM_THRESHOLD 次确认，避免电流抖动导致反复切换。

省电模式会 rfkill 掉 wifi/蓝牙，这台设备没有网口，一旦逻辑卡死就会永久失联。
因此 power_saver.sh 内置了看门狗：enable 时挂一个定时器，到点自动恢复网络。
本模块必须周期性调用 `pet` 续期才能长期停留在省电模式——**续期只发生在
"确认仍需省电"的分支里**，所以传感器读不到值、异常抛出、线程卡死等任何情况
都会导致无人续期，看门狗到点触发，网络自行恢复。
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
WATCHDOG_PET_INTERVAL_SEC = 300 # 看门狗续期间隔，须显著小于脚本里的超时（默认 30 分钟）


def _run_power_saver(action, timeout=30):
    """执行 power_saver.sh，返回是否成功。

    失败必须被看见：enable 在无法挂载看门狗时会主动拒绝并返回非零，
    此时绝不能把 power_save_mode 置为 True，否则状态与实际不符。
    """
    try:
        res = subprocess.run(
            [POWER_SAVER_SCRIPT, action],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.error("执行 %s %s 失败: %s", POWER_SAVER_SCRIPT, action, e)
        return False

    if res.returncode != 0:
        logger.error("%s %s 退出码 %d: %s", POWER_SAVER_SCRIPT, action,
                     res.returncode, res.stderr.decode(errors="replace").strip())
        return False
    return True


def local_sensor_updater():
    ups_discharge_start_time = None
    power_save_exit_count = 0
    last_pet_time = 0.0

    if _run_power_saver("disable"):
        logger.info("🔄 系统启动，初始化电源模式为正常")

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
                                if _run_power_saver("enable"):
                                    state.power_save_mode = True
                                    power_save_exit_count = 0
                                    last_pet_time = time.time()
                                else:
                                    # 脚本拒绝（多半是看门狗挂不上）——保持正常模式，
                                    # 重置计时器以免每轮重试刷屏
                                    logger.error("省电模式启用失败，维持正常模式运行")
                                    ups_discharge_start_time = None
                    elif state.power_save_mode:
                        if current > RECOVER_CURRENT_MA or is_wifi_connected():
                            power_save_exit_count += 1
                            if power_save_exit_count >= CONFIRM_THRESHOLD:
                                logger.info("🔌 电源或网络恢复 (电流: %smA)，连续 %d 次确认，退出省电模式",
                                            current, CONFIRM_THRESHOLD)
                                if _run_power_saver("disable"):
                                    state.power_save_mode = False
                                    power_save_exit_count = 0
                                    ups_discharge_start_time = None
                                # disable 失败则保持 power_save_mode=True，下一轮继续重试；
                                # 即使一直失败，看门狗也会兜底恢复网络
                        else:
                            power_save_exit_count = 0
                            # 确认仍需停留在省电模式 —— 唯一给看门狗续期的地方
                            if time.time() - last_pet_time >= WATCHDOG_PET_INTERVAL_SEC:
                                if _run_power_saver("pet"):
                                    last_pet_time = time.time()
        except Exception:
            # 本循环每 2 秒一轮，I2C 偶发失败很常见；
            # 用 debug 避免刷屏，排查时设 DEWY_LOG_LEVEL=DEBUG 即可看到
            logger.debug("传感器轮询异常", exc_info=True)

        if state.power_save_mode:
            time.sleep(60.0)
        else:
            time.sleep(2.0)
