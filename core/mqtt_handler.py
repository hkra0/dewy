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
            
        # 主动查询所有配置的 mqtt relay 状态
        for n_id, acts in state.hardware_manager.actuators.items():
            for a_id, actuator in acts.items():
                if hasattr(actuator, "topic"):
                    client.publish(actuator.topic, json.dumps({"command": "q1"}))
    else:
        logger.error("❌ MQTT 连接失败，返回码: %s", reason_code)

def on_mqtt_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        topic = msg.topic
        
        # 判断是否为某个继电器的反馈
        for acts in state.hardware_manager.actuators.values():
            for actuator in acts.values():
                if hasattr(actuator, "topic") and actuator.topic == topic:
                    info = data.get("information", "")
                    if time.time() > state.ignore_light_feedback_until:
                        if "n1" in info:
                            state.light_status = "ON"
                        elif "f1" in info:
                            state.light_status = "OFF"
                    return
        
        # 更新传感器节点数据
        if topic in state.mqtt_topic_to_node:
            node_id = state.mqtt_topic_to_node[topic]
            state.mqtt_latest_data[node_id]["data"]["temperature"] = data.get("temperature")
            state.mqtt_latest_data[node_id]["data"]["humidity"] = data.get("humidity")
            state.mqtt_latest_data[node_id]["data"]["pressure"] = data.get("pressure")
            state.mqtt_latest_data[node_id]["updated"] = True
            
    except (UnicodeDecodeError, ValueError) as e:
        # 节点发来非 JSON 报文：常见于固件升级期间，不致命但要能查。
        # 固件若持续发坏包，频率等同于其上报频率，同样需要折叠
        log_failure(logger, f"mqtt:parse:{msg.topic}",
                    "MQTT 报文解析失败 (topic=%s): %s", msg.topic, e)
    except Exception:
        logger.exception("MQTT 消息处理异常 (topic=%s)", msg.topic)
