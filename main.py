import os
import time
import subprocess
import threading
import sqlite3
import json
import urllib.request
import math
from datetime import datetime

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn
import paho.mqtt.client as mqtt

from hardware.manager import HardwareManager

app = FastAPI(title="Robin Plant Monitor BFF")

class WaterRequest(BaseModel):
    duration: float = 0.5
    node_id: str = "main"

# ==================== 统一路径与硬件锁配置 ====================
DATA_DIR = "/home/hkra/dewy/data"
TMP_IMG_PATH = f"{DATA_DIR}/live.jpg"
TMP_IMG_HQ_PATH = f"{DATA_DIR}/live_hq.jpg"
DB_FILE = f"{DATA_DIR}/plant_history.db"
CONFIG_FILE = f"{DATA_DIR}/config.json"

PI_SECRET_TOKEN = "hKra_Secure_Sensor_2026_Token"

camera_lock = threading.Lock()
db_lock = threading.Lock()

os.makedirs(DATA_DIR, exist_ok=True)

# 初始化硬件抽象层
hardware_manager = HardwareManager(DATA_DIR)

global_mqtt_client = None
light_status = "--"
camera_light_active = False

mqtt_topic_to_node = {}
for n_id, info in hardware_manager.mqtt_nodes.items():
    if "topic" in info:
        mqtt_topic_to_node[info["topic"]] = n_id

mqtt_latest_data = {n_id: {"data": {}, "updated": False} for n_id in hardware_manager.mqtt_nodes}
local_latest_data = {n_id: {} for n_id in hardware_manager.local_sensors}

def local_sensor_updater():
    while True:
        try:
            for node_id in hardware_manager.local_sensors:
                data = hardware_manager.read_local_node(node_id)
                if data:
                    local_latest_data[node_id] = data
        except Exception as e:
            pass
        time.sleep(2.0)
# ==================== 软件配置管理 ====================
DEFAULT_CONFIG = {
    "auto_water": {"enabled": True, "duration": 0.5, "threshold": 50.0, "node_id": "main"},
    "auto_light": {"enabled": True, "mode": "fixed", "on_time": "07:30", "off_time": "21:30", "sun_on_offset": 0, "sun_off_offset": 0, "lat": "", "lng": "", "node_id": "main", "actuator_id": "light"}
}
global_config = DEFAULT_CONFIG.copy()

def load_config():
    global global_config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                loaded = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    if k not in loaded: loaded[k] = v
                    elif isinstance(v, dict):
                        for subk, subv in v.items():
                            if subk not in loaded[k]: loaded[k][subk] = subv
                global_config = loaded
        except Exception:
            pass
    else:
        save_config(global_config)

def save_config(cfg):
    global global_config
    global_config = cfg
    try:
        with open(CONFIG_FILE, "w") as f: json.dump(cfg, f, indent=4)
    except: pass

def fetch_ip_location():
    try:
        req = urllib.request.urlopen("http://ip-api.com/json", timeout=3)
        data = json.loads(req.read())
        return data.get("lat"), data.get("lon")
    except: return None, None

def get_effective_light_times():
    cfg = global_config["auto_light"]
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
                save_config(global_config)
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

# ==================== 数据库与逻辑 ====================
def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS node_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                node_id TEXT NOT NULL,
                temperature REAL,
                humidity REAL,
                soil_moisture REAL,
                pressure REAL,
                voltage REAL,
                current REAL,
                is_anomaly INTEGER DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS watering_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                node_id TEXT DEFAULT 'main',
                duration REAL,
                soil_before REAL
            )
        ''')
        conn.commit()
        conn.close()

def clean_soil_anomalies(node_id):
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
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
        with db_lock:
            conn = sqlite3.connect(DB_FILE)
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
    if duration is None: duration = global_config["auto_water"]["duration"]
    
    # Assuming the pump actuator ID is 'pump'
    actuator_id = "pump"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 💦 开启水泵 (Node: {node_id}), 时长: {duration}s")
    success = hardware_manager.trigger_actuator(node_id, actuator_id, duration=duration)
    
    if success:
        with db_lock:
            conn = sqlite3.connect(DB_FILE)
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
            
            # 补光灯定时控制
            if global_config["auto_light"]["enabled"]:
                on_time, off_time = get_effective_light_times()
                time_val = now.hour * 60 + now.minute
                if on_time < off_time:
                    is_light_time = on_time <= time_val < off_time
                else:
                    is_light_time = time_val >= on_time or time_val < off_time
                    
                if global_mqtt_client:
                    cmd = "a1" if is_light_time else "b1"
                    l_node = global_config["auto_light"]["node_id"]
                    l_act = global_config["auto_light"]["actuator_id"]
                    hardware_manager.trigger_actuator(l_node, l_act, mqtt_client=global_mqtt_client, command=cmd)
            
            node_data_to_save = []
            
            # 采集本地节点数据
            for node_id in hardware_manager.local_sensors:
                data = local_latest_data.get(node_id, {})
                if data:
                    data = data.copy()
                    data["node_id"] = node_id
                    node_data_to_save.append(data)
                
                # 自动浇水逻辑判断
                if global_config["auto_water"]["enabled"] and global_config["auto_water"]["node_id"] == node_id:
                    if now.hour == 6 and can_water_now(node_id):
                        soil_pct = data.get("soil_moisture")
                        if soil_pct is not None and soil_pct < global_config["auto_water"]["threshold"]:
                            trigger_watering(node_id, soil_pct, global_config["auto_water"]["duration"])
            
            # 采集 MQTT 节点数据
            for node_id, info in mqtt_latest_data.items():
                if info["updated"]:
                    data = info["data"].copy()
                    data["node_id"] = node_id
                    node_data_to_save.append(data)
                    info["updated"] = False
                    
            # 存入数据库
            with db_lock:
                conn = sqlite3.connect(DB_FILE)
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
        sleep_sec = 600 - (seconds_passed % 600)
        if sleep_sec < 1: sleep_sec += 600
        time.sleep(sleep_sec)

def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("✅ 已成功连接到本地 MQTT Broker")
        topics = hardware_manager.get_mqtt_topics()
        for t in topics:
            client.subscribe(t)
            
        # 主动查询所有配置的 mqtt relay 状态
        for n_id, acts in hardware_manager.actuators.items():
            for a_id, actuator in acts.items():
                if hasattr(actuator, "topic"):
                    client.publish(actuator.topic, json.dumps({"command": "q1"}))
    else:
        print(f"❌ 连接失败，返回码: {reason_code}")

def on_mqtt_message(client, userdata, msg):
    global light_status
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        topic = msg.topic
        
        # 判断是否为某个继电器的反馈
        for acts in hardware_manager.actuators.values():
            for actuator in acts.values():
                if hasattr(actuator, "topic") and actuator.topic == topic:
                    info = data.get("information", "")
                    if "n1" in info:
                        if not camera_light_active:
                            light_status = "ON"
                    elif "f1" in info:
                        if not camera_light_active:
                            light_status = "OFF"
                    return
        
        # 更新传感器节点数据
        if topic in mqtt_topic_to_node:
            node_id = mqtt_topic_to_node[topic]
            mqtt_latest_data[node_id]["data"]["temperature"] = data.get("temperature")
            mqtt_latest_data[node_id]["data"]["humidity"] = data.get("humidity")
            mqtt_latest_data[node_id]["data"]["pressure"] = data.get("pressure")
            mqtt_latest_data[node_id]["updated"] = True
            
    except Exception as e:
        pass

@app.on_event("startup")
def start_background_logger():
    global global_mqtt_client
    load_config()
    threading.Thread(target=background_logger, daemon=True).start()
    threading.Thread(target=local_sensor_updater, daemon=True).start()
    
    try:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_message = on_mqtt_message
        mqtt_client.connect("127.0.0.1", 1883, 60)
        mqtt_client.loop_start()
        global_mqtt_client = mqtt_client
    except Exception as e:
        print(f"MQTT 启动失败: {e}")

# ==================== API 路由 ====================
@app.get("/api/nodes")
def get_nodes(x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    nodes_info = {}
    for node_id, config in hardware_manager.nodes.items():
        node_type = config.get("type", "unknown")
        has_system = (node_type == "local")
        actuators = config.get("actuators", {})
        has_settings = ("pump" in actuators or "light" in actuators)
        has_pump = ("pump" in actuators)
        
        nodes_info[node_id] = {
            "type": node_type,
            "description": config.get("description", f"Node {node_id}"),
            "has_system": has_system,
            "has_settings": has_settings,
            "has_pump": has_pump
        }
    return nodes_info

@app.get("/api/monitor")
def get_monitor_data(x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    
    nodes_data = {}
    
    # 读 Local Nodes
    for node_id in hardware_manager.local_sensors:
        if node_id in local_latest_data:
            nodes_data[node_id] = local_latest_data[node_id].copy()
        
    # 读 MQTT Nodes
    for node_id, info in mqtt_latest_data.items():
        nodes_data[node_id] = info["data"].copy()

    return {
        "timestamp": int(time.time()),
        "nodes": nodes_data,
        "light_status": light_status,
        "system_health": get_system_stats(),
        "system": {"device": "Robin (Zero 2 WH)", "status": "Healthy"}
    }

@app.get("/api/image")
def get_image(live: bool = False, hq: bool = False, x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    target_path = TMP_IMG_HQ_PATH if hq else TMP_IMG_PATH
    if live:
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            
            now = datetime.now()
            time_val = now.hour * 60 + now.minute
            on_time, off_time = get_effective_light_times()
            if on_time < off_time:
                is_light_time = on_time <= time_val < off_time
            else:
                is_light_time = time_val >= on_time or time_val < off_time
                
            global camera_light_active
            needs_temp_light = (not is_light_time) and (light_status != "ON")
            if needs_temp_light and global_mqtt_client:
                camera_light_active = True
                duration = 4 if hq else 2
                l_node = global_config["auto_light"]["node_id"]
                l_act = global_config["auto_light"]["actuator_id"]
                try:
                    hardware_manager.trigger_actuator(l_node, l_act, mqtt_client=global_mqtt_client, duration=duration)
                    time.sleep(0.6)
                except Exception:
                    pass

            try:
                with camera_lock:
                    if hq: cmd = ["rpicam-jpeg", "-o", target_path, "-t", "2000", "--width", "2592", "--height", "1944", "-q", "90", "--vflip", "--hflip", "--nopreview"]
                    else: cmd = ["rpicam-jpeg", "-o", target_path, "-t", "500", "--width", "648", "--height", "486", "-q", "80", "--vflip", "--hflip", "--nopreview"]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            finally:
                if needs_temp_light and global_mqtt_client:
                    try:
                        hardware_manager.trigger_actuator(l_node, l_act, mqtt_client=global_mqtt_client, command="b1")
                    except Exception:
                        pass
                    time.sleep(0.5)
                    camera_light_active = False
        except Exception:
            pass
    if os.path.exists(target_path):
        img_timestamp = str(int(os.path.getmtime(target_path)))
        return FileResponse(target_path, media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Image-Timestamp": img_timestamp})
    raise HTTPException(status_code=404, detail="Image not ready")

@app.get("/api/history")
def get_history_data(hist_type: str = "24h", node_id: str = "main", x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    try:
        with db_lock:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            if hist_type == "watering":
                cursor.execute('''
                    SELECT datetime(timestamp, 'localtime'), duration, soil_before 
                    FROM watering_log 
                    WHERE node_id=?
                    ORDER BY timestamp DESC LIMIT 30
                ''', (node_id,))
                rows = cursor.fetchall()
                conn.close()
                return [{"time": r[0], "duration": r[1], "soil": round(r[2], 1) if r[2] is not None else None} for r in rows]
                
            elif hist_type == "daily":
                cursor.execute('''
                    SELECT date(timestamp, 'localtime') as day, AVG(temperature), AVG(humidity), AVG(soil_moisture), AVG(pressure)
                    FROM node_data 
                    WHERE node_id=? AND (is_anomaly = 0 OR is_anomaly IS NULL) 
                    GROUP BY day ORDER BY day DESC LIMIT 30
                ''', (node_id,))
                rows = cursor.fetchall()
                conn.close()
                rows.reverse()
                return [{"time": r[0][5:], "temp": round(r[1], 1) if r[1] is not None else None, 
                         "hum": round(r[2], 1) if r[2] is not None else None, 
                         "soil": round(r[3], 1) if r[3] is not None else None,
                         "pressure": round(r[4], 1) if r[4] is not None else None} for r in rows]
                
            else: # 24h
                cursor.execute('''
                    SELECT datetime(timestamp, 'localtime'), temperature, humidity, soil_moisture, pressure 
                    FROM node_data 
                    WHERE node_id=? AND (is_anomaly = 0 OR is_anomaly IS NULL) 
                      AND timestamp >= datetime('now', '-24 hours')
                    ORDER BY timestamp DESC
                ''', (node_id,))
                rows = cursor.fetchall()
                conn.close()
                rows.reverse()
                return [{"time": r[0].split(" ")[1][:5] if " " in r[0] else r[0], 
                         "temp": round(r[1], 1) if r[1] is not None else None, 
                         "hum": round(r[2], 1) if r[2] is not None else None, 
                         "soil": round(r[3], 1) if r[3] is not None else None,
                         "pressure": round(r[4], 1) if r[4] is not None else None} for r in rows]
    except Exception as e:
        print(f"History API Error: {e}")
        return []

@app.post("/api/water")
def trigger_manual_watering(req: WaterRequest, x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != PI_SECRET_TOKEN: 
        raise HTTPException(status_code=403, detail="Forbidden")
    
    duration = max(0.1, min(req.duration, 1.0))
    node_id = req.node_id

    # 快速获取最新的湿度
    soil_pct = -1.0
    data = hardware_manager.read_local_node(node_id)
    if data and "soil_moisture" in data and data["soil_moisture"] is not None:
        soil_pct = data["soil_moisture"]
        
    success = trigger_watering(node_id, soil_pct, duration)
    
    if success:
        return {"status": "success"}
    else:
        raise HTTPException(status_code=500, detail="Hardware error or pump not configured")

@app.get("/api/config")
def get_config(x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    on_m, off_m = get_effective_light_times()
    res = global_config.copy()
    res["effective_light_on"] = f"{on_m//60:02d}:{on_m%60:02d}"
    res["effective_light_off"] = f"{off_m//60:02d}:{off_m%60:02d}"
    return res

@app.post("/api/config")
async def update_config(req: Request, x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    try:
        cfg = await req.json()
        save_config(cfg)
        return {"status": "success"}
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

@app.post("/api/light")
def toggle_manual_light(x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != PI_SECRET_TOKEN: 
        raise HTTPException(status_code=403, detail="Forbidden")
    
    global light_status
    if not global_mqtt_client:
        raise HTTPException(status_code=500, detail="MQTT not connected")
        
    new_cmd = "a1" if light_status != "ON" else "b1"
    
    # 强制预更新状态，防止因继电器状态未及时上报导致死锁
    light_status = "ON" if new_cmd == "a1" else "OFF"
    
    l_node = global_config["auto_light"]["node_id"]
    l_act = global_config["auto_light"]["actuator_id"]
    success = hardware_manager.trigger_actuator(l_node, l_act, mqtt_client=global_mqtt_client, command=new_cmd)
    
    if success:
        return {"status": "success"}
    else:
        raise HTTPException(status_code=500, detail="Hardware error or light relay not configured")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)