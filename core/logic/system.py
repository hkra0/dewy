"""系统与网络状态查询。无副作用，供其它模块与 /api/monitor 使用。"""

import os
import socket


def is_wifi_connected():
    try:
        with open("/sys/class/net/wlan0/carrier", "r") as f:
            if f.read().strip() == "1":
                return True
    except Exception:
        pass
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


def get_system_stats():
    try: cpu_temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000.0
    except: cpu_temp = 0.0
    try:
        mem = open("/proc/meminfo").read().split()
        ram_used_pct = round(((int(mem[1]) - int(mem[7])) / int(mem[1])) * 100, 1)
    except: ram_used_pct = 0.0
    try:
        stat = os.statvfs('/')
        disk_used_pct = round((((stat.f_blocks - stat.f_bavail) * stat.f_frsize) / (stat.f_blocks * stat.f_frsize)) * 100, 1)
    except: disk_used_pct = 0.0
    return {"cpu_temperature": round(cpu_temp, 1), "ram_usage_percent": ram_used_pct, "disk_usage_percent": disk_used_pct}


def get_free_disk_gb():
    """返回根分区剩余可用空间（GB）。"""
    try:
        stat = os.statvfs('/')
        return (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
    except Exception:
        return 999.0  # 读取失败时不触发清理
