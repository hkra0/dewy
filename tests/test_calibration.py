"""土壤校准算法的单元测试。

测试 hardware/soil_calibration.py 的纯算法逻辑（EMA、滑动窗口、反转检测、
自适应阈值、稳定判定）与持久化读写。该模块仅用标准库，无需 core 桩。

另测 hardware/manager.py 的 _build_device 注入元信息与 notify_watering。
"""

import importlib.util
import json
import logging
import os
import pathlib
import tempfile
import threading
import time
import unittest

# ---- 加载 soil_calibration（纯标准库模块，不需要 core 桩）----
_spec = importlib.util.spec_from_file_location(
    "tests._soil_calibration",
    pathlib.Path(__file__).resolve().parent.parent / "hardware" / "soil_calibration.py",
)
cal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cal)

import core.state as state  # 本包 __init__ 装好的桩

from hardware.manager import HardwareManager


# ==================== SoilCalibrator 纯算法 ====================

class EMATest(unittest.TestCase):
    """EMA 平滑：S_t = α·Y_t + (1-α)·S_{t-1}"""

    def setUp(self):
        self.c = cal.SoilCalibrator({"alpha": 0.2})

    def test_first_sample_uses_raw_value(self):
        """首个样本直接赋值，避免从 0 起步的冷启动偏置。"""
        self.assertEqual(self.c.update_ema(7000.0), 7000.0)

    def test_subsequent_samples_blend(self):
        """S_1 = 0.2*7200 + 0.8*7000 = 7040"""
        self.c.update_ema(7000.0)
        result = self.c.update_ema(7200.0)
        self.assertAlmostEqual(result, 7040.0)

    def test_converges_to_constant_input(self):
        """持续输入同一值时 EMA 收敛到该值。"""
        for _ in range(100):
            val = self.c.update_ema(7500.0)
        self.assertAlmostEqual(val, 7500.0, places=1)

    def test_resets_cleanly(self):
        self.c.update_ema(7000.0)
        self.c.update_ema(7200.0)
        self.c._reset()
        self.assertIsNone(self.c.ema)
        self.assertEqual(len(self.c.window), 0)
        self.assertEqual(self.c.stable_count, 0)
        self.assertEqual(self.c.max_delta, 0.0)
        self.assertEqual(self.c.drift_sign, 0)
        self.assertFalse(self.c.has_drained)


class SlidingWindowTest(unittest.TestCase):
    """滑动窗口：固定长度、首尾差值。"""

    def setUp(self):
        self.c = cal.SoilCalibrator({"window_size": 5})
        self.c.ema = 7500.0  # 设定 ema 供噪声地板计算

    def test_window_not_full_returns_false(self):
        for v in range(3):
            full, delta, stable = self.c.push_and_check(float(v))
            self.assertFalse(full)
            self.assertIsNone(delta)
            self.assertFalse(stable)

    def test_window_full_returns_delta(self):
        for v in range(5):
            full, delta, _ = self.c.push_and_check(float(v))
        self.assertTrue(full)
        # delta = newest(4.0) - oldest(0.0) = 4.0
        self.assertAlmostEqual(delta, 4.0)

    def test_window_evicts_oldest(self):
        for v in range(5):
            self.c.push_and_check(float(v))
        # push 10.0, window becomes [1,2,3,4,10], delta = 10-1 = 9
        full, delta, _ = self.c.push_and_check(10.0)
        self.assertTrue(full)
        self.assertAlmostEqual(delta, 9.0)

    def test_delta_zero_when_all_equal(self):
        for _ in range(5):
            full, delta, _ = self.c.push_and_check(7000.0)
        self.assertTrue(full)
        self.assertAlmostEqual(delta, 0.0)


# ==================== 反转检测 ====================

