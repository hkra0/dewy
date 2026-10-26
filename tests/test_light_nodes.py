"""补光灯按节点分开：配置迁移、回报路由、定时灯控的节点隔离。

aqua 的灯是一个独立 MQTT 插座，逻辑上属于 aqua 节点。以前全局只有一盏灯，
这里钉住"两盏灯各管各的"——任何一处退回全局单例，就会出现 aqua 插座的
回报改写主节点灯状态、或一个节点的手动覆盖挡住另一个节点的定时之类的串扰。
"""

import importlib.util
import json
import pathlib
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import core.config as config   # 桩
import core.state as state     # 桩
from core.logic import light
from core import mqtt_handler

_spec = importlib.util.spec_from_file_location(
    "tests._real_core_config_lights",
    pathlib.Path(__file__).resolve().parent.parent / "core" / "config.py",
)
real_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(real_config)


def fresh_state():
    return {"status": "--", "manual_override": False,
            "manual_override_until": None, "ignore_feedback_until": 0}


class MergeLightDefaultsTest(unittest.TestCase):
    """core.config.merge_defaults 对 auto_light 段的整理。"""

    def setUp(self):
        hm = MagicMock()
        hm.mqtt_nodes = {}
        hm.actuators = {"main": {"pump": object(), "light": object()},
                        "aqua": {"light": object()}}
        state.hardware_manager = hm

    def test_legacy_flat_config_moves_under_its_node(self):
        # 升级前的扁平结构：用户调好的时段必须原样留在 main 名下
        cfg = real_config.merge_defaults({"auto_light": {
            "enabled": False, "mode": "fixed", "on_time": "06:00", "off_time": "20:00",
            "node_id": "main", "actuator_id": "light"}})
        main = cfg["auto_light"]["main"]
        self.assertFalse(main["enabled"])
        self.assertEqual((main["on_time"], main["off_time"]), ("06:00", "20:00"))
        self.assertNotIn("node_id", main)
        self.assertNotIn("enabled", cfg["auto_light"])

    def test_nodes_with_a_light_get_a_default_section(self):
        cfg = real_config.merge_defaults({})
        self.assertEqual(set(cfg["auto_light"]), {"main", "aqua"})
        self.assertEqual(cfg["auto_light"]["aqua"]["actuator_id"], "light")
        self.assertTrue(cfg["auto_light"]["aqua"]["enabled"])

    def test_missing_fields_are_filled_per_node(self):
        cfg = real_config.merge_defaults({"auto_light": {"aqua": {"on_time": "09:00"}}})
        self.assertEqual(cfg["auto_light"]["aqua"]["on_time"], "09:00")
        self.assertEqual(cfg["auto_light"]["aqua"]["off_time"], "21:30")

    def test_old_frontend_posting_flat_fields_onto_the_node_map(self):
        # 新 Pi + 旧前端：扁平字段铺在节点表上一起提交，不能把 aqua 套进 main 名下
        cfg = real_config.merge_defaults({"auto_light": {
            "main": {"on_time": "07:00"}, "aqua": {"on_time": "10:00"},
            "node_id": "main", "on_time": "06:30"}})
        self.assertEqual(cfg["auto_light"]["main"]["on_time"], "06:30")
        self.assertEqual(cfg["auto_light"]["aqua"]["on_time"], "10:00")
        self.assertEqual(set(cfg["auto_light"]), {"main", "aqua"})

    def test_config_round_trips_through_json(self):
        cfg = real_config.merge_defaults({})
        self.assertEqual(real_config.merge_defaults(json.loads(json.dumps(cfg))), cfg)


