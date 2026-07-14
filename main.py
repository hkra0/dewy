import smbus2
import time
import subprocess
import os
import threading
import sqlite3
from datetime import datetime
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn
import paho.mqtt.client as mqtt
import json

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None

app = FastAPI(title="Robin Plant Monitor BFF")

class WaterRequest(BaseModel):
    duration: float = 0.5

# ==================== 统一路径与硬件锁配置 ====================
DATA_DIR = "/home/hkra/dewy/data"
TMP_IMG_PATH = f"{DATA_DIR}/live.jpg"
TMP_IMG_HQ_PATH = f"{DATA_DIR}/live_hq.jpg"
DB_FILE = f"{DATA_DIR}/plant_history.db"

sensor_lock = threading.Lock()
camera_lock = threading.Lock()
pump_lock = threading.Lock()
esp32_lock = threading.Lock()
PI_SECRET_TOKEN = "hKra_Secure_Sensor_2026_Token"

os.makedirs(DATA_DIR, exist_ok=True)

# ESP32 实时数据缓存
esp32_latest = {"temperature": "--", "humidity": "--", "pressure": "--"}
esp32_updated = False

# ==================== 自动浇水配置 ====================
PIN_PUMP = 4
WATERING_THRESHOLD = 70.0  
WATERING_DURATION = 0.5      

if GPIO:
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIN_PUMP, GPIO.IN)

# ==================== 传感器驱动类 ====================
class SHT30:
    def __init__(self, address=0x44):
        self.bus = smbus2.SMBus(1)
        self.address = address
        
    def read(self, samples=7):
        temps = []
        rhs = []
        for _ in range(samples):
            for attempt in range(3):
                try:
                    self.bus.write_i2c_block_data(self.address, 0x24, [0x00])
                    time.sleep(0.15) 
                    
                    data = self.bus.read_i2c_block_data(self.address, 0x00, 6)
                    t = -45.0 + (175.0 * float((data[0] << 8) | data[1]) / 65535.0)
                    h = 100.0 * (float((data[3] << 8) | data[4]) / 65535.0)
                    temps.append(t)
                    rhs.append(max(0.0, min(100.0, h)))
                    break
                except Exception as e:
                    try:
                        self.bus.write_i2c_block_data(self.address, 0x30, [0xA2])
                    except:
                        pass
                    if attempt < 2:
                        time.sleep(0.2)
                        
        if not temps:
            return None, None
            
        temps.sort()
        rhs.sort()
        trim = len(temps) // 4
        if trim > 0:
            valid_temps = temps[trim:-trim]
            valid_rhs = rhs[trim:-trim]
        else:
            valid_temps = temps
            valid_rhs = rhs
            
        avg_t = sum(valid_temps) / len(valid_temps)
        avg_h = sum(valid_rhs) / len(valid_rhs)
        return round(avg_t, 2), round(avg_h, 1)

class ADS1115_Soil:
    def __init__(self, address=0x48):
        self.bus = smbus2.SMBus(1)
        self.address = address
        self.VAL_AIR, self.VAL_WATER = 17545, 6883
        
    def read_moisture(self, samples=11):
        """中值平均滤波 + A3通道 VCC 比例补偿算法"""
        try:
            # 1. 先读取 A3 通道 (0xF3) 获取此刻真实的供电电压参考值
            self.bus.write_i2c_block_data(self.address, 0x01, [0xF3, 0x83])
            time.sleep(0.05)
            data_vcc = self.bus.read_i2c_block_data(self.address, 0x00, 2)
            vcc_raw = (data_vcc[0] << 8) | data_vcc[1]
            if vcc_raw > 32767: vcc_raw -= 65536
            if vcc_raw <= 0: return None
            
            # 2. 读取 A0 通道 (0xC3) 连续采样土壤数据
            raw_values = []
            for _ in range(samples):
                self.bus.write_i2c_block_data(self.address, 0x01, [0xC3, 0x83])
                time.sleep(0.05)
                data = self.bus.read_i2c_block_data(self.address, 0x00, 2)
                raw_val = (data[0] << 8) | data[1]
                if raw_val > 32767: raw_val -= 65536
                
                raw_values.append(raw_val)
                time.sleep(0.01)
                
            if not raw_values: return None
            
            # 排序并掐头去尾
            raw_values.sort()
            trim_count = len(raw_values) // 4
            if trim_count > 0:
                valid_raws = raw_values[trim_count:-trim_count]
            else:
                valid_raws = raw_values
                
            avg_raw = sum(valid_raws) / len(valid_raws)
            
            # 比例补偿 (Ratiometric Compensation)
            # 使用真实测试出的 2.8V 基准数据
            VCC_BASE = 22581.0 
            compensated_raw = avg_raw * (VCC_BASE / vcc_raw)
            
            percent = ((self.VAL_AIR - compensated_raw) / (self.VAL_AIR - self.VAL_WATER)) * 100.0
            return round(max(0.0, min(100.0, percent)), 1)
        except: return None 

