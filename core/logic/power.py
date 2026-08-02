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
import os
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

UPS_NODE_ID = "main"            # UPS 电流所在的节点
UPS_FIELD = "current"           # 省电判据依赖的字段

# 采样分两档：省电判据只依赖电流，其余传感器不必跟着高频读。
# 归档是 10 分钟一轮、前端轮询 30 秒，温湿度按秒级读属于几百倍过采样——
# 白白占用 CPU 与 I2C 总线，且 SHT30 高频读取会自热、把温度读数抬高。
#
# 快档取 10 秒而不是更密：判据是"连续放电超过 DISCHARGE_CONFIRM_SEC(120) 秒"，
# 10 秒一次在这个窗口里已有 12 个样本，分辨率绰绰有余。而且下面的判定里
# **任何一个高于阈值的样本都会把计时器清零**，所以采样越快越难进省电模式——
# 放慢不会让进入判断变得草率，只会让它更稳，同时把 I2C 事务量降到 1/5
# （每天 43,200 次 → 8,640 次），这对一台正在省电的 Pi Zero 2 W 是实打实的。
# 退出路径不受影响：省电模式下本就是 POWER_SAVE_INTERVAL_SEC 一轮。
_FAST_INTERVAL_DEFAULT = 10.0
try:
    FAST_INTERVAL_SEC = float(os.environ.get("DEWY_UPS_SAMPLE_SEC", _FAST_INTERVAL_DEFAULT))
    if FAST_INTERVAL_SEC <= 0:
        raise ValueError("必须为正数")
except ValueError as e:
    logger.error("DEWY_UPS_SAMPLE_SEC=%r 非法（%s），退回默认 %.1f 秒",
                 os.environ.get("DEWY_UPS_SAMPLE_SEC"), e, _FAST_INTERVAL_DEFAULT)
    FAST_INTERVAL_SEC = _FAST_INTERVAL_DEFAULT

FULL_INTERVAL_SEC = 30.0
POWER_SAVE_INTERVAL_SEC = 60.0  # 省电模式下不再分档，整体降频


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


def _read_all_nodes():
    """全量读取所有本地节点。整轮读不到任何值时保留上一次的读数。"""
    for node_id in state.hardware_manager.local_sensors:
        data = state.hardware_manager.read_local_node(node_id)
        if data:
            state.local_latest_data[node_id] = data


def _read_ups_only(sensor_ids):
    """只读提供电流的那些传感器，结果合并进已有读数。

    合并前先摘掉这些传感器已知会提供的字段：这样读失败时对应字段消失，
    与全量读取的语义一致，界面上不会留下一个看着正常的过期电流值。
    """
    hm = state.hardware_manager
    data = hm.read_local_node(UPS_NODE_ID, sensor_ids=sensor_ids)

    entry = dict(state.local_latest_data.get(UPS_NODE_ID) or {})
    for field in hm.fields_of(UPS_NODE_ID, sensor_ids):
        entry.pop(field, None)
    entry.update(data)
    state.local_latest_data[UPS_NODE_ID] = entry


def local_sensor_updater():
    ups_discharge_start_time = None
    power_save_exit_count = 0
    last_pet_time = 0.0
    last_full_read = 0.0
    ups_sensor_ids = None   # None 表示尚未探测；[] 表示该节点没有电流传感器

    if _run_power_saver("disable"):
        logger.info("🔄 系统启动，初始化电源模式为正常")

    while True:
        try:
            # 省电模式下本就 60 秒一轮，没必要再分档
            need_full = (ups_sensor_ids is None
                         or state.power_save_mode
                         or time.time() - last_full_read >= FULL_INTERVAL_SEC)

            if need_full:
                _read_all_nodes()
                last_full_read = time.time()
                # 每次全量读取后重新探测：坏掉又恢复的传感器能自动归队
                ups_sensor_ids = state.hardware_manager.sensors_for_field(UPS_NODE_ID, UPS_FIELD)
            elif ups_sensor_ids:
                _read_ups_only(ups_sensor_ids)

            if UPS_NODE_ID in state.local_latest_data:
                current = state.local_latest_data[UPS_NODE_ID].get(UPS_FIELD, 0)
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
            # I2C 偶发失败很常见；用 debug 避免刷屏，
            # 排查时设 DEWY_LOG_LEVEL=DEBUG 即可看到
            logger.debug("传感器轮询异常", exc_info=True)

        if state.power_save_mode:
            time.sleep(POWER_SAVE_INTERVAL_SEC)
        elif ups_sensor_ids:
            time.sleep(FAST_INTERVAL_SEC)
        else:
            # 没有电流传感器就没有省电判据，快循环纯属空转
            time.sleep(FULL_INTERVAL_SEC)
