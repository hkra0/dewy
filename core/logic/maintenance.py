"""Authenticated MQTT maintenance, bounded logs and stop-and-wait OTA transfers.

No firmware URLs or inbound ESP ports: the Pi sends 768-byte chunks over MQTT.
Only a matching, signed result from a validated new boot confirms success.
Runtime state is deliberately bounded and ephemeral; restarting the Pi cancels jobs.
"""
import base64
from collections import deque
import hashlib
import hmac
import json
import re
import secrets
import threading
import time

import core.state as state

MAX_FIRMWARE = 4 * 1024 * 1024
CHUNK_SIZE = 768
BOOT_CONFIRM_TIMEOUT = 210  # 120s device trial deadline plus rollback/reconnection budget.
ACTIVE_STATUSES = ("sending", "rebooting", "verifying")
_condition = threading.Condition(threading.RLock())
_nodes = {}
_jobs = {}


def _info(node_id):
    info = state.hardware_manager.mqtt_nodes.get(node_id)
    if not info or not info.get("config_topic"):
        raise ValueError("Unknown maintenance node")
    if len(info.get("maintenance_key", "")) < 32:
        raise ValueError("Configure a per-node maintenance_key of at least 32 characters first")
    return info


def topics():
    return {f"{info['config_topic']}/maintenance/state": node
            for node, info in state.hardware_manager.mqtt_nodes.items()
            if info.get("config_topic") and len(info.get("maintenance_key", "")) >= 32}


def receive(topic, envelope):
    node = topics().get(topic)
    if node is None:
        return False
    body, mac = envelope.get("body"), envelope.get("mac")
    if not isinstance(body, str) or len(body) > 4096 or not isinstance(mac, str):
        return True
    expected = hmac.new(_info(node)["maintenance_key"].encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, mac):
        return True
    report = json.loads(body)
    if not isinstance(report, dict) or not isinstance(report.get("boot"), str):
        return True
    with _condition:
        entry = _nodes.setdefault(node, {"logs": deque(maxlen=300), "seq": 0})
        # A retained packet is never used for liveness (firmware publishes non-retained).
        entry["report"] = report
        entry["seen"] = time.monotonic()
        job = _jobs.get(node)
        if job and job.get("status") != "sending":
            _reconcile_result(job, report)
        if isinstance(report.get("log"), str):
            entry["seq"] += 1
            entry["logs"].append({"seq": entry["seq"], "time": time.time(),
                                  "boot": report["boot"], "text": report["log"][:512]})
        _condition.notify_all()
    return True


def status(node_id, after=0):
    _info(node_id)
    with _condition:
        entry = _nodes.get(node_id, {})
        report = entry.get("report", {})
        return {"online": time.monotonic() - entry.get("seen", float("-inf")) < 20,
                "device": {k: report[k] for k in ("boot", "board", "build", "target", "free_heap", "ota_max", "uptime", "dropped_logs", "rollback", "ota_protocol", "boot_state", "update_result") if k in report},
                "job": dict(_jobs[node_id]) if node_id in _jobs else None,
                "cursor": entry.get("seq", 0),
                "logs": [dict(line) for line in entry.get("logs", ()) if line["seq"] > after]}


def _send(node, command):
    info = _info(node)
    body = json.dumps(command, separators=(",", ":"), ensure_ascii=True)
    mac = hmac.new(info["maintenance_key"].encode(), body.encode(), hashlib.sha256).hexdigest()
    client = state.global_mqtt_client
    if client is None or not client.is_connected():
        raise RuntimeError("MQTT broker disconnected")
    result = client.publish(f"{info['config_topic']}/maintenance/set",
                            json.dumps({"body": body, "mac": mac}), qos=1, retain=False)
    if result.rc != 0:
        raise RuntimeError("MQTT publish failed")


def _exchange(node, command, expected_offset):
    # Repeated begin/chunk/end commands are idempotent on the device.
    for _ in range(4):
        _send(node, command)
        deadline = time.monotonic() + 5
        with _condition:
            while time.monotonic() < deadline:
                report = _nodes[node]["report"]
                if report.get("boot") != command["boot"]:
                    raise RuntimeError("Node rebooted during transfer")
                if report.get("session") == command["session"]:
                    if report.get("error"):
                        raise RuntimeError(report["error"])
                    if report.get("offset") == expected_offset and report.get("ack") == command["op"]:
                        return
                _condition.wait(max(0, deadline - time.monotonic()))
    raise RuntimeError("Node acknowledgement timed out; old firmware remains active until commit")


def validate_image(image, node, board):
    if not 256 <= len(image) <= MAX_FIRMWARE or image[0] != 0xE9:
        raise ValueError("Select an ESP32 application firmware.bin (256 bytes–4 MiB)")
    marker = f"DEWY_TARGET:{node}:{board}".encode() + b"\x00"
    if marker not in image:
        raise ValueError("Firmware target does not match this node/board; rebuild with DEWY_NODE")
    if b"DEWY_OTA:2\x00" not in image:
        raise ValueError("Firmware lacks delayed boot validation/rollback protocol v2; rebuild before updating")
    builds = re.findall(rb"DEWY_BUILD:([0-9a-f]{32})\x00", image)
    if len(set(builds)) != 1:
        raise ValueError("Missing or ambiguous firmware build identity")
    return builds[0].decode()