class ReversalDetectionTest(unittest.TestCase):
    """反转检测：积水尖峰与排水方向相反，符号反转 = 排水已开始。"""

    def setUp(self):
        # window=5, confirm=3, 默认 stable_ratio=0.1, noise_ratio=0.001
        self.c = cal.SoilCalibrator({"window_size": 5, "stable_confirm": 3})
        self.c.ema = 7500.0  # 噪声地板 = 7500 * 0.001 = 7.5

    def test_declining_then_rising_sets_has_drained(self):
        """先下降（尖峰）后上升（排水）-> has_drained=True。"""
        # 下降序列：8000 -> 7200，Δ < 0
        for v in [8000, 7800, 7600, 7400, 7200]:
            self.c.push_and_check(float(v))
        self.assertEqual(self.c.drift_sign, -1)
        self.assertFalse(self.c.has_drained)

        # 上升序列：7400 -> 8200，Δ > 0（反转！）
        for v in [7400, 7600, 7800, 8000, 8200]:
            self.c.push_and_check(float(v))
        self.assertEqual(self.c.drift_sign, 1)
        self.assertTrue(self.c.has_drained)

    def test_rising_then_falling_sets_has_drained(self):
        """先上升（尖峰）后下降（排水）-> has_drained=True。方向无关。"""
        for v in [7000, 7200, 7400, 7600, 7800]:
            self.c.push_and_check(float(v))
        self.assertEqual(self.c.drift_sign, 1)
        self.assertFalse(self.c.has_drained)

        for v in [7600, 7400, 7200, 7000, 6800]:
            self.c.push_and_check(float(v))
        self.assertEqual(self.c.drift_sign, -1)
        self.assertTrue(self.c.has_drained)

    def test_monotonic_no_reversal_has_drained_stays_false(self):
        """持续单方向变化 -> 无反转 -> has_drained=False。"""
        for v in range(8000, 7000, -50):
            self.c.push_and_check(float(v))
        self.assertFalse(self.c.has_drained)

    def test_plateau_does_not_set_has_drained(self):
        """积水平台期 |Δ|≈0：不更新方向，不触发反转。"""
        # 先有一个方向的显著变化
        for v in [8000, 7600, 7200, 7000, 7000]:
            self.c.push_and_check(float(v))
        self.assertEqual(self.c.drift_sign, -1)
        self.assertFalse(self.c.has_drained)

        # 平台期：全部相同值，Δ=0 < 噪声地板，drift_sign 不变
        for _ in range(10):
            self.c.push_and_check(7000.0)
        self.assertEqual(self.c.drift_sign, -1)
        self.assertFalse(self.c.has_drained)

    def test_noise_does_not_trigger_reversal(self):
        """噪声级波动（|Δ| < 噪声地板）不触发反转。"""
        base = 7500.0
        # 填窗口，微小波动
        for i in range(5):
            self.c.push_and_check(base + (i % 3 - 1) * 0.5)  # ±0.5, 远小于噪声地板
        self.assertEqual(self.c.drift_sign, 0)
        self.assertFalse(self.c.has_drained)

    def test_second_reversal_keeps_has_drained_true(self):
        """has_drained 一旦为 True 就不会回到 False。"""
        # 下降
        for v in [8000, 7800, 7600, 7400, 7200]:
            self.c.push_and_check(float(v))
        # 上升（反转 1）
        for v in [7400, 7600, 7800, 8000, 8200]:
            self.c.push_and_check(float(v))
        self.assertTrue(self.c.has_drained)
        # 再次下降（反转 2）
        for v in [8000, 7800, 7600, 7400, 7200]:
            self.c.push_and_check(float(v))
        self.assertTrue(self.c.has_drained)


# ==================== 自适应阈值 ====================

class AdaptiveThresholdTest(unittest.TestCase):
    """自适应阈值：threshold = max(max_delta × stable_ratio, |ema| × noise_ratio)。"""

    def setUp(self):
        self.c = cal.SoilCalibrator({
            "window_size": 5,
            "stable_ratio": 0.1,
            "noise_ratio": 0.001,
        })
        self.c.ema = 7500.0  # 噪声地板 = 7.5

    def test_threshold_scales_with_peak_delta(self):
        """大尖峰产生大阈值，小变化产生小阈值。"""
        # 大尖峰：Δ = -1000
        for v in [8000, 7800, 7600, 7400, 7000]:
            self.c.push_and_check(float(v))
        large_max = self.c.max_delta
        self.assertGreater(large_max, 500)

        # 重置，小尖峰：Δ = -50
        self.c._reset()
        self.c.ema = 7500.0
        for v in [7550, 7540, 7530, 7520, 7500]:
            self.c.push_and_check(float(v))
        small_max = self.c.max_delta
        self.assertLess(small_max, 100)

        # 阈值应按比例缩放
        large_threshold = max(large_max * 0.1, 7.5)
        small_threshold = max(small_max * 0.1, 7.5)
        self.assertGreater(large_threshold, small_threshold)

    def test_noise_floor_is_minimum_threshold(self):
        """当 max_delta 很小时，阈值不低于噪声地板。"""
        for v in [7501, 7500, 7499, 7500, 7501]:
            self.c.push_and_check(float(v))
        # max_delta 很小，阈值 = max(small * 0.1, 7.5) = 7.5
        expected = max(self.c.max_delta * 0.1, 7.5)
        self.assertAlmostEqual(expected, 7.5, places=1)


