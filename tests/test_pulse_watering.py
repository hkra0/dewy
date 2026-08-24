"""脉冲式浇水逻辑的单元测试。

覆盖：
- pulse_watering：正常达标退出、达到最大脉冲数、泵启动失败、读不到湿度
- check_auto_watering：省电模式跳过、时刻限制、间隔限制、正常触发
- trigger_watering：手动浇水兼容性（pulse_count 默认值）
- config.merge_defaults：老配置文件缺少新字段时自动补全
"""

import copy
import unittest
from unittest.mock import MagicMock, patch, call

import tests  # noqa: F401 — 加载桩
import core.state as state
import core.config as config
import core.database as db


# ---- pulse_watering 测试 ----

class TestPulseWatering(unittest.TestCase):
    """pulse_watering() 的各种场景。"""

    def setUp(self):
        """设置默认配置和 mock。"""
        config.global_config = {
            "auto_water": {
                "enabled": True,
                "duration": 0.5,
                "threshold": 65.0,
                "target_moisture": 85.0,
                "pulse_interval": 0,   # 测试时不实际等待
                "max_pulses": 10,
                "min_interval_hours": 12,
                "start_hour": 6,
                "end_hour": 20,
                "node_id": "main",
                "actuator_id": "pump",
            },
        }
        state.hardware_manager = MagicMock()
        state.local_latest_data = {}
        state.power_save_mode = False
        db.insert_watering = MagicMock()
        db.query_watering_safety = MagicMock(return_value={})
        db.query_latest_soil = MagicMock(return_value=50.0)

    @patch("time.sleep")
    def test_reaches_target_and_stops(self, mock_sleep):
        """湿度在第 3 次脉冲后达标 → 总共 3 脉冲。"""
        # 泵每次都成功
        state.hardware_manager.trigger_actuator.return_value = True
        # 模拟湿度逐步上升：50 → 70 → 88（达标）
        state.hardware_manager.read_local_node.side_effect = [
            {"soil_moisture": 50.0},
            {"soil_moisture": 70.0},
            {"soil_moisture": 88.0},
        ]

        from core.logic.watering import pulse_watering
        pulse_watering("main", 40.0)

        # 泵应该启动了 3 次
        self.assertEqual(state.hardware_manager.trigger_actuator.call_count, 3)
        # 日志记录 pulse_count=3, soil_after=88.0
        db.insert_watering.assert_called_once()
        args = db.insert_watering.call_args
        self.assertEqual(args[0][0], "main")     # node_id
        self.assertAlmostEqual(args[0][1], 1.5)  # total_duration = 3 * 0.5
        self.assertAlmostEqual(args[0][2], 40.0)  # soil_before
        self.assertEqual(args[1]["pulse_count"], 3)
        self.assertAlmostEqual(args[1]["soil_after"], 88.0)

    @patch("time.sleep")
    def test_max_pulses_exhausted(self, mock_sleep):
        """湿度始终不达标 → 用完最大脉冲数。"""
        config.global_config["auto_water"]["max_pulses"] = 3
        state.hardware_manager.trigger_actuator.return_value = True
        # 每次都返回低湿度
        state.hardware_manager.read_local_node.return_value = {"soil_moisture": 45.0}

        from core.logic.watering import pulse_watering
        pulse_watering("main", 30.0)

        self.assertEqual(state.hardware_manager.trigger_actuator.call_count, 3)
        db.insert_watering.assert_called_once()
        self.assertEqual(db.insert_watering.call_args[1]["pulse_count"], 3)

    @patch("time.sleep")
    def test_pump_failure_aborts(self, mock_sleep):
        """泵启动失败 → 立即终止。"""
        state.hardware_manager.trigger_actuator.return_value = False

        from core.logic.watering import pulse_watering
        pulse_watering("main", 30.0)

        # 只尝试了一次
        self.assertEqual(state.hardware_manager.trigger_actuator.call_count, 1)
        # 仍记录日志：0 脉冲成功（泵失败了不算 pulse_count）
        db.insert_watering.assert_called_once()
        self.assertEqual(db.insert_watering.call_args[1]["pulse_count"], 0)

    @patch("time.sleep")
    def test_sensor_read_failure_stops_fail_closed(self, mock_sleep):
        """闭环反馈丢失 → 立即停止，不能盲打剩余脉冲。"""
        config.global_config["auto_water"]["max_pulses"] = 2
        state.hardware_manager.trigger_actuator.return_value = True
        # 第一次读不到，第二次达标
        state.hardware_manager.read_local_node.side_effect = [
            {},  # 无 soil_moisture 键
            {"soil_moisture": 90.0},
        ]

        from core.logic.watering import pulse_watering
        pulse_watering("main", 30.0)

        self.assertEqual(state.hardware_manager.trigger_actuator.call_count, 1)
        self.assertIsNone(db.insert_watering.call_args[1]["soil_after"])


