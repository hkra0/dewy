"""通过 MQTT 控制的继电器（补光灯等）。

指令与状态回报的字面量随固件而异，全部从 hardware_config 读取，
默认值是本项目 ESP32 固件使用的那一套。换一个别人的继电器固件，
改配置即可，不必动 core/ 里的灯控逻辑。
"""

import json


class MQTT_Relay:
    def __init__(self, **kwargs):
        self.topic = kwargs.get("topic")

        # 下发指令
        self.on_command = kwargs.get("on_command", "a1")
        self.off_command = kwargs.get("off_command", "b1")
        self.query_command = kwargs.get("query_command", "q1")
        # 定时通电的指令模板，{duration} 会被替换成秒数
        self.pulse_command = kwargs.get("pulse_command", "c1={duration}")

        # 状态回报：固件在 information 字段里带这些子串表示当前开/关
        self.on_feedback = kwargs.get("on_feedback", "n1")
        self.off_feedback = kwargs.get("off_feedback", "f1")

        # 报文格式：默认 {"command": "<cmd>"}
        self.command_field = kwargs.get("command_field", "command")

    def _publish(self, mqtt_client, cmd, retain=False):
        try:
            mqtt_client.publish(self.topic, json.dumps({self.command_field: cmd}), retain=retain)
            return True
        except Exception:
            return False

    def trigger(self, mqtt_client, state=None, command=None, duration=None, retain=False):
        """驱动继电器。

        三种用法，优先级从高到低：
        - state=True/False —— 语义化开关，映射到配置里的 on/off_command
        - duration=秒数    —— 定时通电（拍照补光、点动水泵）
        - command="..."    —— 直接下发原始指令
        """
        if not mqtt_client:
            return False

        if state is not None:
            return self._publish(mqtt_client, self.on_command if state else self.off_command, retain)
        if duration is not None:
            return self._publish(mqtt_client, self.pulse_command.format(duration=duration))
        if command is not None:
            return self._publish(mqtt_client, command, retain)
        return False

    def query(self, mqtt_client):
        """请固件回报一次当前状态。"""
        return self._publish(mqtt_client, self.query_command)

    def parse_feedback(self, information):
        """把固件回报解析成 "ON"/"OFF"，认不出返回 None。"""
        if self.on_feedback and self.on_feedback in information:
            return "ON"
        if self.off_feedback and self.off_feedback in information:
            return "OFF"
        return None
