import json
import logging
import time

import core.state as state
from core.logfold import log_failure

logger = logging.getLogger(__name__)

def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        logger.info("✅ 已成功连接到本地 MQTT Broker")
        topics = state.hardware_manager.get_mqtt_topics()
        for t in topics:
            client.subscribe(t)
            
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
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def on_mqtt_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        topic = msg.topic
        
        # 判断是否为某个继电器的反馈
        for acts in state.hardware_manager.actuators.values():
            for actuator in acts.values():
                if getattr(actuator, "topic", None) != topic:
                    continue
                if time.time() > state.ignore_light_feedback_until:
                    # 回报里用什么字面量表示开/关由驱动按配置解析
                    status = actuator.parse_feedback(data.get("information", ""))
                    if status:
                        state.light_status = status
                return
        
        # 判断是否为某个节点的配置状态回报
        if topic in state.mqtt_config_topic_to_node:
            node_id = state.mqtt_config_topic_to_node[topic]
            state.node_config_state[node_id] = data
            logger.info("📥 收到节点 %s 配置状态回报: %s", node_id, data)
            return

        # 更新传感器节点数据
        if topic in state.mqtt_topic_to_node:
            node_id = state.mqtt_topic_to_node[topic]
            readings = _extract_readings(node_id, data)
            if readings:
                # 若节点处于已喂食状态但 fed_time 为 "00:00" 或空（例如触摸时 NTP 尚未就绪），
                # 尝试从今日首次喂食记录对齐，确保看板显示真实的喂食时刻
                if readings.get("fed") == 1 and readings.get("fed_time") in ("00:00", "", None):
                    import core.database as db
                    first_time = db.query_today_first_fed_time(node_id)
                    if first_time:
                        readings["fed_time"] = first_time

                state.mqtt_latest_data[node_id]["data"].update(readings)
                state.mqtt_latest_data[node_id]["updated"] = True
                try:
                    from core.logic.sensor_aggregator import aggregator
                    aggregator.record_sample(node_id, readings)
                except Exception as e:
                    logger.debug("聚合采样记录失败 (node=%s): %s", node_id, e)
            
    except (UnicodeDecodeError, ValueError) as e:
        # 节点发来非 JSON 报文：常见于固件升级期间，不致命但要能查。
        # 固件若持续发坏包，频率等同于其上报频率，同样需要折叠
        log_failure(logger, f"mqtt:parse:{msg.topic}",
                    "MQTT 报文解析失败 (topic=%s): %s", msg.topic, e)
    except Exception:
        logger.exception("MQTT 消息处理异常 (topic=%s)", msg.topic)
