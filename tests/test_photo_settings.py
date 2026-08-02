"""拍照相关设置：补光开关、配置段合并、重拍的覆盖语义。

这三件事都只在真机上才看得出问题（灯没亮、配置段被吃掉、照片没被覆盖），
所以用本包 __init__ 装好的桩把它们钉在单元测试里。
"""

import importlib.util
import pathlib
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import core.config as config   # 桩
import core.state as state     # 桩
from core.logic import light, photo

# merge_defaults 测的正是 core/config.py 本身，桩上没有实现。绕开 sys.modules
# 单独加载一份真实模块——它只在 load/save 时用到 core.state.CONFIG_FILE，
# 而这里只调用纯函数 merge_defaults，不碰磁盘。
_spec = importlib.util.spec_from_file_location(
    "tests._real_core_config",
    pathlib.Path(__file__).resolve().parent.parent / "core" / "config.py",
)
real_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(real_config)


def photo_config(camera=None, **overrides):
    """一份可用的配置，字段与 DEFAULT_CONFIG 对齐。"""
    cfg = {
        "auto_light": {"node_id": "main", "actuator_id": "light"},
        "camera": {"fill_light": True},
        "daily_photo": {"enabled": True, "hour": 12, "disk_limit_free_gb": 20},
    }
    cfg["daily_photo"].update(overrides)
    if camera:
        cfg["camera"].update(camera)
    return cfg


class FillLightForCaptureTest(unittest.TestCase):
    """core.logic.light.fill_light_for_capture —— 拍照前的临时补光。"""

    def setUp(self):
        config.global_config = photo_config()

        self.hm = MagicMock()
        state.hardware_manager = self.hm
        state.global_mqtt_client = MagicMock()
        state.light_status = "OFF"

        # 真的 sleep 0.6 秒只会拖慢测试，补光时序不是这里要验证的东西
        patcher = patch.object(light.time, "sleep")
        self.addCleanup(patcher.stop)
        patcher.start()

    def tearDown(self):
        config.global_config = {}

    def test_lights_up_by_default(self):
        self.assertTrue(light.fill_light_for_capture(4))
        self.hm.trigger_actuator.assert_called_once()
        self.assertEqual(self.hm.trigger_actuator.call_args.kwargs["duration"], 4)

    def test_setting_off_skips_the_light(self):
        config.global_config = photo_config(camera={"fill_light": False})
        self.assertFalse(light.fill_light_for_capture(4))
        self.hm.trigger_actuator.assert_not_called()

    def test_missing_key_defaults_to_on(self):
        # 老配置文件里没有 fill_light 字段，行为必须与升级前一致
        del config.global_config["camera"]["fill_light"]
        self.assertTrue(light.fill_light_for_capture(4))

    def test_missing_camera_section_defaults_to_on(self):
        # 整个 camera 段都没有的老配置（合并前就被读到）同样要能拍
        del config.global_config["camera"]
        self.assertTrue(light.fill_light_for_capture(4))

    def test_already_on_light_is_left_alone(self):
        # 灯本来就亮着，再发一个"亮 4 秒"的脉冲反而会在 4 秒后把它关掉
        state.light_status = "ON"
        self.assertFalse(light.fill_light_for_capture(4))
        self.hm.trigger_actuator.assert_not_called()

    def test_no_mqtt_client_skips_the_light(self):
        state.global_mqtt_client = None
        self.assertFalse(light.fill_light_for_capture(4))
        self.hm.trigger_actuator.assert_not_called()

    def test_feedback_is_ignored_for_the_whole_pulse(self):
        # 灯会自己灭，期间 ESP32 回报的 ON 不是用户的意图
        with patch.object(light.time, "time", return_value=1000.0):
            light.fill_light_for_capture(4)
        self.assertGreaterEqual(state.ignore_light_feedback_until, 1004.0)

    def test_hardware_failure_does_not_raise(self):
        # 补光失败只是照片偏暗，不该让拍照整个失败
        self.hm.trigger_actuator.side_effect = RuntimeError("mqtt down")
        self.assertFalse(light.fill_light_for_capture(4))

    def test_uses_the_configured_light_actuator(self):
        config.global_config["auto_light"] = {"node_id": "sub1", "actuator_id": "grow_lamp"}
        light.fill_light_for_capture(2)
        self.assertEqual(self.hm.trigger_actuator.call_args.args[:2], ("sub1", "grow_lamp"))


