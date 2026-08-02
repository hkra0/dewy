"""hardware.manager 的驱动解析与实例化。

这里覆盖的是「换硬件」这条路：任何人把 .py 丢进 hardware/drivers/
就该能用，写错名字必须有明确报错而不是无声消失。
"""

import logging
import unittest

from hardware.manager import HardwareManager


def _manager():
    """不读配置文件、不初始化任何硬件的裸 manager。"""
    hm = HardwareManager.__new__(HardwareManager)
    hm._driver_class_cache = {}
    return hm


class ResolveDriverClassTest(unittest.TestCase):

    def setUp(self):
        self.hm = _manager()

    def test_legacy_names_still_resolve(self):
        # 老 hardware_config.toml 里的五个驱动名不能因为这次改动失效
        for name in ("SHT30", "ADS1115_Soil", "INA219_UPS", "GPIO_Relay", "MQTT_Relay"):
            with self.subTest(driver=name):
                self.assertIsNotNone(self.hm._load_driver_class(name))

    def test_previously_unreachable_drivers_now_resolve(self):
        # 这批驱动此前不在白名单里，配置了也加载不到
        for name in ("aht20_sensor", "bh1750_sensor", "bme280_sensor", "dht_sensor",
                     "ds18b20_sensor", "dummy_sensor", "http_sensor", "script_sensor"):
            with self.subTest(driver=name):
                self.assertIsNotNone(self.hm._load_driver_class(name))

    def test_bare_name_resolves_to_suffixed_module(self):
        # 配置里写 "bh1750" 也该找到 bh1750_sensor.py
        self.assertIsNotNone(self.hm._load_driver_class("bh1750"))
        self.assertIsNotNone(self.hm._load_driver_class("dummy"))

    def test_class_name_resolves_even_when_module_name_differs(self):
        cls = self.hm._load_driver_class("ADS1115_Soil")
        self.assertEqual(cls.__name__, "ADS1115_Soil")

    def test_unknown_driver_returns_none_and_logs_error(self):
        with self.assertLogs("hardware.manager", level=logging.ERROR) as cm:
            self.assertIsNone(self.hm._load_driver_class("NoSuchSensor"))
        self.assertIn("NoSuchSensor", "\n".join(cm.output))

    def test_resolution_is_cached(self):
        first = self.hm._load_driver_class("SHT30")
        self.assertIs(self.hm._load_driver_class("SHT30"), first)


class InstantiateTest(unittest.TestCase):

    def test_kwargs_style_driver(self):
        class D:
            def __init__(self, **kwargs):
                self.seen = kwargs

            def read(self):
                return {}

        obj = HardwareManager._instantiate(D, {"driver": "D", "pin": 4})
        self.assertEqual(obj.seen, {"pin": 4})

    def test_legacy_config_dict_style_driver(self):
        # 按早期 hardware/README.md 写的第三方驱动仍须能用
        class D:
            def __init__(self, config):
                self.seen = config

            def read(self):
                return {}

        obj = HardwareManager._instantiate(D, {"driver": "D", "pin": 4})
        self.assertEqual(obj.seen, {"pin": 4})

    def test_explicit_keyword_signature_driver(self):
        class D:
            def __init__(self, url, timeout=5):
                self.url, self.timeout = url, timeout

            def read(self):
                return {}

        obj = HardwareManager._instantiate(D, {"driver": "D", "url": "http://x"})
        self.assertEqual((obj.url, obj.timeout), ("http://x", 5))

    def test_driver_key_is_never_passed_through(self):
        class D:
            def __init__(self, **kwargs):
                self.seen = kwargs

        self.assertNotIn("driver", HardwareManager._instantiate(D, {"driver": "D"}).seen)


