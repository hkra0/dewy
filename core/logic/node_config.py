"""远程节点设置推送。

后端只负责存储 + 转发，不解释设置的业务含义。
推送时机：MQTT 连接/重连时、config 保存且 node_settings 变更时。
"""

import json
import logging
import math
import time
import core.state as state
import core.config as config

logger = logging.getLogger(__name__)
_pending = {}


def validate_node_settings(settings):
    """Only schema types/ranges here; cross-field policy belongs to the device."""
    if not isinstance(settings, dict):
        raise ValueError("node_settings must be an object")
    for nid, values in settings.items():
        if not isinstance(values, dict):
            raise ValueError(f"{nid}: expected object")
        schema = state.hardware_manager.mqtt_nodes.get(nid, {}).get("settings_schema", {})
        for key, value in values.items():
            meta = schema.get(key)
            if not meta:  # Preserve legacy fields not represented by the current UI.
                continue
            typ = meta.get("type", "text")
            valid = True
            if typ == "number":
                valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                         and math.isfinite(value)
                         and value >= meta.get("min", -math.inf)
                         and value <= meta.get("max", math.inf))
                if valid and meta.get("step"):
                    units = (value - meta.get("min", 0)) / meta["step"]
                    valid = abs(units - round(units)) < 1e-7
            elif typ == "boolean":
                valid = isinstance(value, bool)
            elif typ == "select":
                valid = isinstance(value, str) and value in meta.get("options", [])
            else:
                valid = isinstance(value, str)
            if not valid:
                raise ValueError(f"{nid}.{key}: invalid {typ}")


def config_status():
    statuses = {}
    desired = config.global_config.get("node_settings", {})
    for nid in state.hardware_manager.mqtt_nodes:
        actual = state.node_config_state.get(nid, {})
        pending = _pending.get(nid, 0)
        fresh = actual.get("_received_at", 0) >= pending
        error = actual.get("config_error") if fresh else None
        matches = bool(actual) and all(actual.get(k) == v for k, v in desired.get(nid, {}).items()
                                       if k != "feed_reset_hour")
        statuses[nid] = {"status": "rejected" if error else "applied" if fresh and matches else "pending",
                         "error": error, "actual": {k: v for k, v in actual.items() if not k.startswith("_")}}
    return statuses


def push_node_settings(node_id=None):
    """向指定节点（或所有有 config_topic 的节点）推送当前设置。"""
    client = state.global_mqtt_client
    if not client:
        return

    ns = config.global_config.get("node_settings", {})
    targets = [node_id] if node_id else list(state.hardware_manager.mqtt_nodes)

    for nid in targets:
        node_info = state.hardware_manager.mqtt_nodes.get(nid, {})
        config_topic = node_info.get("config_topic")
        if not config_topic:
            continue
        settings = ns.get(nid, {})
        if not settings:
            continue
        topic = f"{config_topic}/set"
        try:
            _pending[nid] = time.time()
            client.publish(topic, json.dumps(settings), retain=True)
            logger.info("📤 已推送设置到 %s: %s", topic, settings)
        except Exception:
            logger.exception("推送节点设置失败 (node=%s)", nid)


def push_all_on_connect():
    """MQTT 连接/重连时推送所有节点设置。"""
    push_node_settings()
