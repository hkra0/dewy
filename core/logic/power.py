"""UPS 供电监测与省电模式切换。

判据：INA219 电流长期为负（放电）且无网络 → 进入省电模式。
恢复需连续 CONFIRM_THRESHOLD 次确认，避免电流抖动导致反复切换。
"""

import subprocess
import time
from datetime import datetime

import core.state as state
from core.logic.system import is_wifi_connected

POWER_SAVER_SCRIPT = "/home/hkra/dewy/power_saver.sh"

DISCHARGE_CURRENT_MA = -300     # 低于此值视为放电
RECOVER_CURRENT_MA = -100       # 高于此值视为供电恢复
DISCHARGE_CONFIRM_SEC = 120     # 放电持续多久才进省电
CONFIRM_THRESHOLD = 3           # 退出省电所需的连续确认次数


def local_sensor_updater():
    ups_discharge_start_time = None
    power_save_exit_count = 0

    try:
        subprocess.run([POWER_SAVER_SCRIPT, "disable"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 系统启动，初始化电源模式为正常...")
    except Exception as e:
        print(f"初始化省电模式状态失败: {e}")

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
                                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ UPS 长期放电 (电流: {current}mA) 且无网络，即将进入省电模式...")
                                state.power_save_mode = True
                                power_save_exit_count = 0
                                subprocess.run([POWER_SAVER_SCRIPT, "enable"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    elif state.power_save_mode:
                        if current > RECOVER_CURRENT_MA or is_wifi_connected():
                            power_save_exit_count += 1
                            if power_save_exit_count >= CONFIRM_THRESHOLD:
                                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔌 电源或网络恢复 (电流: {current}mA)，连续 {CONFIRM_THRESHOLD} 次确认，退出省电模式...")
                                state.power_save_mode = False
                                power_save_exit_count = 0
                                ups_discharge_start_time = None
                                subprocess.run([POWER_SAVER_SCRIPT, "disable"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        else:
                            power_save_exit_count = 0
        except Exception:
            pass

        if state.power_save_mode:
            time.sleep(60.0)
        else:
            time.sleep(2.0)
