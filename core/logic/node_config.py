"""远程节点设置推送。

后端只负责存储 + 转发，不解释设置的业务含义。
推送时机：MQTT 连接/重连时、config 保存且 node_settings 变更时。
"""

import json
import logging
import core.state as state
import core.config as config

logger = logging.getLogger(__name__)


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
            client.publish(topic, json.dumps(settings), retain=True)
            logger.info("📤 已推送设置到 %s: %s", topic, settings)
        except Exception:
            logger.exception("推送节点设置失败 (node=%s)", nid)


def push_all_on_connect():
    """MQTT 连接/重连时推送所有节点设置。"""
    push_node_settings()