# ---- check_auto_watering 测试 ----

class TestCheckAutoWatering(unittest.TestCase):
    """check_auto_watering() 的各种条件判断。"""

    def setUp(self):
        config.global_config = {
            "auto_water": {
                "enabled": True,
                "duration": 0.5,
                "threshold": 65.0,
                "target_moisture": 85.0,
                "pulse_interval": 0,
                "max_pulses": 3,
                "min_interval_hours": 12,
                "start_hour": 6,
                "end_hour": 20,
                "node_id": "main",
                "actuator_id": "pump",
            },
        }
        state.hardware_manager = MagicMock()
        state.local_latest_data = {}
        state.power_save_mode = False
        db.insert_watering = MagicMock()
        db.query_last_watering_time = MagicMock(return_value=None)
        db.query_watering_safety = MagicMock(return_value={})
        db.query_latest_soil = MagicMock(return_value=50.0)

    def test_power_save_skips(self):
        """省电模式下不浇水。"""
        state.power_save_mode = True
        from datetime import datetime
        from core.logic.watering import check_auto_watering
        check_auto_watering("main", {"soil_moisture": 30.0}, datetime(2026, 8, 20, 8, 0))
        state.hardware_manager.trigger_actuator.assert_not_called()

    def test_out_of_window_skips(self):
        """当前时刻不在 start_hour ~ end_hour 之间 → 不浇。"""
        from datetime import datetime
        from core.logic.watering import check_auto_watering
        # 5:00 < 6:00
        check_auto_watering("main", {"soil_moisture": 30.0}, datetime(2026, 8, 20, 5, 0))
        state.hardware_manager.trigger_actuator.assert_not_called()
        
        # 21:00 > 20:00
        check_auto_watering("main", {"soil_moisture": 30.0}, datetime(2026, 8, 20, 21, 0))
        state.hardware_manager.trigger_actuator.assert_not_called()

    def test_cross_day_window(self):
        """跨天窗口：start=22, end=6。"""
        config.global_config["auto_water"]["start_hour"] = 22
        config.global_config["auto_water"]["end_hour"] = 6
        from datetime import datetime
        from core.logic.watering import check_auto_watering
        
        # 23:00 在区间内，满足触发条件 (阈值 65)
        state.hardware_manager.trigger_actuator.return_value = True
        state.hardware_manager.read_local_node.return_value = {"soil_moisture": 90.0}
        check_auto_watering("main", {"soil_moisture": 30.0}, datetime(2026, 8, 20, 23, 0))
        state.hardware_manager.trigger_actuator.assert_called()
        
        state.hardware_manager.trigger_actuator.reset_mock()
        # 5:00 在区间内
        check_auto_watering("main", {"soil_moisture": 30.0}, datetime(2026, 8, 20, 5, 0))
        state.hardware_manager.trigger_actuator.assert_called()
        
        state.hardware_manager.trigger_actuator.reset_mock()
        # 12:00 不在区间内
        check_auto_watering("main", {"soil_moisture": 30.0}, datetime(2026, 8, 20, 12, 0))
        state.hardware_manager.trigger_actuator.assert_not_called()

    def test_above_threshold_skips(self):
        """湿度高于阈值 → 不浇。"""
        from datetime import datetime
        from core.logic.watering import check_auto_watering
        check_auto_watering("main", {"soil_moisture": 70.0}, datetime(2026, 8, 20, 8, 0))
        state.hardware_manager.trigger_actuator.assert_not_called()

    @patch("time.sleep")
    def test_triggers_pulse_watering(self, mock_sleep):
        """条件全部满足 → 触发脉冲浇水。"""
        state.hardware_manager.trigger_actuator.return_value = True
        state.hardware_manager.read_local_node.return_value = {"soil_moisture": 90.0}

        from datetime import datetime
        from core.logic.watering import check_auto_watering
        check_auto_watering("main", {"soil_moisture": 30.0}, datetime(2026, 8, 20, 8, 0))

        # 至少调用了一次泵
        self.assertGreaterEqual(state.hardware_manager.trigger_actuator.call_count, 1)
        db.insert_watering.assert_called_once()

    def test_wrong_node_skips(self):
        """非配置指定的节点 → 不浇。"""
        from datetime import datetime
        from core.logic.watering import check_auto_watering
        check_auto_watering("sub1", {"soil_moisture": 30.0}, datetime(2026, 8, 20, 8, 0))
        state.hardware_manager.trigger_actuator.assert_not_called()

    def test_disabled_skips(self):
        """自动浇水未启用 → 不浇。"""
        config.global_config["auto_water"]["enabled"] = False
        from datetime import datetime
        from core.logic.watering import check_auto_watering
        check_auto_watering("main", {"soil_moisture": 30.0}, datetime(2026, 8, 20, 8, 0))
        state.hardware_manager.trigger_actuator.assert_not_called()