# ==================== 稳定判定 ====================

class StabilityDetectionTest(unittest.TestCase):
    """稳定判定：has_drained 后连续 N 次 |Δ| < 自适应阈值。"""

    def setUp(self):
        self.c = cal.SoilCalibrator({
            "window_size": 5,
            "stable_confirm": 3,
        })
        self.c.ema = 7500.0

    def test_spike_drainage_stable_triggers(self):
        """完整序列：尖峰 -> 排水（反转）-> 稳定 -> 检测到稳定。

        排水阶段结束后，窗口仍残留排水期的旧值，需要几次 push 让旧值
        退出窗口、Δ 归零，然后连续 confirm 次才判定稳定。
        """
        # 尖峰：值下降（Δ < 0）
        for v in [8000, 7800, 7600, 7400, 7200]:
            self.c.push_and_check(float(v))
        self.assertFalse(self.c.has_drained)

        # 排水：值上升（Δ > 0，反转！）
        for v in [7400, 7600, 7800, 8000, 8200]:
            self.c.push_and_check(float(v))
        self.assertTrue(self.c.has_drained)

        # 稳定：需足够次数让旧值退出窗口 + 连续 confirm 次命中
        is_stable = False
        for _ in range(10):
            _, _, is_stable = self.c.push_and_check(8200.0)
            if is_stable:
                break
        self.assertTrue(is_stable)

    def test_plateau_without_drainage_rejected(self):
        """积水平台期 |Δ|≈0 但 has_drained=False -> 不判定稳定。"""
        # 尖峰：值下降
        for v in [8000, 7800, 7600, 7400, 7200]:
            self.c.push_and_check(float(v))
        self.assertFalse(self.c.has_drained)

        # 平台期：值不变（积水未排空）
        for _ in range(20):
            _, _, is_stable = self.c.push_and_check(7200.0)
            self.assertFalse(is_stable, "平台期不应判定稳定")
        self.assertFalse(self.c.has_drained)

    def test_no_drainage_no_stability(self):
        """只有单调变化（无反转）-> has_drained=False -> 永不判定稳定。"""
        for i in range(50):
            v = 8000.0 - i * 10  # 持续下降
            _, _, is_stable = self.c.push_and_check(v)
            self.assertFalse(is_stable)
        self.assertFalse(self.c.has_drained)

    def test_large_delta_after_stable_resets_count(self):
        """稳定计数中遇到大 Δ -> 清零。"""
        # 完成尖峰+排水
        for v in [8000, 7800, 7600, 7400, 7200]:
            self.c.push_and_check(float(v))
        for v in [7400, 7600, 7800, 8000, 8200]:
            self.c.push_and_check(float(v))
        self.assertTrue(self.c.has_drained)

        # 稳定几步
        for _ in range(3):
            self.c.push_and_check(8200.0)
        # 此时 count 应该在增长

        # 大跳变
        self.c.push_and_check(9000.0)
        self.assertEqual(self.c.stable_count, 0)

    def test_confirm_count_required(self):
        """需要连续 confirm 次才判定稳定，少于 confirm 次不算。"""
        c = cal.SoilCalibrator({"window_size": 3, "stable_confirm": 5})
        c.ema = 7500.0
        # 尖峰
        for v in [8000, 7000, 7000]:
            c.push_and_check(float(v))
        # 排水（反转）
        for v in [7500, 8000, 8000]:
            c.push_and_check(float(v))
        self.assertTrue(c.has_drained)
        # 稳定 4 次（不够 5 次）
        for _ in range(4):
            _, _, is_stable = c.push_and_check(8000.0)
            self.assertFalse(is_stable)
        # 第 5 次
        _, _, is_stable = c.push_and_check(8000.0)
        self.assertTrue(is_stable)


# ==================== run_calibration 集成 ====================