def start_update(node_id, image):
    _info(node_id)
    with _condition:
        current = status(node_id)
        if not current["online"]:
            raise RuntimeError("Node offline or maintenance firmware not installed")
        device = current["device"]
        if device.get("rollback") is not True or device.get("ota_protocol") != "DEWY_OTA:2":
            raise ValueError("Install the rollback-enabled maintenance baseline with USB before remote updates")
        if device.get("boot_state") != "valid":
            raise RuntimeError("Current firmware is still awaiting boot validation")
        build = validate_image(image, node_id, device.get("board", ""))
        if len(image) > device.get("ota_max", 0):
            raise ValueError("Firmware exceeds the node's OTA partition")
        if current["job"] and current["job"]["status"] in ACTIVE_STATUSES:
            raise RuntimeError("An update is already running for this node")
        session = secrets.token_hex(16)
        job = {"id": session, "status": "sending", "sent": 0, "size": len(image),
               "sha256": hashlib.sha256(image).hexdigest(), "build": build, "error": None,
               "error_code": None, "boot": device["boot"], "started_at": time.time()}
        _jobs[node_id] = job
        threading.Thread(target=_transfer, args=(node_id, bytes(image), dict(device), job),
                         daemon=True, name=f"ota-{node_id}").start()
        return dict(job)


def _reconcile_result(job, report):
    """Only a matching persisted device result can settle a reboot/rollback outcome."""
    result = report.get("update_result")
    if not isinstance(result, dict) or result.get("session") != job["id"] or result.get("build") != job["build"]:
        return False
    if result.get("status") == "rolled_back":
        job.update(status="failed", error_code="rolled_back", device_error=result.get("code", "boot_failed_or_interrupted"),
                   error="New firmware failed its boot trial; the previous firmware has been restored",
                   finished_at=time.time())
        return True
    if result.get("status") == "failed":
        job.update(status="failed", error_code="device_rejected", device_error=result.get("code"),
                   error="Device rejected the candidate image; inspect device_error and logs", finished_at=time.time())
        return True
    if (result.get("status") == "succeeded" and report.get("boot_state") == "valid"
            and report.get("build") == job["build"] and report.get("boot") != job["boot"]):
        job.update(status="succeeded", error=None, error_code=None, finished_at=time.time())
        return True
    return False


def _transfer(node, image, device, job):
    common = {"boot": device["boot"], "session": job["id"]}
    try:
        _exchange(node, {**common, "op": "begin", "size": len(image), "target": node,
                         "board": device["board"], "md5": hashlib.md5(image).hexdigest()}, 0)
        for offset in range(0, len(image), CHUNK_SIZE):
            chunk = image[offset:offset + CHUNK_SIZE]
            _exchange(node, {**common, "op": "chunk", "offset": offset,
                             "data": base64.b64encode(chunk).decode()}, offset + len(chunk))
            with _condition:
                job["sent"] = offset + len(chunk)
        # End ACK can be lost as the node restarts; a verified new boot is decisive.
        with _condition:
            job["status"] = "rebooting"
        _send(node, {**common, "op": "end", "build": job["build"]})
        deadline = time.monotonic() + BOOT_CONFIRM_TIMEOUT
        with _condition:
            while time.monotonic() < deadline:
                report = _nodes[node]["report"]
                if _reconcile_result(job, report):
                    return
                if report.get("boot") != device["boot"] and report.get("build") == job["build"]:
                    job["status"] = "verifying"
                    if report.get("boot_state") == "pending_verify" and report.get("health_ready") is True:
                        _send(node, {"op": "confirm", "boot": report["boot"],
                                     "session": job["id"], "build": job["build"]})
                        if _reconcile_result(job, _nodes[node]["report"]):
                            return
                if report.get("session") == job["id"] and report.get("error"):
                    raise RuntimeError(report["error"])
                # Retry commit if its MQTT delivery was lost.
                _condition.wait(3)
                if _nodes[node]["report"].get("boot") == device["boot"]:
                    _send(node, {**common, "op": "end", "build": job["build"]})
        raise TimeoutError("Boot/rollback outcome is unconfirmed; inspect current build and connectivity before retrying")
    except Exception as exc:
        with _condition:
            after_commit = job["status"] in ("rebooting", "verifying")
            job["status"] = "failed"
            job["error"] = str(exc)
            job["error_code"] = "outcome_unknown" if after_commit else "transfer_failed"
            job["finished_at"] = time.time()
        if not after_commit:
            try:
                _send(node, {**common, "op": "abort"})
            except Exception:
                pass  # The device independently aborts an idle transfer after 30 seconds.
