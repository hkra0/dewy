import hmac
import logging
import os
import re
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

import core.state as state
import core.config as config
import core.database as db
from core.logic import (
    trigger_watering,
    get_effective_light_times,
    get_system_stats,
    compute_next_boundary,
    set_light,
    fill_light_for_capture,
    daily_photo_capture,
    node_capabilities,
)

logger = logging.getLogger(__name__)


def verify_pi_token(x_bff_to_pi_token: str = Header(None)):
    """校验 BFF(Worker) → Pi 的共享密钥。

    挂在 router 上而不是逐个端点写：新增端点自动受保护，
    漏写一处就是一个鉴权洞——这正是 AGENTS.md「七、鉴权」强调的"无旁路"。
    要放开某个端点必须显式声明，不会因为忘了粘贴而默默敞开。
    """
    if not x_bff_to_pi_token or not hmac.compare_digest(x_bff_to_pi_token, state.PI_SECRET_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")


router = APIRouter(dependencies=[Depends(verify_pi_token)])

class WaterRequest(BaseModel):
    duration: float = 0.5
    node_id: str = "main"

# 允许发给前端的节点字段。白名单而非黑名单：hardware_config 的节点段里还放着
# ESP32 的构建参数（wifi_password、mqtt_host…），逐个去黑名单迟早漏一个，
# 而这个端点只要 viewer key 就能读。
_PUBLIC_NODE_FIELDS = ("type", "description")


@router.get("/api/nodes")
def get_nodes():
    """节点列表与各节点的能力。

    前端据此决定显示哪些卡片与页签。能力由 `logic.node_capabilities` 算而不是
    让前端翻原始配置：水泵/灯的执行器 id 是可配的，相机也可能压根没在配置里
    出现（此时用默认相机），每日照片还能被开关关掉——这些判断规则不该散落在
    五个前端模块里各写一份。此处只负责组装响应。

    能力放在这个端点而不是 `/api/config`：后者要浇水密钥，而页签显隐对只有
    viewer key 的访客同样要成立。
    """
    hm = state.hardware_manager

    result = {}
    for node_id, node_info in hm.nodes.items():
        public = {k: node_info[k] for k in _PUBLIC_NODE_FIELDS if k in node_info}
        public["sensors"] = sorted(hm.local_sensors.get(node_id, {}))
        public["actuators"] = sorted(hm.actuators.get(node_id, {}))
        public["capabilities"] = node_capabilities(node_id)
        result[node_id] = public

    return result

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
        "system": {"device": "Raspberry Pi Zero 2 WH", "status": "Healthy"}
    }

