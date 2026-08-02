"""系统与网络状态查询。无副作用，供其它模块与 /api/monitor 使用。"""

import glob
import logging
import os
import socket

logger = logging.getLogger(__name__)

# 网卡名不是到处都叫 wlan0：桌面 Linux 上是 wlp2s0 之类，有线接入则是 eth0。
# 留一个环境变量给能确定的人，其余情况自动挑一张已连接的物理网卡。
NET_INTERFACE = os.environ.get("DEWY_NET_INTERFACE", "").strip()


def _carrier_is_up():
    """本机是否有网卡已连上链路。/sys 不存在（非 Linux）时返回 False。"""
    if NET_INTERFACE:
        candidates = [f"/sys/class/net/{NET_INTERFACE}/carrier"]
    else:
        # lo 没有 carrier 文件，天然被排除；虚接口一般也没有
        candidates = sorted(glob.glob("/sys/class/net/*/carrier"))

    for path in candidates:
        try:
            with open(path, "r") as f:
                if f.read().strip() == "1":
                    return True
        except OSError:
            continue
    return False


def is_wifi_connected():
    """有网可用即为真。链路层查不出结果时退回实际拨测。"""
    if _carrier_is_up():
        return True
    try:
        socket.create_connection(("223.5.5.5", 53), timeout=2)
        return True
    except OSError:
        pass
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False


def _read_cpu_temp():
    """CPU 温度（℃），读不到返回 0.0。

    thermal_zone0 在树莓派上是 CPU，但在别的板子/主机上未必——
    某些平台上 zone0 是电池或无线模块。故遍历所有热区取最高值，
    宁可报一个偏高的机内温度，也好过报一个明显不对的数。
    """
    temps = []
    for path in sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp")):
        try:
            with open(path, "r") as f:
                value = int(f.read().strip()) / 1000.0
        except (OSError, ValueError):
            continue
        # 明显不是摄氏温度的读数（有些热区未启用时报 0 或极大值）直接跳过
        if 0 < value < 150:
            temps.append(value)

    if not temps:
        logger.debug("读取 CPU 温度失败：没有可用的 thermal zone")
        return 0.0
    return max(temps)


def _read_ram_used_pct():
    """内存占用百分比，读不到返回 0.0。

    按字段名解析而非按行号：/proc/meminfo 的字段顺序随内核版本变动过，
    固定下标在别的发行版上会读到完全不相干的值。
    """
    try:
        fields = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                name, _, rest = line.partition(":")
                if name in ("MemTotal", "MemAvailable"):
                    fields[name] = int(rest.split()[0])
        total, available = fields["MemTotal"], fields["MemAvailable"]
        return round(((total - available) / total) * 100, 1)
    except (OSError, ValueError, KeyError, IndexError, ZeroDivisionError) as e:
        logger.debug("读取内存占用失败: %s", e)
        return 0.0


def get_system_stats():
    """读不到的项返回 0.0——前端显示 0 即代表该项不可用。

    每 5 秒被 /api/monitor 调用一次，故失败只记 debug，避免刷屏。
    """
    cpu_temp = _read_cpu_temp()
    ram_used_pct = _read_ram_used_pct()
    try:
        stat = os.statvfs('/')
        disk_used_pct = round((((stat.f_blocks - stat.f_bavail) * stat.f_frsize) / (stat.f_blocks * stat.f_frsize)) * 100, 1)
    except (OSError, ZeroDivisionError) as e:
        logger.debug("读取磁盘占用失败: %s", e)
        disk_used_pct = 0.0
    return {"cpu_temperature": round(cpu_temp, 1), "ram_usage_percent": ram_used_pct, "disk_usage_percent": disk_used_pct}


def get_free_disk_gb():
    """返回根分区剩余可用空间（GB）。"""
    try:
        stat = os.statvfs('/')
        return (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
    except OSError as e:
        # 返回极大值，宁可不清理也不要误删照片
        logger.warning("读取磁盘剩余空间失败，本次跳过照片清理: %s", e)
        return 999.0