class INA219_UPS:
    def __init__(self, address=0x43):
        self.bus = smbus2.SMBus(1)
        self.address = address
        try:
            self.bus.write_i2c_block_data(self.address, 0x00, [0x39, 0x9F])
            self.bus.write_i2c_block_data(self.address, 0x05, [0x1A, 0x00])
        except: pass
    def read_status(self):
        try:
            v_raw = ((self.bus.read_i2c_block_data(self.address, 0x02, 2)[0] << 8) | self.bus.read_i2c_block_data(self.address, 0x02, 2)[1]) >> 3
            c_raw = (self.bus.read_i2c_block_data(self.address, 0x04, 2)[0] << 8) | self.bus.read_i2c_block_data(self.address, 0x04, 2)[1]
            if c_raw > 32767: c_raw -= 65536
            voltage = v_raw * 0.004
            return round(voltage, 2), round(c_raw * 1.0, 1), 0.0
        except: return 0.0, 0.0, 0.0

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

sht, ups, soil = SHT30(), INA219_UPS(), ADS1115_Soil()

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS env_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            temperature REAL,
            humidity REAL,
            soil_moisture REAL,
            voltage REAL,
            current REAL,
            is_anomaly INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watering_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            duration REAL,
            soil_before REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS esp32_env_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            temperature REAL,
            humidity REAL,
            pressure REAL
        )
    ''')
    conn.commit()
    conn.close()

def clean_soil_anomalies(cursor):
    cursor.execute("SELECT id, soil_moisture FROM env_log ORDER BY id DESC LIMIT 5")
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
            cursor.execute(f"UPDATE env_log SET is_anomaly = 1 WHERE id IN ({placeholders})", anomaly_ids)

def can_water_now():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp FROM watering_log ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if not row: return True
        last_utc = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        diff_hours = (datetime.utcnow() - last_utc).total_seconds() / 3600
        return diff_hours > 12
    except Exception:
        return False

def trigger_watering(soil_before, duration=WATERING_DURATION):
    if not GPIO: return False
    with pump_lock:
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 💦 开启水泵 (OUT / LOW), 时长: {duration}s")
            GPIO.setup(PIN_PUMP, GPIO.OUT)
            GPIO.output(PIN_PUMP, GPIO.LOW)
            time.sleep(duration)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 关闭水泵 (切回 IN)")
            GPIO.setup(PIN_PUMP, GPIO.IN)
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO watering_log (duration, soil_before) VALUES (?, ?)", (duration, soil_before))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"❌ 浇水异常: {e}")
            GPIO.setup(PIN_PUMP, GPIO.IN) 
            return False

def background_logger():
    global esp32_updated
    init_db()
    while True:
        try:
            with sensor_lock:
                temp, rh = sht.read()
                soil_pct = soil.read_moisture()
                v, c, _ = ups.read_status()
            
            now = datetime.now()
            
            if now.hour == 6 and can_water_now():
                if soil_pct is not None and soil_pct < WATERING_THRESHOLD:
                    trigger_watering(soil_pct)
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO env_log (temperature, humidity, soil_moisture, voltage, current)
                VALUES (?, ?, ?, ?, ?)
            ''', (temp, rh, soil_pct, v, c))
            clean_soil_anomalies(cursor)
            
            # 保存 ESP32 历史数据
            with esp32_lock:
                e_temp = esp32_latest.get("temperature")
                e_hum = esp32_latest.get("humidity")
                e_pres = esp32_latest.get("pressure")
                e_upd = esp32_updated
                esp32_updated = False
            
            # 如果从没收到过数据或为 "--"，则记为 None
            if e_temp != "--" and e_hum != "--" and e_pres != "--" and e_upd:
                cursor.execute('''
                    INSERT INTO esp32_env_log (temperature, humidity, pressure)
                    VALUES (?, ?, ?)
                ''', (e_temp, e_hum, e_pres))

            conn.commit()
            conn.close()
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
        client.subscribe("sensor/esp32/env_data")
    else:
        print(f"❌ 连接失败，返回码: {reason_code}")

def on_mqtt_message(client, userdata, msg):
    global esp32_updated
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        with esp32_lock:
            esp32_latest["temperature"] = data.get('temperature', "--")
            esp32_latest["humidity"] = data.get('humidity', "--")
            esp32_latest["pressure"] = data.get('pressure', "--")
            esp32_updated = True
    except Exception as e:
        pass

@app.on_event("startup")
def start_background_logger():
    threading.Thread(target=background_logger, daemon=True).start()
    
    # 初始化 MQTT 客户端
    try:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_message = on_mqtt_message
        mqtt_client.connect("127.0.0.1", 1883, 60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"MQTT 启动失败: {e}")