@router.get("/api/image")
def get_image(live: bool = False, hq: bool = False, since: int = 0):
    """返回预览图。

    `live=true` 才会真正驱动相机抓新图；不带 live 时只是把磁盘上
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

            fill_light_for_capture(4 if hq else 2)

            camera = state.hardware_manager.get_camera()
            if camera is None:
                logger.error("未配置任何相机，无法拍照")
            else:
                with state.camera_lock:
                    camera.capture(target_path, hq=hq)
        except Exception:
            logger.exception("实时拍照失败 (hq=%s)", hq)
        finally:
            state.camera_in_progress = False
    if os.path.exists(target_path):
        img_timestamp = str(int(os.path.getmtime(target_path)))
        return FileResponse(target_path, media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Image-Timestamp": img_timestamp})
    raise HTTPException(status_code=404, detail="Image not ready")

def _group_metrics(rows):
    """[(时间桶, key, 值), ...] → {时间桶: {key: 值}}。

    同一个桶里同名 key 出现多次时后者覆盖前者（24h 视图里一分钟内
    多次采样才会发生），与 node_data 那边"同一时刻只留一行"的行为一致。
    """
    grouped = {}
    for bucket, key, value in rows:
        if value is None:
            continue
        grouped.setdefault(bucket, {})[key] = round(value, 2)
    return grouped


@router.get("/api/history")
def get_history_data(hist_type: str = "24h", node_id: str = "main"):
    try:
        if hist_type == "watering":
            rows = db.query_watering_history(node_id)
            return [{"time": r[0], "duration": r[1],
                     "soil": round(r[2], 1) if r[2] is not None else None,
                     "pulses": r[3] if r[3] is not None else 1,
                     "soil_after": round(r[4], 1) if r[4] is not None else None} for r in rows]

        elif hist_type == "daily":
            rows, water_rows = db.query_daily_history(node_id)
            watering_map = {r[0]: round(r[1], 1) if r[1] is not None else 0 for r in water_rows}
            extra_map = _group_metrics(db.query_daily_metrics(node_id))
            rows = list(rows)
            rows.reverse()
            return [{"time": r[0][5:], "temp": round(r[1], 1) if r[1] is not None else None,
                     "hum": round(r[2], 1) if r[2] is not None else None,
                     "soil": round(r[3], 1) if r[3] is not None else None,
                     "pressure": round(r[4], 1) if r[4] is not None else None,
                     "water": watering_map.get(r[0], 0),
                     "extra": extra_map.get(r[0], {})} for r in rows]

        else: # 24h
            sensor_rows, water_rows = db.query_24h_history(node_id)
            extra_map = _group_metrics(db.query_24h_metrics(node_id))

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
                    "water": 0,
                    "extra": extra_map.get(time_str, {})
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
                        "water": dur,
                        "extra": extra_map.get(time_str, {})
                    }

            sorted_points = sorted(timeline.values(), key=lambda x: x["epoch"])
            return [{"time": p["time"],
                     "temp": p["temp"],
                     "hum": p["hum"],
                     "soil": p["soil"],
                     "pressure": p["pressure"],
                     "water": p["water"] if p["water"] > 0 else 0,
                     "extra": p["extra"]} for p in sorted_points]
    except Exception:
        logger.exception("查询历史数据失败 (type=%s node=%s)", hist_type, node_id)
        return []

@router.get("/api/metrics")
def get_extra_metrics(node_id: str = "main", key: str = None, hours: int = 24):
    """node_data 固定列之外的测量量（照度、EC、CO₂…）。

    不带 key 时列出该节点有哪些指标及其最新值；带 key 时返回该指标的历史序列。
    内置图表只画固定列，这些指标供外部消费与自定义前端使用。
    """
    try:
        if key:
            points = db.query_metric_history(node_id, key, hours=hours)
            return {"node_id": node_id, "key": key,
                    "points": [{"time": t, "value": v} for t, v in points]}
        return {"node_id": node_id,
                "keys": db.query_metric_keys(node_id),
                "latest": db.query_latest_metrics(node_id)}
    except Exception:
        logger.exception("查询额外指标失败 (node=%s key=%s)", node_id, key)
        return {"node_id": node_id, "keys": [], "latest": {}}


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
        
    turn_on = state.light_status != "ON"

    now = datetime.now()
    on_time, off_time = get_effective_light_times()
    state.manual_override = True
    state.manual_override_until = compute_next_boundary(now, on_time, off_time)

    state.light_status = "ON" if turn_on else "OFF"
    logger.info("🔧 手动切灯: %s，覆盖至 %s",
                state.light_status, state.manual_override_until.strftime('%H:%M'))

    success = set_light(turn_on, retain=True)

    if success:
        return {"status": "success"}
    else:
        raise HTTPException(status_code=500, detail="Hardware error or light relay not configured")

@router.post("/api/photo/retake")
def retake_daily_photo(force: bool = False):
    """立即重拍当日照片（设置页的手动入口）。

    路径特意不写成 `/api/photos/retake`：Worker 里 `/api/photos/` 整个前缀
    归 viewer key 管，落在那下面等于把一个会驱动硬件的端点降级成只读鉴权。

    两个失败码前端要分开处理，所以不能共用 409——Worker 只透传状态码，
    会把 body 换成自己的错误 JSON，detail 到不了浏览器：
      409 当天已有照片，需要用户确认覆盖（前端据此进入"再点一次"状态）
      423 相机正忙，稍后再试
    """
    if state.camera_in_progress:
        raise HTTPException(status_code=423, detail="Camera capture in progress")

    today = datetime.now().strftime("%Y-%m-%d")
    if not force and db.photo_exists(today):
        raise HTTPException(status_code=409, detail="Photo already exists for today")

    # 与实时抓拍共用这个标志：拍摄期间的手动切灯会被 /api/light 挡掉，
    # 否则用户在这十几秒里切灯，等于对着正在曝光的镜头开关灯。
    state.camera_in_progress = True
    try:
        ok = daily_photo_capture(force=True)
    finally:
        state.camera_in_progress = False

    if not ok:
        raise HTTPException(status_code=500, detail="Capture failed")
    return {"status": "success", "date": today}


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


class ExportTimelapseRequest(BaseModel):
    format: str = "mp4"
    quality: str = "hd"
    fps: float = 2.0
    watermark: bool = True
    max_frames: int = 120


@router.post("/api/photos/export")
def export_photos_timelapse(req: ExportTimelapseRequest):
    try:
        from core.logic.photo_export import export_timelapse
        output_path = export_timelapse(
            export_format=req.format,
            quality=req.quality,
            fps=req.fps,
            watermark=req.watermark,
            max_frames=req.max_frames,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except RuntimeError as re_err:
        raise HTTPException(status_code=500, detail=str(re_err))
    except Exception as e:
        logger.exception("导出延时文件失败")
        raise HTTPException(status_code=500, detail=f"Export failed: {e}")

    filename = os.path.basename(output_path)
    media_type = "video/mp4" if req.format.lower() == "mp4" else "image/gif"
    return FileResponse(
        output_path,
        media_type=media_type,
        filename=filename,
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )

