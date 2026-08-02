import hmac
import logging
import os
import re
import subprocess
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

import core.state as state
import core.config as config
import core.database as db
from core.logic import trigger_watering, get_effective_light_times, get_system_stats, compute_next_boundary

logger = logging.getLogger(__name__)


def verify_pi_token(x_bff_to_pi_token: str = Header(None)):
    """校验 BFF(Worker) → Pi 的共享密钥。

    挂在 router 上而不是逐个端点写：新增端点自动受保护，
    漏写一处就是一个鉴权洞——这正是 agent.md「七、鉴权」强调的"无旁路"。
    要放开某个端点必须显式声明，不会因为忘了粘贴而默默敞开。
    """
    if not x_bff_to_pi_token or not hmac.compare_digest(x_bff_to_pi_token, state.PI_SECRET_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")


router = APIRouter(dependencies=[Depends(verify_pi_token)])

class WaterRequest(BaseModel):
    duration: float = 0.5
    node_id: str = "main"

@router.get("/api/nodes")
def get_nodes():
    return state.hardware_manager.nodes

@router.get("/api/monitor")
def get_monitor_data():
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
def get_image(live: bool = False, hq: bool = False, since: int = 0):
    """返回预览图。

    `live=true` 才会真正调用 rpicam 抓新图；不带 live 时只是把磁盘上
    已有的那张发回去。

    `since` 是客户端已持有的图片时间戳（秒）。前端 30 秒轮询一次，而这张
    图只在有人显式请求 live 时才会被重写——不带条件的话，每次轮询都在重下
    同一张几十 KB 的 JPEG，穿过 Cloudflare 与隧道白烧流量。带上 since 后
    未变更直接回 304，仍然保留了"别的客户端拍了新图，本客户端下一轮就能
    看到"的语义。
    """
    target_path = state.TMP_IMG_HQ_PATH if hq else state.TMP_IMG_PATH

    # 条件请求只对非 live 有意义：live 的整个目的就是拍一张新的。
    if not live and since > 0 and os.path.exists(target_path):
        if int(os.path.getmtime(target_path)) <= since:
            return Response(status_code=304, headers={"Cache-Control": "no-store"})

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
                except Exception as e:
                    logger.warning("拍照前临时补光失败: %s", e)

            with state.camera_lock:
                if hq: cmd = ["rpicam-jpeg", "-o", target_path, "-t", "2000", "--width", "2592", "--height", "1944", "-q", "90", "--vflip", "--hflip", "--nopreview"]
                else: cmd = ["rpicam-jpeg", "-o", target_path, "-t", "500", "--width", "648", "--height", "486", "-q", "60", "--vflip", "--hflip", "--nopreview"]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            logger.exception("实时拍照失败 (hq=%s)", hq)
        finally:
            state.camera_in_progress = False
    if os.path.exists(target_path):
        img_timestamp = str(int(os.path.getmtime(target_path)))
        return FileResponse(target_path, media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Image-Timestamp": img_timestamp})
    raise HTTPException(status_code=404, detail="Image not ready")

@router.get("/api/history")
def get_history_data(hist_type: str = "24h", node_id: str = "main"):
    try:
        if hist_type == "watering":
            rows = db.query_watering_history(node_id)
            return [{"time": r[0], "duration": r[1], "soil": round(r[2], 1) if r[2] is not None else None} for r in rows]

        elif hist_type == "daily":
            rows, water_rows = db.query_daily_history(node_id)
            watering_map = {r[0]: round(r[1], 1) if r[1] is not None else 0 for r in water_rows}
            rows = list(rows)
            rows.reverse()
            return [{"time": r[0][5:], "temp": round(r[1], 1) if r[1] is not None else None,
                     "hum": round(r[2], 1) if r[2] is not None else None,
                     "soil": round(r[3], 1) if r[3] is not None else None,
                     "pressure": round(r[4], 1) if r[4] is not None else None,
                     "water": watering_map.get(r[0], 0)} for r in rows]

        else: # 24h
            sensor_rows, water_rows = db.query_24h_history(node_id)

            timeline = {}
            for r in sensor_rows:
                time_str = r[0]
                epoch = int(r[5]) if r[5] is not None else 0
                timeline[time_str] = {
                    "time": time_str,
                    "epoch": epoch,
                    "temp": round(r[1], 1) if r[1] is not None else None,
                    "hum": round(r[2], 1) if r[2] is not None else None,
                    "soil": round(r[3], 1) if r[3] is not None else None,
                    "pressure": round(r[4], 1) if r[4] is not None else None,
                    "water": 0
                }

            for w in water_rows:
                if w[0] is None or w[1] is None: continue
                time_str = w[0]
                dur = float(w[1])
                soil_val = round(w[2], 1) if w[2] is not None and w[2] >= 0 else None
                epoch = int(w[3]) if w[3] is not None else 0
                if time_str in timeline:
                    timeline[time_str]["water"] = round(timeline[time_str]["water"] + dur, 1)
                    if timeline[time_str]["soil"] is None and soil_val is not None:
                        timeline[time_str]["soil"] = soil_val
                else:
                    timeline[time_str] = {
                        "time": time_str,
                        "epoch": epoch,
                        "temp": None,
                        "hum": None,
                        "soil": soil_val,
                        "pressure": None,
                        "water": dur
                    }

            sorted_points = sorted(timeline.values(), key=lambda x: x["epoch"])
            return [{"time": p["time"],
                     "temp": p["temp"],
                     "hum": p["hum"],
                     "soil": p["soil"],
                     "pressure": p["pressure"],
                     "water": p["water"] if p["water"] > 0 else 0} for p in sorted_points]
    except Exception:
        logger.exception("查询历史数据失败 (type=%s node=%s)", hist_type, node_id)
        return []

@router.post("/api/water")
def trigger_manual_watering(req: WaterRequest):
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
def get_config_endpoint():
    on_m, off_m = get_effective_light_times()
    res = config.global_config.copy()
    res["effective_light_on"] = f"{on_m//60:02d}:{on_m%60:02d}"
    res["effective_light_off"] = f"{off_m//60:02d}:{off_m%60:02d}"
    return res

@router.post("/api/config")
async def update_config(req: Request):
    try:
        cfg = await req.json()
        config.save_config(cfg)
        return {"status": "success"}
    except ValueError as e:
        logger.warning("配置更新请求体非法: %s", e)
        raise HTTPException(status_code=400, detail="Invalid JSON")

@router.post("/api/light")
def toggle_manual_light():
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
    logger.info("🔧 手动切灯: %s，覆盖至 %s",
                state.light_status, state.manual_override_until.strftime('%H:%M'))
    
    l_node = config.global_config["auto_light"]["node_id"]
    l_act = config.global_config["auto_light"]["actuator_id"]
    success = state.hardware_manager.trigger_actuator(l_node, l_act, mqtt_client=state.global_mqtt_client, command=new_cmd, retain=True)
    
    if success:
        return {"status": "success"}
    else:
        raise HTTPException(status_code=500, detail="Hardware error or light relay not configured")

@router.get("/api/photos")
def get_photo_list():
    try:
        rows = db.query_photos_desc()
        return [{"date": r[0], "size": r[1], "thumb_size": r[2], "timestamp": str(r[3]) if r[3] else ""} for r in rows]
    except Exception:
        logger.exception("查询照片列表失败")
        return []

@router.get("/api/photos/{date}")
def get_photo(date: str, thumb: bool = False):
    # 验证日期格式
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
