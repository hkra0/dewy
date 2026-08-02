"""core.mqtt_handler._extract_readings —— MQTT 节点上报字段的提取。

关系到「别人的 ESP32 报了别的量」时数据能不能进来。
"""

import unittest
from unittest.mock import MagicMock

import core.state as state
from core.mqtt_handler import _extract_readings

NODE = "sub1"


class ExtractReadingsTest(unittest.TestCase):

    def setUp(self):
        state.hardware_manager = MagicMock()
        state.hardware_manager.mqtt_nodes = {NODE: {}}

    def declare(self, metrics):
        state.hardware_manager.mqtt_nodes = {NODE: {"metrics": metrics}}

    def test_all_numeric_fields_are_taken_by_default(self):
        payload = {"temperature": 21.0, "humidity": 55, "illuminance": 300}
        self.assertEqual(_extract_readings(NODE, payload), payload)

    def test_non_numeric_fields_are_dropped(self):
        payload = {"temperature": 21.0, "fw": "1.2.0", "ok": True, "err": None}
        self.assertEqual(_extract_readings(NODE, payload), {"temperature": 21.0})

    def test_declared_metrics_act_as_a_whitelist(self):
        self.declare(["temperature", "humidity"])
        payload = {"temperature": 21.0, "humidity": 55, "rssi": -70}
        self.assertEqual(_extract_readings(NODE, payload), {"temperature": 21.0, "humidity": 55})

    def test_declared_metric_missing_from_payload_is_omitted(self):
        # 缺的字段不写 None，保留上一次已知值
        self.declare(["temperature", "pressure"])
        self.assertEqual(_extract_readings(NODE, {"temperature": 21.0}), {"temperature": 21.0})

    def test_unknown_node_falls_back_to_numeric_filter(self):
        self.assertEqual(_extract_readings("nope", {"temperature": 21.0}), {"temperature": 21.0})

    def test_empty_payload_yields_nothing(self):
        self.assertEqual(_extract_readings(NODE, {}), {})


if __name__ == "__main__":
    unittest.main()
