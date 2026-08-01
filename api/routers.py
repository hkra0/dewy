import os
import time
import subprocess
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

import core.state as state
import core.config as config
from core.logic import trigger_watering, get_effective_light_times, get_system_stats, compute_next_boundary

router = APIRouter()

class WaterRequest(BaseModel):
    duration: float = 0.5
    node_id: str = "main"

@router.get("/api/nodes")
def get_nodes(x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != state.PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    return state.hardware_manager.nodes

@router.get("/api/monitor")
def get_monitor_data(x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != state.PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    
    nodes_data = {}
    
    for node_id in state.hardware_manager.local_sensors:
        if node_id in state.local_latest_data:
            nodes_data[node_id] = state.local_latest_data[node_id].copy()
        
    for node_id, info in state.mqtt_latest_data.items():
        nodes_data[node_id] = info["data"].copy()

    return {
        "timestamp": int(time.time()),
        "nodes": nodes_data,
        "light_status": state.light_status,
        "system_health": get_system_stats(),
        "system": {"device": "Robin (Zero 2 WH)", "status": "Healthy"}
    }

@router.get("/api/image")
def get_image(live: bool = False, hq: bool = False, x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != state.PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    target_path = state.TMP_IMG_HQ_PATH if hq else state.TMP_IMG_PATH
    if live:
        state.camera_in_progress = True
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            
            needs_temp_light = (state.light_status != "ON") and state.global_mqtt_client
            l_node = config.global_config["auto_light"]["node_id"]
            l_act = config.global_config["auto_light"]["actuator_id"]
            
            if needs_temp_light:
                duration = 4 if hq else 2
                state.ignore_light_feedback_until = time.time() + duration + 3
                try:
                    state.hardware_manager.trigger_actuator(l_node, l_act, mqtt_client=state.global_mqtt_client, duration=duration)
                    time.sleep(0.6)
                except Exception:
                    pass

            try:
                with state.camera_lock:
                    if hq: cmd = ["rpicam-jpeg", "-o", target_path, "-t", "2000", "--width", "2592", "--height", "1944", "-q", "90", "--vflip", "--hflip", "--nopreview"]
                    else: cmd = ["rpicam-jpeg", "-o", target_path, "-t", "500", "--width", "648", "--height", "486", "-q", "60", "--vflip", "--hflip", "--nopreview"]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            finally:
                pass
        except Exception:
            pass
        finally:
            state.camera_in_progress = False
    if os.path.exists(target_path):
        img_timestamp = str(int(os.path.getmtime(target_path)))
        return FileResponse(target_path, media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Image-Timestamp": img_timestamp})
    raise HTTPException(status_code=404, detail="Image not ready")

@router.get("/api/history")
def get_history_data(hist_type: str = "24h", node_id: str = "main", x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != state.PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    try:
        with state.db_lock:
            conn = sqlite3.connect(state.DB_FILE)
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

                cursor.execute('''
                    SELECT date(timestamp, 'localtime') as day, SUM(duration)
                    FROM watering_log 
                    WHERE node_id=? AND timestamp >= datetime('now', '-35 days')
                    GROUP BY day
                ''', (node_id,))
                watering_map = {r[0]: round(r[1], 1) if r[1] is not None else 0 for r in cursor.fetchall()}
                conn.close()
                rows.reverse()
                return [{"time": r[0][5:], "temp": round(r[1], 1) if r[1] is not None else None, 
                         "hum": round(r[2], 1) if r[2] is not None else None, 
                         "soil": round(r[3], 1) if r[3] is not None else None,
                         "pressure": round(r[4], 1) if r[4] is not None else None,
                         "water": watering_map.get(r[0], 0)} for r in rows]
                
            else: # 24h
                cursor.execute('''
                    SELECT strftime('%H:%M', timestamp, 'localtime'), temperature, humidity, soil_moisture, pressure, strftime('%s', timestamp)
                    FROM node_data 
                    WHERE node_id=? AND (is_anomaly = 0 OR is_anomaly IS NULL) 
                      AND timestamp >= datetime('now', '-24 hours')
                    ORDER BY timestamp ASC
                ''', (node_id,))
                rows = cursor.fetchall()

                cursor.execute('''
                    SELECT strftime('%s', timestamp), duration 
                    FROM watering_log 
                    WHERE node_id=? AND timestamp >= datetime('now', '-24 hours')
                ''', (node_id,))
                w_rows = cursor.fetchall()
                conn.close()

                water_map = [0.0] * len(rows)
                if rows and w_rows:
                    row_ts = [int(r[5]) if r[5] is not None else 0 for r in rows]
                    for w in w_rows:
                        if w[0] is None or w[1] is None: continue
                        w_ts = int(w[0])
                        w_dur = float(w[1])
                        best_idx = 0
                        min_diff = float('inf')
                        for idx, ts in enumerate(row_ts):
                            diff = abs(ts - w_ts)
                            if diff < min_diff:
                                min_diff = diff
                                best_idx = idx
                        if min_diff <= 7200:
                            water_map[best_idx] = round(water_map[best_idx] + w_dur, 1)

                return [{"time": r[0], 
                         "temp": round(r[1], 1) if r[1] is not None else None, 
                         "hum": round(r[2], 1) if r[2] is not None else None, 
                         "soil": round(r[3], 1) if r[3] is not None else None,
                         "pressure": round(r[4], 1) if r[4] is not None else None,
                         "water": water_map[i] if water_map[i] > 0 else 0} for i, r in enumerate(rows)]
    except Exception as e:
        print(f"History API Error: {e}")
        return []

@router.post("/api/water")
def trigger_manual_watering(req: WaterRequest, x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != state.PI_SECRET_TOKEN: 
        raise HTTPException(status_code=403, detail="Forbidden")
    
    duration = max(0.1, min(req.duration, 1.0))
    node_id = req.node_id

    soil_pct = -1.0
    data = state.hardware_manager.read_local_node(node_id)
    if data and "soil_moisture" in data and data["soil_moisture"] is not None:
        soil_pct = data["soil_moisture"]
        
    success = trigger_watering(node_id, soil_pct, duration)
    
    if success:
        return {"status": "success"}
    else:
        raise HTTPException(status_code=500, detail="Hardware error or pump not configured")

@router.get("/api/config")
def get_config_endpoint(x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != state.PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    on_m, off_m = get_effective_light_times()
    res = config.global_config.copy()
    res["effective_light_on"] = f"{on_m//60:02d}:{on_m%60:02d}"
    res["effective_light_off"] = f"{off_m//60:02d}:{off_m%60:02d}"
    return res

@router.post("/api/config")
async def update_config(req: Request, x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != state.PI_SECRET_TOKEN: raise HTTPException(status_code=403, detail="Forbidden")
    try:
        cfg = await req.json()
        config.save_config(cfg)
        return {"status": "success"}
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

@router.post("/api/light")
def toggle_manual_light(x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != state.PI_SECRET_TOKEN: 
        raise HTTPException(status_code=403, detail="Forbidden")
    
    if not state.global_mqtt_client:
        raise HTTPException(status_code=500, detail="MQTT not connected")
    if state.camera_in_progress:
        raise HTTPException(status_code=409, detail="Camera capture in progress")
        
    new_cmd = "a1" if state.light_status != "ON" else "b1"
    
    now = datetime.now()
    on_time, off_time = get_effective_light_times()
    state.manual_override = True
    state.manual_override_until = compute_next_boundary(now, on_time, off_time)
    
    state.light_status = "ON" if new_cmd == "a1" else "OFF"
    print(f"[{now.strftime('%H:%M:%S')}] 🔧 手动切灯: {state.light_status}，覆盖至 {state.manual_override_until.strftime('%H:%M')}")
    
    l_node = config.global_config["auto_light"]["node_id"]
    l_act = config.global_config["auto_light"]["actuator_id"]
    success = state.hardware_manager.trigger_actuator(l_node, l_act, mqtt_client=state.global_mqtt_client, command=new_cmd, retain=True)
    
    if success:
        return {"status": "success"}
    else:
        raise HTTPException(status_code=500, detail="Hardware error or light relay not configured")

@router.get("/api/photos")
def get_photo_list(x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != state.PI_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        with state.db_lock:
            conn = sqlite3.connect(state.DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT date, file_size, thumb_size, timestamp FROM photo_log ORDER BY date DESC")
            rows = cursor.fetchall()
            conn.close()
        return [{"date": r[0], "size": r[1], "thumb_size": r[2], "timestamp": str(r[3]) if r[3] else ""} for r in rows]
    except Exception as e:
        print(f"Photo list API Error: {e}")
        return []

@router.get("/api/photos/{date}")
def get_photo(date: str, thumb: bool = False, x_bff_to_pi_token: str = Header(None)):
    if x_bff_to_pi_token != state.PI_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    # 验证日期格式
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
    
    if thumb:
        target = os.path.join(state.THUMB_DIR, f"{date}.jpg")
    else:
        target = os.path.join(state.PHOTO_DIR, f"{date}.jpg")
    
    if os.path.exists(target):
        if date == datetime.now().strftime("%Y-%m-%d"):
            cache_header = "no-cache, no-store, must-revalidate"
        else:
            cache_header = "public, max-age=86400"
        return FileResponse(target, media_type="image/jpeg", headers={"Cache-Control": cache_header})
    raise HTTPException(status_code=404, detail="Photo not found")