# ---- trigger_watering 手动浇水兼容性 ----

class TestTriggerWatering(unittest.TestCase):
    """trigger_watering() 手动浇水路径不受脉冲逻辑影响。"""

    def setUp(self):
        config.global_config = {
            "auto_water": {
                "enabled": True,
                "duration": 0.5,
                "threshold": 65.0,
                "target_moisture": 85.0,
                "pulse_interval": 60,
                "max_pulses": 10,
                "min_interval_hours": 12,
                "start_hour": 6,
                "end_hour": 20,
                "node_id": "main",
                "actuator_id": "pump",
            },
        }
        state.hardware_manager = MagicMock()
        state.hardware_manager.trigger_actuator.return_value = True
        db.insert_watering = MagicMock()
        db.query_watering_safety = MagicMock(return_value={})

    def test_manual_watering_defaults(self):
        """手动浇水走 trigger_watering，pulse_count 默认 1，soil_after 默认 None。"""
        from core.logic.watering import trigger_watering
        result = trigger_watering("main", 45.0, duration=0.5)
        self.assertTrue(result)
        db.insert_watering.assert_called_once_with(
            "main", 0.5, 45.0, pulse_count=1, soil_after=None
        )


# ---- merge_defaults 兼容性 ----

class TestMergeDefaults(unittest.TestCase):
    """老配置文件缺少脉冲浇水字段时，merge_defaults 应自动补全。"""

    @classmethod
    def setUpClass(cls):
        """加载真实的 merge_defaults 函数（绕过桩）。"""
        import importlib
        real_config = importlib.import_module("core.config")
        # 桩模块上的 merge_defaults 是 MagicMock，要用 importlib 重载
        importlib.reload(real_config)
        cls.merge_defaults = staticmethod(real_config.merge_defaults)

    def test_old_config_gets_new_fields(self):
        """只有 enabled/threshold/duration/hour 的老配置 → 补全新字段。"""
        old_cfg = {
            "auto_water": {
                "enabled": True,
                "threshold": 50.0,
                "duration": 0.5,
                "hour": 6,
                "node_id": "main",
                "actuator_id": "pump",
            },
        }
        result = self.merge_defaults(old_cfg)

        aw = result["auto_water"]
        self.assertEqual(aw["target_moisture"], 85.0)
        self.assertEqual(aw["pulse_interval"], 60)
        self.assertEqual(aw["max_pulses"], 10)
        self.assertEqual(aw["min_interval_hours"], 12)
        self.assertEqual(aw["start_hour"], 6)
        self.assertEqual(aw["end_hour"], 20)
        self.assertNotIn("hour", aw)
        # 老的 threshold 值保留，不被覆盖
        self.assertEqual(aw["threshold"], 50.0)

    def test_existing_fields_not_overwritten(self):
        """已有的字段不会被默认值覆盖。"""
        cfg = {
            "auto_water": {
                "enabled": True,
                "threshold": 70.0,
                "target_moisture": 90.0,
                "duration": 1.0,
                "pulse_interval": 120,
                "max_pulses": 5,
                "min_interval_hours": 6,
                "start_hour": 8,
                "end_hour": 18,
                "node_id": "main",
                "actuator_id": "pump",
            },
        }
        result = self.merge_defaults(cfg)

        aw = result["auto_water"]
        self.assertEqual(aw["threshold"], 70.0)
        self.assertEqual(aw["target_moisture"], 90.0)
        self.assertEqual(aw["pulse_interval"], 120)
        self.assertEqual(aw["max_pulses"], 5)


if __name__ == "__main__":
    unittest.main()
