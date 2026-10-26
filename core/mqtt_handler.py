import json
import logging
import time

import core.state as state
from core.logfold import log_failure
from core.metric_metadata import SNAPSHOT_METADATA

logger = logging.getLogger(__name__)

def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        logger.info("✅ 已成功连接到本地 MQTT Broker")
        topics = state.hardware_manager.get_mqtt_topics()
        for t in topics:
            client.subscribe(t)
        from core.logic.maintenance import topics as maintenance_topics
        for topic in maintenance_topics():
            client.subscribe(topic)
            
        # 主动查询所有配置的 mqtt relay 状态。查询指令的字面量属于固件，
        # 由驱动按配置决定，这里不该知道它长什么样
        for acts in state.hardware_manager.actuators.values():
            for actuator in acts.values():
                if hasattr(actuator, "query"):
                    actuator.query(client)

        # 连接建立后向所有支持远程配置的 ESP32 节点推送当前设置
        try:
            from core.logic.node_config import push_all_on_connect
            push_all_on_connect()
        except Exception:
            logger.exception("推送远程节点配置异常")
    else:
        logger.error("❌ MQTT 连接失败，返回码: %s", reason_code)

def _extract_readings(node_id, payload):
    """从节点上报的 JSON 里取出测量值。

    默认收下所有数值字段——ESP32 上换个传感器、多报一个量，不该还要改这里。
    节点配置里写了 metrics 时以它为准，用来挡掉 rssi、uptime 之类的自身状态量。
    """
    declared = state.hardware_manager.mqtt_nodes.get(node_id, {}).get("metrics")
    if declared:
        return {k: payload[k] for k in declared if k in payload}

    return {k: v for k, v in payload.items()
            if k not in SNAPSHOT_METADATA and isinstance(v, (int, float)) and not isinstance(v, bool)}


def update_node_snapshot(node_id, data, received_at=None):
    """v2 packets are complete snapshots; legacy packets retain partial-update semantics."""
    readings = _extract_readings(node_id, data)
    version = data.get("data_version", 1)
    if version not in (1, 2):
        return
    info = state.mqtt_latest_data[node_id]
    if version == 2:
        # Keep main's skipped-event history working with both v2 firmware builds
        # and legacy numeric flags, even if the node's metric list predates it.
        readings["skipped"] = int(data.get("feeding_state") == "skipped")
        declared = state.hardware_manager.mqtt_nodes.get(node_id, {}).get("metrics", [])
        for key in set(info["data"]) | set(declared):
            readings.setdefault(key, None)
        readings.update({k: data.get(k) for k in SNAPSHOT_METADATA
                         if k not in {"received_at", "stale"}})
        if data.get("water_temp_valid") is not True:
            readings["water_temp"] = None
        # Replace atomically so readers cannot observe half an updated snapshot.
        info["data"] = readings
    else:
        if isinstance(data.get("skipped"), (int, float)) and data["skipped"] in (0, 1):
            readings["skipped"] = int(data["skipped"])
        previous = info["data"]
        if previous.get("data_version") == 2:
            # Firmware rollback: old packets must select the legacy UI again.
            cleared = {k: None for k in SNAPSHOT_METADATA | {"feeding_score"}}
            aggregator_data = {**cleared, **readings}
            previous = {k: v for k, v in previous.items()
                        if k not in SNAPSHOT_METADATA and k != "feeding_score"}
        else:
            aggregator_data = readings
        if "fed_time" in data:
            readings["fed_time"] = data["fed_time"]
        elif data.get("fed") == 0:
            readings["fed_time"] = None
        if data.get("fed") == 1 and readings.get("fed_time") in ("00:00", "", None):
            # Legacy firmware has no reliable action timestamp before NTP sync.
            # Preserve main's fallback using an existing archived feeding event;
            # v2 timestamps are device-owned and must never be fabricated here.
            import core.database as db
            first_time = db.query_today_first_fed_time(node_id)
            if isinstance(first_time, str) and first_time:
                readings["fed_time"] = first_time
        info["data"] = {**previous, **readings}
    info["received_at"] = time.time() if received_at is None else received_at
    info["updated"] = True
    from core.logic.sensor_aggregator import aggregator
    metadata = state.hardware_manager.mqtt_nodes.get(node_id, {}).get("metric_metadata", {})
    aggregator.record_sample(node_id, readings if version == 2 else {**aggregator_data, **readings}, metadata)


def node_snapshot(info, now=None):
    result = info["data"].copy()
    received = info.get("received_at")
    result["received_at"] = received
    result["stale"] = received is None or (time.time() if now is None else now) - received > 30
    return result


def on_mqtt_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("MQTT payload must be an object")
        topic = msg.topic
        from core.logic.maintenance import receive as maintenance_receive, topics as maintenance_topics
        if topic in maintenance_topics():
            if not getattr(msg, "retain", False):
                maintenance_receive(topic, data)
            return
        
        # 判断是否为某个继电器的反馈。回报只记到它所属节点的灯上——
        # 以前全局只有一个 light_status，aqua 插座的回报会覆盖主节点的灯；
        # 不是灯的继电器（MQTT 水泵之类）的回报也不该被当成灯的状态。
        for node_id, acts in state.hardware_manager.actuators.items():
            for act_id, actuator in acts.items():
                if getattr(actuator, "topic", None) != topic:
                    continue
                from core.logic.light import light_config, light_state
                cfg = light_config(node_id)
                if cfg is None or cfg.get("actuator_id", "light") != act_id:
                    return
                ls = light_state(node_id)
                if time.time() > ls["ignore_feedback_until"]:
                    # 回报里用什么字面量表示开/关由驱动按配置解析
                    status = actuator.parse_feedback(data.get("information", ""))
                    if status:
                        ls["status"] = status
                return
        
        # 判断是否为某个节点的配置状态回报
        if topic in state.mqtt_config_topic_to_node:
            node_id = state.mqtt_config_topic_to_node[topic]
            state.node_config_state[node_id] = {**data, "_received_at": time.time()}
            logger.info("📥 收到节点 %s 配置状态回报: %s", node_id, data)
            return

        # 更新传感器节点数据
        if topic in state.mqtt_topic_to_node:
            node_id = state.mqtt_topic_to_node[topic]
            update_node_snapshot(node_id, data)
            
    except (UnicodeDecodeError, ValueError) as e:
        # 节点发来非 JSON 报文：常见于固件升级期间，不致命但要能查。
        # 固件若持续发坏包，频率等同于其上报频率，同样需要折叠
        log_failure(logger, f"mqtt:parse:{msg.topic}",
                    "MQTT 报文解析失败 (topic=%s): %s", msg.topic, e)
    except Exception:
        logger.exception("MQTT 消息处理异常 (topic=%s)", msg.topic)