class MergeDefaultsTest(unittest.TestCase):
    """core.config.merge_defaults —— 前端只提交它渲染的那几段。"""

    def test_missing_section_is_restored(self):
        # 这是真实的失败路径：设置页不提交 daily_photo 时，后台循环下一轮
        # 读 config["daily_photo"] 会 KeyError，而且要重启才恢复
        cfg = real_config.merge_defaults({"auto_water": {"enabled": False}})
        self.assertIn("daily_photo", cfg)
        self.assertTrue(cfg["daily_photo"]["enabled"])

    def test_missing_subkey_is_restored(self):
        cfg = real_config.merge_defaults({"daily_photo": {"enabled": False}})
        self.assertEqual(cfg["daily_photo"]["disk_limit_free_gb"], 20)

    def test_camera_section_is_restored(self):
        cfg = real_config.merge_defaults({"daily_photo": {"enabled": False}})
        self.assertTrue(cfg["camera"]["fill_light"])

    def test_provided_values_win(self):
        cfg = real_config.merge_defaults({"daily_photo": {"hour": 6}, "camera": {"fill_light": False}})
        self.assertEqual(cfg["daily_photo"]["hour"], 6)
        self.assertFalse(cfg["camera"]["fill_light"])

    def test_restored_section_does_not_alias_the_defaults(self):
        # 浅拷贝的话，改一次配置就把 DEFAULT_CONFIG 本身改了
        cfg = real_config.merge_defaults({})
        cfg["daily_photo"]["hour"] = 3
        self.assertEqual(real_config.DEFAULT_CONFIG["daily_photo"]["hour"], 12)

    def test_unknown_keys_are_preserved(self):
        cfg = real_config.merge_defaults({"custom": {"x": 1}})
        self.assertEqual(cfg["custom"], {"x": 1})

    def test_fill_light_defaults_to_on(self):
        self.assertTrue(real_config.DEFAULT_CONFIG["camera"]["fill_light"])

    def test_fill_light_is_not_scoped_to_the_daily_photo(self):
        # 补光对实时预览与高清抓拍同样生效，放回 daily_photo 段就名不副实了
        self.assertNotIn("fill_light", real_config.DEFAULT_CONFIG["daily_photo"])


class DailyPhotoCaptureTest(unittest.TestCase):
    """core.logic.photo.daily_photo_capture —— force 的跳过与覆盖语义。"""

    def setUp(self):
        config.global_config = photo_config(hour=12)
        state.hardware_manager = MagicMock()

        self.db = patch.object(photo, "db").start()
        patch.object(photo, "fill_light_for_capture").start()
        patch.object(photo, "cleanup_old_photos").start()
        self.os = patch.object(photo, "os").start()
        self.addCleanup(patch.stopall)
        self.os.path.join.side_effect = lambda *a: "/".join(a)
        self.os.path.exists.return_value = True
        self.os.path.getsize.return_value = 4096

    def tearDown(self):
        config.global_config = {}

    def capture(self, hour, force=False):
        with patch.object(photo, "datetime") as dt:
            dt.now.return_value = datetime(2026, 8, 2, hour, 0)
            return photo.daily_photo_capture(force=force)

    def test_before_the_configured_hour_nothing_happens(self):
        self.db.photo_exists.return_value = False
        self.assertFalse(self.capture(hour=9))
        state.hardware_manager.get_camera.assert_not_called()

    def test_existing_photo_is_not_retaken_by_the_scheduler(self):
        self.db.photo_exists.return_value = True
        self.assertFalse(self.capture(hour=13))
        state.hardware_manager.get_camera.assert_not_called()

    def test_force_ignores_the_configured_hour(self):
        self.db.photo_exists.return_value = False
        self.assertTrue(self.capture(hour=3, force=True))
        state.hardware_manager.get_camera.assert_called_once()

    def test_force_overwrites_an_existing_photo(self):
        self.db.photo_exists.return_value = True
        self.assertTrue(self.capture(hour=13, force=True))
        # upsert 而非 insert：insert 撞 UNIQUE 会被 DAL 静默吞掉，
        # 文件换了、记录里的体积和时间戳还是旧的，前端缩略图缓存不失效
        self.db.upsert_photo.assert_called_once()
        self.db.insert_photo.assert_not_called()

    def test_scheduled_capture_still_uses_plain_insert(self):
        self.db.photo_exists.return_value = False
        self.assertTrue(self.capture(hour=13))
        self.db.insert_photo.assert_called_once()
        self.db.upsert_photo.assert_not_called()

    def test_missing_camera_reports_failure(self):
        self.db.photo_exists.return_value = False
        state.hardware_manager.get_camera.return_value = None
        self.assertFalse(self.capture(hour=13, force=True))

    def test_camera_exception_reports_failure(self):
        self.db.photo_exists.return_value = False
        state.hardware_manager.get_camera.return_value.capture.side_effect = RuntimeError("boom")
        self.assertFalse(self.capture(hour=13, force=True))


if __name__ == "__main__":
    unittest.main()
