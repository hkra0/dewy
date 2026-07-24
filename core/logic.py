import os
import time
import subprocess
import sqlite3
import json
import urllib.request
import math
from datetime import datetime, timedelta

import core.state as state
import core.config as config
from core.database import init_db

def is_wifi_connected():
    import socket
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

def local_sensor_updater():
    ups_discharge_start_time = None
    CONFIRM_THRESHOLD = 3
    power_save_exit_count = 0

    try:
        subprocess.run(["/home/hkra/dewy/power_saver.sh", "disable"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
                    if current < -300:
                        if ups_discharge_start_time is None:
                            ups_discharge_start_time = time.time()
                    else:
                        ups_discharge_start_time = None

                    if not state.power_save_mode:
                        if ups_discharge_start_time and (time.time() - ups_discharge_start_time) > 120:
                            if not is_wifi_connected():
                                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ UPS 长期放电 (电流: {current}mA) 且无网络，即将进入省电模式...")
                                state.power_save_mode = True
                                power_save_exit_count = 0
                                subprocess.run(["/home/hkra/dewy/power_saver.sh", "enable"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    elif state.power_save_mode:
                        if current > -100 or is_wifi_connected():
                            power_save_exit_count += 1
                            if power_save_exit_count >= CONFIRM_THRESHOLD:
                                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔌 电源或网络恢复 (电流: {current}mA)，连续 {CONFIRM_THRESHOLD} 次确认，退出省电模式...")
                                state.power_save_mode = False
                                power_save_exit_count = 0
                                ups_discharge_start_time = None
                                subprocess.run(["/home/hkra/dewy/power_saver.sh", "disable"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        else:
                            power_save_exit_count = 0
        except Exception as e:
            pass
        
        if state.power_save_mode:
            time.sleep(60.0)
        else:
            time.sleep(2.0)

def compute_next_boundary(now, on_minutes, off_minutes):
    current_minutes = now.hour * 60 + now.minute
    boundaries = [on_minutes, off_minutes]
    
    next_boundary = None
    for b in sorted(boundaries):
        if b > current_minutes:
            next_boundary = b
            break
    
    if next_boundary is None:
        next_boundary = min(boundaries)
        target = now.replace(hour=next_boundary // 60, minute=next_boundary % 60, second=0, microsecond=0)
        target += timedelta(days=1)
    else:
        target = now.replace(hour=next_boundary // 60, minute=next_boundary % 60, second=0, microsecond=0)
    
    return target

def fetch_ip_location():
    try:
        req = urllib.request.urlopen("http://ip-api.com/json", timeout=3)
        data = json.loads(req.read())
        return data.get("lat"), data.get("lon")
    except: return None, None

def get_effective_light_times():
    cfg = config.global_config["auto_light"]
    if cfg["mode"] == "fixed":
        try:
            on_h, on_m = map(int, cfg["on_time"].split(":"))
            off_h, off_m = map(int, cfg["off_time"].split(":"))
            return on_h * 60 + on_m, off_h * 60 + off_m
        except: return 7 * 60 + 30, 21 * 60 + 30
    else:
        lat, lng = cfg.get("lat"), cfg.get("lng")
        if not lat or not lng:
            lat, lng = fetch_ip_location()
            if lat and lng:
                cfg["lat"], cfg["lng"] = str(lat), str(lng)
                config.save_config(config.global_config)
            else: return 7 * 60 + 30, 21 * 60 + 30
        try:
            lat_f, lng_f = float(lat), float(lng)
            from datetime import date
            import time
            N = date.today().timetuple().tm_yday
            B = math.radians((360 / 365) * (N - 81))
            decl = 23.45 * math.sin(B)
            cos_ha = (math.cos(math.radians(90.8333)) - (math.sin(math.radians(lat_f)) * math.sin(math.radians(decl)))) / (math.cos(math.radians(lat_f)) * math.cos(math.radians(decl)))
            if cos_ha > 1 or cos_ha < -1: return 7 * 60 + 30, 21 * 60 + 30
            ha = math.degrees(math.acos(cos_ha))
            eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)
            solar_noon_utc = 12 - (lng_f / 15) - (eot / 60)
            is_dst = time.daylight and time.localtime().tm_isdst > 0
            utc_offset = - (time.altzone if is_dst else time.timezone) / 3600
            sr_local = (solar_noon_utc - (ha / 15) + utc_offset) % 24
            ss_local = (solar_noon_utc + (ha / 15) + utc_offset) % 24
            on_time = int(sr_local * 60) + int(cfg.get("sun_on_offset", 0))
            off_time = int(ss_local * 60) + int(cfg.get("sun_off_offset", 0))
            return on_time, off_time
        except: return 7 * 60 + 30, 21 * 60 + 30

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

def clean_soil_anomalies(node_id):
    with state.db_lock:
        conn = sqlite3.connect(state.DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, soil_moisture FROM node_data WHERE node_id=? ORDER BY id DESC LIMIT 5", (node_id,))
        rows = cursor.fetchall()
        
        if len(rows) < 3: return
        current_soil = rows[0][1]
        last_soil = rows[1][1]
        
        if current_soil is not None and last_soil is not None and current_soil - last_soil > 10:
            anomaly_ids = []
            if last_soil < 10 and len(rows) >= 3 and rows[2][1] is not None and (rows[2][1] - last_soil > 5): anomaly_ids = [rows[1][0]]
            elif last_soil < 10 and len(rows) >= 4 and rows[2][1] is not None and rows[2][1] < 10 and rows[3][1] is not None and (rows[3][1] - rows[2][1] > 5): anomaly_ids = [rows[1][0], rows[2][0]]
            elif last_soil < 10 and len(rows) >= 5 and rows[2][1] is not None and rows[2][1] < 10 and rows[3][1] is not None and rows[3][1] < 10 and rows[4][1] is not None and (rows[4][1] - rows[3][1] > 5): anomaly_ids = [rows[1][0], rows[2][0], rows[3][0]]
            
            if anomaly_ids:
                placeholders = ','.join('?' * len(anomaly_ids))
                cursor.execute(f"UPDATE node_data SET is_anomaly = 1 WHERE id IN ({placeholders})", anomaly_ids)
        conn.commit()
        conn.close()

def can_water_now(node_id):
    try:
        with state.db_lock:
            conn = sqlite3.connect(state.DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT timestamp FROM watering_log WHERE node_id=? ORDER BY id DESC LIMIT 1", (node_id,))
            row = cursor.fetchone()
            conn.close()
            if not row: return True
            last_utc = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            diff_hours = (datetime.utcnow() - last_utc).total_seconds() / 3600
            return diff_hours > 12
    except Exception:
        return False

def trigger_watering(node_id, soil_before, duration=None):
    if duration is None: duration = config.global_config["auto_water"]["duration"]
    
    actuator_id = "pump"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 💦 开启水泵 (Node: {node_id}), 时长: {duration}s")
    success = state.hardware_manager.trigger_actuator(node_id, actuator_id, duration=duration)
    
    if success:
        with state.db_lock:
            conn = sqlite3.connect(state.DB_FILE)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO watering_log (node_id, duration, soil_before) VALUES (?, ?, ?)", (node_id, duration, soil_before))
            conn.commit()
            conn.close()
        return True
    else:
        print(f"❌ 浇水异常或未配置对应继电器")
        return False

def background_logger():
    init_db()
    while True:
        try:
            now = datetime.now()
            
            if config.global_config["auto_light"]["enabled"]:
                on_time, off_time = get_effective_light_times()
                time_val = now.hour * 60 + now.minute
                if on_time < off_time:
                    is_light_time = on_time <= time_val < off_time
                else:
                    is_light_time = time_val >= on_time or time_val < off_time
                    
                if state.global_mqtt_client:
                    if state.manual_override:
                        if state.manual_override_until and now >= state.manual_override_until:
                            state.manual_override = False
                            state.manual_override_until = None
                            print(f"[{now.strftime('%H:%M:%S')}] 🔄 手动覆盖已到期，恢复定时控制")
                            
                            desired = "ON" if is_light_time else "OFF"
                            cmd = "a1" if desired == "ON" else "b1"
                            l_node = config.global_config["auto_light"]["node_id"]
                            l_act = config.global_config["auto_light"]["actuator_id"]
                            state.hardware_manager.trigger_actuator(l_node, l_act, mqtt_client=state.global_mqtt_client, command=cmd)
                            state.light_status = desired
                        else:
                            cmd = "a1" if state.light_status == "ON" else "b1"
                            l_node = config.global_config["auto_light"]["node_id"]
                            l_act = config.global_config["auto_light"]["actuator_id"]
                            state.hardware_manager.trigger_actuator(l_node, l_act, mqtt_client=state.global_mqtt_client, command=cmd)
                    
                    if not state.manual_override:
                        desired = "ON" if is_light_time else "OFF"
                        
                        if state.light_status != desired:
                            print(f"[{now.strftime('%H:%M:%S')}] 💡 定时灯控: {desired}")
                            state.light_status = desired
                            
                        cmd = "a1" if desired == "ON" else "b1"
                        l_node = config.global_config["auto_light"]["node_id"]
                        l_act = config.global_config["auto_light"]["actuator_id"]
                        state.hardware_manager.trigger_actuator(l_node, l_act, mqtt_client=state.global_mqtt_client, command=cmd)
            
            node_data_to_save = []
            
            for node_id in state.hardware_manager.local_sensors:
                data = state.local_latest_data.get(node_id, {})
                if data:
                    data = data.copy()
                    data["node_id"] = node_id
                    node_data_to_save.append(data)
                
                if not state.power_save_mode and config.global_config["auto_water"]["enabled"] and config.global_config["auto_water"]["node_id"] == node_id:
                    if now.hour == 6 and can_water_now(node_id):
                        soil_pct = data.get("soil_moisture")
                        if soil_pct is not None and soil_pct < config.global_config["auto_water"]["threshold"]:
                            trigger_watering(node_id, soil_pct, config.global_config["auto_water"]["duration"])
            
            for node_id, info in state.mqtt_latest_data.items():
                if info["updated"]:
                    data = info["data"].copy()
                    data["node_id"] = node_id
                    node_data_to_save.append(data)
                    info["updated"] = False
                    
            with state.db_lock:
                conn = sqlite3.connect(state.DB_FILE)
                cursor = conn.cursor()
                for d in node_data_to_save:
                    cursor.execute('''
                        INSERT INTO node_data (node_id, temperature, humidity, soil_moisture, pressure, voltage, current)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        d.get("node_id"), 
                        d.get("temperature"), d.get("humidity"), d.get("soil_moisture"),
                        d.get("pressure"), d.get("voltage"), d.get("current")
                    ))
                conn.commit()
                conn.close()
                
            for d in node_data_to_save:
                clean_soil_anomalies(d.get("node_id"))
                
            print(f"[{now.strftime('%H:%M:%S')}] 💾 数据归档")
        except Exception as e:
            print(f"后台记录失败: {e}")
        
        now = datetime.now()
        seconds_passed = now.minute * 60 + now.second + now.microsecond / 1_000_000
        
        align_interval = 3600 if state.power_save_mode else 600
        sleep_sec = align_interval - (seconds_passed % align_interval)
        time.sleep(max(0.1, sleep_sec))