class LightFeedbackRoutingTest(unittest.TestCase):
    """core.mqtt_handler.on_mqtt_message —— 继电器回报只记到所属节点的灯上。"""

    def setUp(self):
        self.main_light, self.aqua_light, self.pump = MagicMock(), MagicMock(), MagicMock()
        self.main_light.topic, self.aqua_light.topic, self.pump.topic = "main_t", "aqua_t", "pump_t"
        for relay in (self.main_light, self.aqua_light, self.pump):
            relay.parse_feedback.side_effect = lambda info: "ON" if "n1" in info else None
        hm = MagicMock()
        hm.actuators = {"main": {"light": self.main_light, "pump": self.pump},
                        "aqua": {"light": self.aqua_light}}
        state.hardware_manager = hm
        state.lights = {"main": fresh_state(), "aqua": fresh_state()}
        config.global_config = {"auto_light": {"main": {"actuator_id": "light"},
                                               "aqua": {"actuator_id": "light"}}}
        patcher = patch("core.logic.maintenance.topics", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        config.global_config = {}

    def send(self, topic, info="n1"):
        msg = MagicMock(topic=topic, payload=json.dumps({"information": info}).encode())
        mqtt_handler.on_mqtt_message(None, None, msg)

    def test_aqua_plug_feedback_updates_only_aqua(self):
        self.send("aqua_t")
        self.assertEqual(state.lights["aqua"]["status"], "ON")
        self.assertEqual(state.lights["main"]["status"], "--")

    def test_non_light_relay_feedback_is_not_a_light_state(self):
        self.send("pump_t")
        self.assertEqual(state.lights["main"]["status"], "--")
        self.pump.parse_feedback.assert_not_called()

    def test_ignore_window_is_per_node(self):
        # 主节点拍照补光期间，aqua 插座的回报照常生效
        state.lights["main"]["ignore_feedback_until"] = float("inf")
        self.send("main_t")
        self.send("aqua_t")
        self.assertEqual(state.lights["main"]["status"], "--")
        self.assertEqual(state.lights["aqua"]["status"], "ON")


class ApplyLightScheduleTest(unittest.TestCase):
    """core.logic.light.apply_light_schedule —— 每个节点各跑各的定时。"""

    def setUp(self):
        hm = MagicMock()
        hm.actuators = {"main": {"light": object()}, "aqua": {"light": object()}}
        state.hardware_manager = hm
        state.global_mqtt_client = MagicMock()
        state.lights = {}
        config.global_config = {"auto_light": {
            "main": {"enabled": True, "mode": "fixed", "on_time": "07:00", "off_time": "21:00", "actuator_id": "light"},
            "aqua": {"enabled": True, "mode": "fixed", "on_time": "10:00", "off_time": "18:00", "actuator_id": "light"},
        }}
        self.hm = hm

    def tearDown(self):
        config.global_config = {}

    def commands(self):
        return {c.args[0]: c.kwargs["state"] for c in self.hm.trigger_actuator.call_args_list}

    def test_each_node_follows_its_own_schedule(self):
        light.apply_light_schedule(datetime(2026, 10, 26, 8, 0))
        self.assertEqual(self.commands(), {"main": True, "aqua": False})
        self.assertEqual(state.lights["aqua"]["status"], "OFF")

    def test_manual_override_on_one_node_leaves_the_other_alone(self):
        light.light_state("aqua").update(status="ON", manual_override=True,
                                         manual_override_until=datetime(2026, 10, 27, 10, 0))
        light.apply_light_schedule(datetime(2026, 10, 26, 22, 0))
        self.assertEqual(self.commands(), {"main": False, "aqua": True})

    def test_disabled_node_is_skipped(self):
        config.global_config["auto_light"]["aqua"]["enabled"] = False
        light.apply_light_schedule(datetime(2026, 10, 26, 12, 0))
        self.assertEqual(self.commands(), {"main": True})

    def test_light_without_a_loaded_actuator_is_skipped(self):
        # 配置里有段落但驱动没加载成功（或 actuator_id 写错）：不发指令
        del self.hm.actuators["aqua"]
        light.apply_light_schedule(datetime(2026, 10, 26, 12, 0))
        self.assertEqual(self.commands(), {"main": True})

    def test_one_failing_node_does_not_stop_the_others(self):
        def trigger(node_id, *_, **__):
            if node_id == "main":
                raise RuntimeError("relay gone")
            return True
        self.hm.trigger_actuator.side_effect = trigger
        light.apply_light_schedule(datetime(2026, 10, 26, 12, 0))
        self.assertEqual(state.lights["aqua"]["status"], "ON")


if __name__ == "__main__":
    unittest.main()