# ==================== API 路由 ====================
@app.get("/api/monitor")
def get_monitor_data(x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    with sensor_lock:
        temp, rh = sht.read()
        soil_pct = soil.read_moisture()
        v, c, _ = ups.read_status()
        
    return {
        "timestamp": int(time.time()),
        "environment": {
            "temperature": temp if temp is not None else "--", 
            "humidity": rh if rh is not None else "--", 
            "soil_moisture": soil_pct if soil_pct is not None else "--"
        },
        "esp32": esp32_latest,
        "power": {"voltage": v, "current": c, "status": "监控中"},
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
            with camera_lock:
                if hq: cmd = ["rpicam-jpeg", "-o", target_path, "-t", "2000", "--width", "2592", "--height", "1944", "-q", "90", "--vflip", "--hflip", "--nopreview"]
                else: cmd = ["rpicam-jpeg", "-o", target_path, "-t", "500", "--width", "648", "--height", "486", "-q", "80", "--vflip", "--hflip", "--nopreview"]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    if os.path.exists(target_path):
        img_timestamp = str(int(os.path.getmtime(target_path)))
        return FileResponse(target_path, media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Image-Timestamp": img_timestamp})
    raise HTTPException(status_code=404, detail="Image not ready")

@app.get("/api/history")
def get_history_data(hist_type: str = "24h", x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        if hist_type == "watering":
            cursor.execute('''
                SELECT datetime(timestamp, 'localtime'), duration, soil_before 
                FROM watering_log 
                ORDER BY timestamp DESC LIMIT 30
            ''')
            rows = cursor.fetchall()
            conn.close()
            return [{"time": r[0], "duration": r[1], "soil": round(r[2], 1) if r[2] is not None else None} for r in rows]
            
        elif hist_type == "daily":
            cursor.execute('''
                SELECT date(timestamp, 'localtime') as day, AVG(temperature), AVG(humidity), AVG(soil_moisture)
                FROM env_log WHERE is_anomaly = 0 OR is_anomaly IS NULL GROUP BY day ORDER BY day DESC LIMIT 30
            ''')
            rows = cursor.fetchall()
            conn.close()
            rows.reverse()
            return [{"time": r[0][5:], "temp": round(r[1], 1) if r[1] is not None else None, "hum": round(r[2], 1) if r[2] is not None else None, "soil": round(r[3], 1) if r[3] is not None else None} for r in rows]
            
        elif hist_type == "sub1_daily":
            cursor.execute('''
                SELECT date(timestamp, 'localtime') as day, AVG(temperature), AVG(humidity), AVG(pressure)
                FROM esp32_env_log GROUP BY day ORDER BY day DESC LIMIT 30
            ''')
            rows = cursor.fetchall()
            conn.close()
            rows.reverse()
            return [{"time": r[0][5:], "temp": round(r[1], 1) if r[1] is not None else None, "hum": round(r[2], 1) if r[2] is not None else None, "pressure": round(r[3], 1) if r[3] is not None else None} for r in rows]
            
        elif hist_type == "sub1_24h":
            cursor.execute('''
                SELECT datetime(timestamp, 'localtime'), temperature, humidity, pressure 
                FROM esp32_env_log 
                WHERE timestamp >= datetime('now', '-24 hours')
                ORDER BY timestamp DESC
            ''')
            rows = cursor.fetchall()
            conn.close()
            rows.reverse()
            return [{"time": r[0].split(" ")[1][:5] if " " in r[0] else r[0], "temp": round(r[1], 1) if r[1] is not None else None, "hum": round(r[2], 1) if r[2] is not None else None, "pressure": round(r[3], 1) if r[3] is not None else None} for r in rows]
            
        else:
            cursor.execute('''
                SELECT datetime(timestamp, 'localtime'), temperature, humidity, soil_moisture 
                FROM env_log 
                WHERE (is_anomaly = 0 OR is_anomaly IS NULL) 
                  AND timestamp >= datetime('now', '-24 hours')
                ORDER BY timestamp DESC
            ''')
            rows = cursor.fetchall()
            conn.close()
            rows.reverse()
            return [{"time": r[0].split(" ")[1][:5] if " " in r[0] else r[0], "temp": round(r[1], 1) if r[1] is not None else None, "hum": round(r[2], 1) if r[2] is not None else None, "soil": round(r[3], 1) if r[3] is not None else None} for r in rows]
    except Exception as e:
        print(f"History API Error: {e}")
        return []

# 手动浇水 API
@app.post("/api/water")
def trigger_manual_watering(req: WaterRequest, x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != PI_SECRET_TOKEN: 
        raise HTTPException(status_code=403, detail="Forbidden")
    
    # 限制浇水时长不超过 1 秒，防止意外水漫金山
    duration = max(0.1, min(req.duration, 1.0))

    # 快速读取当前湿度用于日志记录 (减少采样次数避免接口卡顿)
    with sensor_lock:
        soil_pct = soil.read_moisture(samples=5)
        
    success = trigger_watering(soil_pct if soil_pct is not None else -1.0, duration)
    
    if success:
        return {"status": "success"}
    else:
        raise HTTPException(status_code=500, detail="Hardware error")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)