class BuildDeviceTest(unittest.TestCase):

    def setUp(self):
        self.hm = _manager()

    def test_failing_driver_init_is_isolated(self):
        # 驱动构造抛异常时只能跳过它自己：HardwareManager 在 core.state
        # 导入期构造，放任异常上抛会导致整个服务起不来
        class Boom:
            def __init__(self, **kwargs):
                raise RuntimeError("i2c 不通")

        self.hm._driver_class_cache["Boom"] = Boom
        with self.assertLogs("hardware.manager", level=logging.ERROR):
            self.assertIsNone(self.hm._build_device("main", "传感器", "s1", {"driver": "Boom"}))

    def test_missing_driver_key_is_reported(self):
        with self.assertLogs("hardware.manager", level=logging.ERROR) as cm:
            self.assertIsNone(self.hm._build_device("main", "传感器", "s1", {"bus": 1}))
        self.assertIn("未指定 driver", "\n".join(cm.output))


class CameraTest(unittest.TestCase):

    def setUp(self):
        self.hm = _manager()
        self.hm.cameras = {}
        self.hm._legacy_camera_nodes = set()
        self.hm._default_camera = None

    def test_configured_camera_is_reported_and_returned(self):
        self.hm.cameras = {"main": object()}
        self.assertTrue(self.hm.has_camera("main"))
        self.assertIs(self.hm.get_camera("main"), self.hm.cameras["main"])

    def test_node_without_camera_reports_false(self):
        self.assertFalse(self.hm.has_camera("main"))
        self.assertIsNone(self.hm.get_camera("main"))

    def test_legacy_camera_sensor_marks_the_node(self):
        # 老配置用 [nodes.main.sensors.camera] 表示"这个节点有相机"
        self.hm._legacy_camera_nodes = {"main"}
        self.assertTrue(self.hm.has_camera("main"))

    def test_get_camera_without_node_falls_back_to_rpicam(self):
        # 配置里没有 camera 段的老部署仍要能拍照
        self.assertEqual(type(self.hm.get_camera()).__module__, "hardware.drivers.rpicam")

    def test_default_camera_is_built_once(self):
        self.assertIs(self.hm.get_camera(), self.hm.get_camera())

    def test_configured_camera_wins_over_the_default(self):
        sentinel = object()
        self.hm.cameras = {"main": sentinel}
        self.assertIs(self.hm.get_camera(), sentinel)


class LegacyCameraSensorTest(unittest.TestCase):
    """名为 camera 的传感器条目是标记，不能真的实例化成传感器。

    它以前解析不到驱动、被静默跳过；现在 dummy 之类能解析了，
    若真建出来就会往节点数据里灌假读数。
    """

    def build(self, sensors):
        hm = _manager()
        hm.nodes = {"main": {"type": "local", "sensors": sensors}}
        hm.local_sensors, hm.actuators, hm.cameras, hm.mqtt_nodes = {}, {}, {}, {}
        hm._legacy_camera_nodes = set()
        hm._init_hardware()
        return hm

    def test_camera_sensor_is_not_instantiated(self):
        hm = self.build({"camera": {"driver": "dummy"}})
        self.assertEqual(hm.local_sensors["main"], {})
        self.assertTrue(hm.has_camera("main"))

    def test_other_sensors_are_unaffected(self):
        hm = self.build({"camera": {"driver": "dummy"}, "fake": {"driver": "dummy_sensor"}})
        self.assertEqual(list(hm.local_sensors["main"]), ["fake"])


class TriggerActuatorTest(unittest.TestCase):

    def setUp(self):
        self.hm = _manager()

    def test_prefers_trigger(self):
        class A:
            def trigger(self, duration=None):
                return "triggered"

        self.hm.actuators = {"main": {"pump": A()}}
        self.assertEqual(self.hm.trigger_actuator("main", "pump", duration=1), "triggered")

    def test_falls_back_to_legacy_set(self):
        class A:
            def set(self, state, duration=None):
                return ("set", state, duration)

        self.hm.actuators = {"main": {"pump": A()}}
        self.assertEqual(self.hm.trigger_actuator("main", "pump", duration=1), ("set", True, 1))

    def test_unknown_actuator_returns_false(self):
        self.hm.actuators = {"main": {}}
        self.assertFalse(self.hm.trigger_actuator("main", "pump"))


if __name__ == "__main__":
    unittest.main()
