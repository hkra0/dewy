"""执行器与相机的可配置性。

这些字面量（灯的 a1/b1、水泵叫 pump、rpicam 的分辨率）过去写死在
core/ 与 api/ 里，换一套硬件就得改代码。这里锁住"改配置即可"。
"""

import unittest
from unittest.mock import MagicMock

import core.config as config
from hardware.drivers.mqtt_relay import MQTT_Relay
from hardware.drivers.rpicam import Driver as RpicamDriver
from hardware.drivers.command_camera import Driver as CommandCamera
from core.logic import watering


class MqttRelayCommandsTest(unittest.TestCase):

    def setUp(self):
        self.client = MagicMock()

    def sent(self):
        topic, payload = self.client.publish.call_args[0][:2]
        return payload

    def test_default_commands_match_the_bundled_firmware(self):
        relay = MQTT_Relay(topic="t")
        relay.trigger(self.client, state=True)
        self.assertIn('"a1"', self.sent())
        relay.trigger(self.client, state=False)
        self.assertIn('"b1"', self.sent())

    def test_commands_are_configurable(self):
        relay = MQTT_Relay(topic="t", on_command="POWER ON", off_command="POWER OFF")
        relay.trigger(self.client, state=True)
        self.assertIn("POWER ON", self.sent())
        relay.trigger(self.client, state=False)
        self.assertIn("POWER OFF", self.sent())

    def test_command_field_is_configurable(self):
        relay = MQTT_Relay(topic="t", command_field="cmd")
        relay.trigger(self.client, state=True)
        self.assertIn('"cmd"', self.sent())

    def test_pulse_template_is_configurable(self):
        relay = MQTT_Relay(topic="t", pulse_command="pulse:{duration}s")
        relay.trigger(self.client, duration=4)
        self.assertIn("pulse:4s", self.sent())

    def test_raw_command_still_works(self):
        relay = MQTT_Relay(topic="t")
        relay.trigger(self.client, command="x9")
        self.assertIn("x9", self.sent())

    def test_state_takes_precedence_over_duration(self):
        relay = MQTT_Relay(topic="t")
        relay.trigger(self.client, state=True, duration=4)
        self.assertIn('"a1"', self.sent())

    def test_query_uses_configured_command(self):
        relay = MQTT_Relay(topic="t", query_command="STATUS")
        relay.query(self.client)
        self.assertIn("STATUS", self.sent())

    def test_trigger_without_a_client_is_a_no_op(self):
        self.assertFalse(MQTT_Relay(topic="t").trigger(None, state=True))

    def test_feedback_parsing_uses_configured_tokens(self):
        relay = MQTT_Relay(topic="t", on_feedback="ON", off_feedback="OFF")
        self.assertEqual(relay.parse_feedback("relay is ON now"), "ON")
        self.assertEqual(relay.parse_feedback("relay is OFF now"), "OFF")
        self.assertIsNone(relay.parse_feedback("rebooting"))

    def test_default_feedback_tokens(self):
        relay = MQTT_Relay(topic="t")
        self.assertEqual(relay.parse_feedback("n1"), "ON")
        self.assertEqual(relay.parse_feedback("f1"), "OFF")


class PumpActuatorIdTest(unittest.TestCase):

    def tearDown(self):
        config.global_config = {}

    def test_defaults_to_pump(self):
        config.global_config = {"auto_water": {}}
        self.assertEqual(watering._pump_actuator_id(), "pump")

    def test_is_configurable(self):
        config.global_config = {"auto_water": {"actuator_id": "pump_b"}}
        self.assertEqual(watering._pump_actuator_id(), "pump_b")


class RpicamArgsTest(unittest.TestCase):

    def test_defaults_reproduce_the_previous_hardcoded_command(self):
        args = RpicamDriver()._build_args("/tmp/x.jpg", RpicamDriver().hq)
        self.assertEqual(args[0], "rpicam-jpeg")
        for expected in ("2592", "1944", "90", "2000", "--vflip", "--hflip", "--nopreview"):
            self.assertIn(expected, args)

    def test_preview_profile_uses_the_small_size(self):
        d = RpicamDriver()
        args = d._build_args("/tmp/x.jpg", d.preview)
        self.assertIn("648", args)
        self.assertIn("486", args)

    def test_resolution_and_flips_are_configurable(self):
        d = RpicamDriver(hq_width=1280, hq_height=720, vflip=False, hflip=False)
        args = d._build_args("/tmp/x.jpg", d.hq)
        self.assertIn("1280", args)
        self.assertIn("720", args)
        self.assertNotIn("--vflip", args)
        self.assertNotIn("--hflip", args)

    def test_command_name_is_configurable(self):
        # Bullseye 及更早的系统上叫 libcamera-jpeg
        d = RpicamDriver(command="libcamera-jpeg")
        self.assertEqual(d._build_args("/tmp/x.jpg", d.hq)[0], "libcamera-jpeg")

    def test_extra_args_are_appended(self):
        d = RpicamDriver(extra_args=["--roi", "0.25,0.25,0.5,0.5"])
        self.assertEqual(d._build_args("/tmp/x.jpg", d.hq)[-2:], ["--roi", "0.25,0.25,0.5,0.5"])


class CommandCameraTest(unittest.TestCase):

    def test_command_is_required(self):
        with self.assertRaises(ValueError):
            CommandCamera()

    def test_hq_command_defaults_to_the_plain_one(self):
        cam = CommandCamera(command="grab {path}")
        self.assertEqual(cam.hq_command, "grab {path}")


if __name__ == "__main__":
    unittest.main()