class RunCalibrationTest(unittest.TestCase):
    """run_calibration 的端到端测试（用假 read_func）。"""

    def test_spike_drainage_stable_detects(self):
        """完整序列：浇水前 -> 积水尖峰 -> 排水 -> 田间持水量稳定。"""
        # 模拟真实浇水曲线（EMA 平滑后的效果）：
        # Phase 1: 浇水前基线
        readings = [8000.0] * 20
        # Phase 2: 积水尖峰（值骤降）
        readings += [7000.0] * 20
        # Phase 3: 排水（值回升，触发反转）
        readings += [7500.0] * 20
        # Phase 4: 稳定在田间持水量
        readings += [7500.0] * 40

        idx = [0]

        def read_func():
            if idx[0] >= len(readings):
                return None
            v = readings[idx[0]]
            idx[0] += 1
            return v

        config = {
            "window_size": 10,
            "stable_confirm": 3,
            "settle_delay_sec": 0,
            "sample_interval_sec": 0.01,
            "timeout_min": 5,
        }
        result = cal.run_calibration(read_func, config=config)
        self.assertIsNotNone(result)
        # EMA 未完全收敛到 7500，但在合理范围内
        self.assertAlmostEqual(result, 7500.0, delta=100.0)

    def test_plateau_only_times_out(self):
        """只有积水尖峰+平台期（无排水）-> 超时不更新基准。"""
        readings = [8000.0] * 10
        readings += [7000.0] * 200  # 尖峰后一直平台，不排水

        idx = [0]

        def read_func():
            if idx[0] >= len(readings):
                return None
            v = readings[idx[0]]
            idx[0] += 1
            return v

        config = {
            "window_size": 10,
            "stable_confirm": 3,
            "settle_delay_sec": 0,
            "sample_interval_sec": 0.01,
            "timeout_min": 0.02,  # ~1.2 秒超时
        }
        result = cal.run_calibration(read_func, config=config)
        self.assertIsNone(result)

    def test_monotonic_change_times_out(self):
        """持续单方向变化（无反转）-> 超时返回 None。"""
        counter = [0]

        def read_func():
            counter[0] += 1
            return 7000.0 + counter[0] * 100  # 持续上升，无反转

        config = {
            "window_size": 5,
            "stable_confirm": 3,
            "settle_delay_sec": 0,
            "sample_interval_sec": 0.01,
            "timeout_min": 0.005,  # ~0.3 秒超时
        }
        result = cal.run_calibration(read_func, config=config)
        self.assertIsNone(result)

    def test_restart_event_returns_none(self):
        """收到 restart 信号时立即退出返回 None。"""
        restart = threading.Event()

        def read_func():
            time.sleep(0.1)
            return 7000.0

        config = {
            "window_size": 100,  # 永远填不满
            "stable_confirm": 10,
            "settle_delay_sec": 0,
            "sample_interval_sec": 0.01,
            "timeout_min": 5,
        }

        result_holder = [None]

        def runner():
            result_holder[0] = cal.run_calibration(read_func, config=config,
                                                    restart_event=restart)

        t = threading.Thread(target=runner, daemon=True)
        t.start()
        time.sleep(0.2)
        restart.set()
        t.join(timeout=2)
        self.assertIsNone(result_holder[0])

    def test_consecutive_read_failures_abort(self):
        """连续读取失败超过上限应中止返回 None。"""
        calls = [0]

        def read_func():
            calls[0] += 1
            return None

        config = {
            "window_size": 5,
            "stable_confirm": 3,
            "settle_delay_sec": 0,
            "sample_interval_sec": 0.01,
            "timeout_min": 5,
        }
        result = cal.run_calibration(read_func, config=config)
        self.assertIsNone(result)
        self.assertGreaterEqual(calls[0], cal.MAX_READ_FAILURES)

    def test_adaptive_threshold_handles_small_spike(self):
        """小幅尖峰也能正确检测稳定（自适应阈值缩放）。"""
        # 小幅变化：7600 -> 7500 -> 7550（尖峰仅 100 ADC）
        readings = [7600.0] * 15
        readings += [7500.0] * 15
        readings += [7550.0] * 30
        readings += [7550.0] * 30

        idx = [0]

        def read_func():
            if idx[0] >= len(readings):
                return None
            v = readings[idx[0]]
            idx[0] += 1
            return v

        config = {
            "window_size": 10,
            "stable_confirm": 3,
            "settle_delay_sec": 0,
            "sample_interval_sec": 0.01,
            "timeout_min": 5,
        }
        result = cal.run_calibration(read_func, config=config)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 7550.0, delta=50.0)


# ==================== 持久化 ====================

class PersistenceTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.data_dir = self._tmp

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_then_load(self):
        cal.save_calibration(self.data_dir, "main", "soil", 7491.5)
        val = cal.load_calibration(self.data_dir, "main", "soil")
        self.assertAlmostEqual(val, 7491.5)

    def test_load_missing_file_returns_none(self):
        self.assertIsNone(cal.load_calibration(self.data_dir, "main", "soil"))

    def test_load_corrupt_file_returns_none(self):
        path = os.path.join(self.data_dir, "calibration.json")
        with open(path, "w") as f:
            f.write("not json {{{")
        self.assertIsNone(cal.load_calibration(self.data_dir, "main", "soil"))

    def test_multiple_sensors_coexist(self):
        cal.save_calibration(self.data_dir, "main", "soil", 7491.0)
        cal.save_calibration(self.data_dir, "main", "soil2", 6500.0)
        cal.save_calibration(self.data_dir, "sub1", "soil", 8000.0)

        self.assertAlmostEqual(cal.load_calibration(self.data_dir, "main", "soil"), 7491.0)
        self.assertAlmostEqual(cal.load_calibration(self.data_dir, "main", "soil2"), 6500.0)
        self.assertAlmostEqual(cal.load_calibration(self.data_dir, "sub1", "soil"), 8000.0)

    def test_save_overwrites_previous(self):
        cal.save_calibration(self.data_dir, "main", "soil", 6883.0)
        cal.save_calibration(self.data_dir, "main", "soil", 7491.0)
        self.assertAlmostEqual(cal.load_calibration(self.data_dir, "main", "soil"), 7491.0)

    def test_unknown_key_returns_none(self):
        cal.save_calibration(self.data_dir, "main", "soil", 7491.0)
        self.assertIsNone(cal.load_calibration(self.data_dir, "main", "other"))

    def test_no_temp_files_left_behind(self):
        """原子写入成功后不应残留临时文件。"""
        cal.save_calibration(self.data_dir, "main", "soil", 7491.0)
        leftovers = [f for f in os.listdir(self.data_dir)
                     if f.startswith(".calibration-") or f.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        self.assertAlmostEqual(
            cal.load_calibration(self.data_dir, "main", "soil"), 7491.0)

    def test_old_file_intact_when_replace_fails(self):
        """os.replace 失败（模拟崩溃在替换瞬间）时旧文件应完好，临时文件应清理。"""
        from unittest.mock import patch

        cal.save_calibration(self.data_dir, "main", "soil", 6883.0)
        calib_path = os.path.join(self.data_dir, "calibration.json")
        with open(calib_path) as f:
            old_content = f.read()

        with patch.object(cal.os, "replace", side_effect=OSError("disk full")):
            cal.save_calibration(self.data_dir, "main", "soil", 7491.0)

        with open(calib_path) as f:
            self.assertEqual(f.read(), old_content)
        self.assertAlmostEqual(
            cal.load_calibration(self.data_dir, "main", "soil"), 6883.0)
        leftovers = [f for f in os.listdir(self.data_dir)
                     if f.startswith(".calibration-")]
        self.assertEqual(leftovers, [])

    def test_write_to_new_file_is_valid_json(self):
        """从零开始（文件不存在）的原子写入应产出合法 JSON。"""
        cal.save_calibration(self.data_dir, "main", "soil", 7491.0)
        with open(os.path.join(self.data_dir, "calibration.json")) as f:
            data = json.load(f)
        self.assertIn("main:soil", data)
        self.assertAlmostEqual(data["main:soil"]["val_water"], 7491.0)
        self.assertIn("calibrated_at", data["main:soil"])


# ==================== HardwareManager 集成 ====================

class ManagerInjectionTest(unittest.TestCase):
    """_build_device 注入元信息、notify_watering 鸭子类型调用。"""

    def _manager(self):
        hm = HardwareManager.__new__(HardwareManager)
        hm._driver_class_cache = {}
        hm.data_dir = "/tmp/test_data"
        return hm

    def test_metadata_params_injected(self):
        """_build_device 向驱动注入 _data_dir / _node_id / _sensor_id。"""
        class Spy:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        hm = self._manager()
        hm._driver_class_cache["Spy"] = Spy
        obj = hm._build_device("main", "传感器", "soil", {"driver": "Spy", "bus": 1})

        self.assertIsNotNone(obj)
        self.assertEqual(obj.kwargs.get("_data_dir"), "/tmp/test_data")
        self.assertEqual(obj.kwargs.get("_node_id"), "main")
        self.assertEqual(obj.kwargs.get("_sensor_id"), "soil")
        self.assertEqual(obj.kwargs.get("bus"), 1)

    def test_config_driver_key_not_passed(self):
        """driver 键不应传给驱动实例。"""
        class Spy:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        hm = self._manager()
        hm._driver_class_cache["Spy"] = Spy
        obj = hm._build_device("main", "传感器", "soil", {"driver": "Spy", "bus": 1})
        self.assertNotIn("driver", obj.kwargs)

    def test_notify_watering_calls_on_watering(self):
        """notify_watering 对实现了 on_watering() 的传感器调用它。"""
        class SoilSensor:
            def __init__(self):
                self.watered = False
            def on_watering(self):
                self.watered = True

        class OtherSensor:
            pass  # No on_watering, should be skipped silently

        hm = self._manager()
        soil = SoilSensor()
        other = OtherSensor()
        hm.local_sensors = {"main": {"soil": soil, "sht30": other}}

        hm.notify_watering("main")
        self.assertTrue(soil.watered)

    def test_notify_watering_unknown_node_is_noop(self):
        """通知不存在的节点不应抛异常。"""
        hm = self._manager()
        hm.local_sensors = {}
        hm.notify_watering("nonexistent")  # Should not raise

    def test_notify_watering_isolates_failures(self):
        """一个传感器的 on_watering 抛异常不应影响其他传感器。"""
        class Good:
            def __init__(self):
                self.watered = False
            def on_watering(self):
                self.watered = True

        class Bad:
            def on_watering(self):
                raise RuntimeError("I2C error")

        hm = self._manager()
        good = Good()
        hm.local_sensors = {"main": {"bad": Bad(), "good": good}}

        with self.assertLogs("hardware.manager", level=logging.WARNING):
            hm.notify_watering("main")
        self.assertTrue(good.watered)


# ==================== 数据库 schema 迁移 ====================

class DatabaseMigrationTest(unittest.TestCase):
    """soil_adc_raw 列的自动迁移：老库 ALTER TABLE、新库直接建、幂等。"""

    def setUp(self):
        import sqlite3
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        state.DB_FILE = self._tmp.name
        state.db_lock = threading.RLock()

    def tearDown(self):
        os.unlink(self._tmp.name)

    def _load_real_db(self):
        spec = importlib.util.spec_from_file_location(
            "tests._real_db_migration",
            pathlib.Path(__file__).resolve().parent.parent / "core" / "database.py",
        )
        db = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(db)
        return db

    def test_old_schema_gets_soil_adc_raw_column(self):
        """老库（无 soil_adc_raw 列）运行 init_db 后自动补列。"""
        db = self._load_real_db()
        with db.get_conn() as conn:
            conn.execute('''
                CREATE TABLE node_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    node_id TEXT NOT NULL,
                    temperature REAL, humidity REAL, soil_moisture REAL,
                    pressure REAL, voltage REAL, current REAL,
                    is_anomaly INTEGER DEFAULT 0
                )
            ''')
            conn.execute("INSERT INTO node_data (node_id, soil_moisture) VALUES ('main', 50.0)")

        db.init_db()

        with db.get_conn() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(node_data)")]
            self.assertIn("soil_adc_raw", cols)
            row = conn.execute("SELECT soil_moisture, soil_adc_raw FROM node_data").fetchone()
            self.assertEqual(row, (50.0, None))

    def test_new_schema_has_soil_adc_raw_from_start(self):
        """全新数据库直接建表就包含 soil_adc_raw 列。"""
        db = self._load_real_db()
        db.init_db()
        with db.get_conn() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(node_data)")]
            self.assertIn("soil_adc_raw", cols)

    def test_migration_is_idempotent(self):
        """多次运行 init_db 不会报错或重复加列。"""
        db = self._load_real_db()
        db.init_db()
        db.init_db()
        db.init_db()
        with db.get_conn() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(node_data)")]
            self.assertEqual(cols.count("soil_adc_raw"), 1)

    def test_soil_adc_raw_not_leaked_to_metrics(self):
        """soil_adc_raw 在 NODE_DATA_FIELDS 里，不应进 node_metrics 长表。"""
        db = self._load_real_db()
        db.init_db()
        db.insert_node_data([{"node_id": "main", "soil_moisture": 55.0, "soil_adc_raw": 7491.0}])
        self.assertEqual(db.query_metric_keys("main"), [])

    def test_insert_without_soil_adc_raw_is_backward_compatible(self):
        """不提供 soil_adc_raw 的旧驱动仍能正常写入。"""
        db = self._load_real_db()
        db.init_db()
        db.insert_node_data([{"node_id": "main", "soil_moisture": 55.0}])
        row = db.query("SELECT soil_adc_raw FROM node_data WHERE node_id='main'")[0]
        self.assertEqual(row, (None,))


if __name__ == "__main__":
    unittest.main()
