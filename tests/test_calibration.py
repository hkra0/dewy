"""土壤校准算法的单元测试。

测试 hardware/soil_calibration.py 的纯算法逻辑（EMA、滑动窗口极差、
盲区延迟、稳定判定、毛刺过滤）与持久化读写。该模块仅用标准库，无需 core 桩。

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
        self.assertEqual(self.c.samples_seen, 0)


# ==================== 滑动窗口极差 ====================

class SlidingWindowTest(unittest.TestCase):
    """滑动窗口：固定长度、极差计算。"""

    def setUp(self):
        # window=5, settle_delay=0 (无盲区), threshold=18, confirm=2
        self.c = cal.SoilCalibrator({
            "window_size": 5, "settle_delay_sec": 0,
            "stable_threshold": 18, "stable_confirm": 2,
        })
        self.c.ema = 7500.0

    def test_window_not_full_returns_false(self):
        for v in range(3):
            full, rng, stable = self.c.push_and_check(float(v))
            self.assertFalse(full)
            self.assertIsNone(rng)
            self.assertFalse(stable)

    def test_window_full_returns_range(self):
        for v in [7500, 7505, 7498, 7502, 7500]:
            full, rng, _ = self.c.push_and_check(float(v))
        self.assertTrue(full)
        # range = max(7505) - min(7498) = 7.0
        self.assertAlmostEqual(rng, 7.0)

    def test_window_evicts_oldest(self):
        for v in [7500, 7505, 7498, 7502, 7500]:
            self.c.push_and_check(float(v))
        # push 7520, window becomes [7505, 7498, 7502, 7500, 7520]
        # range = 7520 - 7498 = 22.0
        full, rng, _ = self.c.push_and_check(7520.0)
        self.assertTrue(full)
        self.assertAlmostEqual(rng, 22.0)

    def test_range_zero_when_all_equal(self):
        for _ in range(5):
            full, rng, _ = self.c.push_and_check(7000.0)
        self.assertTrue(full)
        self.assertAlmostEqual(rng, 0.0)


# ==================== 盲区延迟 ====================

class SettleDelayTest(unittest.TestCase):
    """盲区期：只采集数据，不做稳定判定。"""

    def test_no_stability_during_settle(self):
        """盲区内即使数据完全平稳也不判定稳定。"""
        c = cal.SoilCalibrator({
            "window_size": 3, "settle_delay_sec": 30,
            "sample_interval_sec": 10, "stable_threshold": 18,
            "stable_confirm": 1,
        })
        c.ema = 7000.0
        # settle_samples = 30/10 = 3，前 3 个样本在盲区内
        for i in range(3):
            full, rng, stable = c.push_and_check(7000.0)
            self.assertFalse(stable, f"盲区内不应判定稳定 (step {i})")
        # 第 4 个样本开始判定
        full, rng, stable = c.push_and_check(7000.0)
        self.assertTrue(stable, "盲区后应立即判定稳定（range=0 < 18）")

    def test_settle_zero_allows_immediate_check(self):
        """settle_delay=0 时从第一个满窗口即可判定。"""
        c = cal.SoilCalibrator({
            "window_size": 3, "settle_delay_sec": 0,
            "stable_threshold": 18, "stable_confirm": 1,
        })
        c.ema = 7000.0
        full, rng, stable = c.push_and_check(7000.0)
        full, rng, stable = c.push_and_check(7000.0)
        full, rng, stable = c.push_and_check(7000.0)
        self.assertTrue(stable)

    def test_settle_samples_calculation(self):
        """settle_samples = round(settle_delay / sample_interval)。"""
        c = cal.SoilCalibrator({
            "settle_delay_sec": 600, "sample_interval_sec": 10,
        })
        self.assertEqual(c.settle_samples, 60)

        c2 = cal.SoilCalibrator({
            "settle_delay_sec": 25, "sample_interval_sec": 10,
        })
        self.assertEqual(c2.settle_samples, 3)  # round(2.5) = 2, but int(2.5+0.5)=3


# ==================== 极差稳定判定 ====================

class StabilityDetectionTest(unittest.TestCase):
    """稳定判定：窗口极差 < threshold 连续 confirm 次。"""

    def setUp(self):
        self.c = cal.SoilCalibrator({
            "window_size": 5, "settle_delay_sec": 0,
            "stable_threshold": 15, "stable_confirm": 2,
        })
        self.c.ema = 7500.0

    def test_flat_data_triggers_stable(self):
        """完全平稳的数据应快速判定稳定。"""
        for _ in range(5):
            _, _, stable = self.c.push_and_check(7500.0)
        # range=0 < 15, count=1 (need 2)
        self.assertFalse(stable)
        _, _, stable = self.c.push_and_check(7500.0)
        self.assertTrue(stable)

    def test_large_range_rejected(self):
        """极差超过阈值时不判定稳定。"""
        for v in [7500, 7530, 7470, 7520, 7480]:
            _, _, stable = self.c.push_and_check(float(v))
        # range = 7530 - 7470 = 60 > 15
        self.assertFalse(stable)
        self.assertEqual(self.c.stable_count, 0)

    def test_range_resets_count_on_violation(self):
        """稳定计数中遇到大极差 -> 清零。"""
        # 先积累 1 次稳定
        for _ in range(5):
            self.c.push_and_check(7500.0)
        self.assertEqual(self.c.stable_count, 1)
        # 大跳变
        self.c.push_and_check(7600.0)
        self.assertEqual(self.c.stable_count, 0)

    def test_confirm_count_required(self):
        """需要连续 confirm 次才判定稳定。"""
        c = cal.SoilCalibrator({
            "window_size": 3, "settle_delay_sec": 0,
            "stable_threshold": 20, "stable_confirm": 4,
        })
        c.ema = 7000.0
        for _ in range(3):
            c.push_and_check(7000.0)  # 填满窗口, range=0, count=1
        for i in range(2):
            _, _, stable = c.push_and_check(7000.0)
            self.assertFalse(stable, f"第 {i+2} 次不应稳定 (需 4 次)")
        _, _, stable = c.push_and_check(7000.0)
        self.assertTrue(stable, "第 4 次应稳定")

    def test_gradual_decline_then_stable(self):
        """缓慢下降后趋于平稳 -> 最终判定稳定。

        模拟真实场景：浇水后 raw 缓慢下降，最终趋于平稳。
        """
        c = cal.SoilCalibrator({
            "window_size": 10, "settle_delay_sec": 0,
            "stable_threshold": 15, "stable_confirm": 2,
            "alpha": 0.3,
        })
        # 先让 EMA 收敛到一个基线
        for _ in range(20):
            c.update_ema(6000.0)

        # 缓慢下降 30 步（每步 -2 ADC），然后平稳
        for i in range(30):
            v = 6000.0 - i * 2
            smoothed = c.update_ema(v)
            c.push_and_check(smoothed)

        # 平稳期
        is_stable = False
        for _ in range(15):
            smoothed = c.update_ema(5940.0)
            _, _, is_stable = c.push_and_check(smoothed)
            if is_stable:
                break
        self.assertTrue(is_stable, "下降趋平后应判定稳定")

    def test_constant_decline_never_stable(self):
        """持续匀速下降 -> 窗口极差始终超阈值 -> 不判稳定。"""
        c = cal.SoilCalibrator({
            "window_size": 10, "settle_delay_sec": 0,
            "stable_threshold": 15, "stable_confirm": 2,
            "alpha": 0.3,
        })
        for _ in range(20):
            c.update_ema(6000.0)

        is_stable = False
        for i in range(100):
            v = 6000.0 - i * 5  # 每步 -5 ADC，10 步窗口 range ≈ 50
            smoothed = c.update_ema(v)
            _, _, is_stable = c.push_and_check(smoothed)
            self.assertFalse(is_stable, f"步骤 {i}: 匀速下降不应判稳定")


# ==================== run_calibration 集成 ====================

class RunCalibrationTest(unittest.TestCase):
    """run_calibration 的端到端测试（用假 read_func）。"""

    def test_stable_after_settle_detects(self):
        """完整序列：浇水 -> 盲区 -> 稳定 -> 检测到稳定。"""
        readings = [6000.0] * 10       # 盲区期（settle=5 样本）
        readings += [5800.0] * 5       # 下降过渡
        readings += [5750.0] * 30      # 稳定在田间持水量

        idx = [0]

        def read_func():
            if idx[0] >= len(readings):
                return None
            v = readings[idx[0]]
            idx[0] += 1
            return v

        config = {
            "window_size": 5,
            "settle_delay_sec": 0.15,     # 15 个样本的盲区（覆盖平直+过渡）
            "sample_interval_sec": 0.01,
            "stable_threshold": 15,
            "stable_confirm": 2,
            "timeout_min": 5,
        }
        result = cal.run_calibration(read_func, config=config)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 5750.0, delta=50.0)

    def test_already_saturated_detects_quickly(self):
        """土壤已饱和（浇水后几乎不变）-> 盲区后立即稳定。"""
        readings = [5750.0] * 60  # 全程不变

        idx = [0]

        def read_func():
            if idx[0] >= len(readings):
                return None
            v = readings[idx[0]]
            idx[0] += 1
            return v

        config = {
            "window_size": 5,
            "settle_delay_sec": 0.03,     # 3 个样本
            "sample_interval_sec": 0.01,
            "stable_threshold": 18,
            "stable_confirm": 2,
            "timeout_min": 5,
        }
        result = cal.run_calibration(read_func, config=config)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 5750.0, delta=5.0)

    def test_glitch_filtered(self):
        """单个毛刺读数不应阻止校准成功。"""
        # 3 盲区 + 2 填满窗口(count=1) + 毛刺 + 5 稳定(count=2 -> STABLE)
        readings = [5750.0] * 3        # 盲区
        readings += [5750.0] * 2        # 填满窗口，count=1（未稳定）
        readings += [22612.0]           # 毛刺！应被过滤跳过
        readings += [5750.0] * 5        # 继续：count 达 2 -> 稳定

        idx = [0]

        def read_func():
            if idx[0] >= len(readings):
                return None
            v = readings[idx[0]]
            idx[0] += 1
            return v

        config = {
            "window_size": 5,
            "settle_delay_sec": 0.03,   # 3 个样本
            "sample_interval_sec": 0.01,
            "stable_threshold": 18,
            "stable_confirm": 2,
            "timeout_min": 5,
        }
        result = cal.run_calibration(read_func, config=config)
        self.assertIsNotNone(result, "毛刺应被过滤，校准应成功")
        self.assertAlmostEqual(result, 5750.0, delta=50.0)

    def test_constant_decline_times_out(self):
        """持续匀速下降（永不平稳）-> 超时返回 None。"""
        counter = [0]

        def read_func():
            counter[0] += 1
            return 6000.0 - counter[0] * 10  # 每步 -10 ADC

        config = {
            "window_size": 5,
            "settle_delay_sec": 0,
            "sample_interval_sec": 0.01,
            "stable_threshold": 15,
            "stable_confirm": 2,
            "timeout_min": 0.01,  # ~0.6 秒超时
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
            "settle_delay_sec": 0,
            "sample_interval_sec": 0.01,
            "timeout_min": 5,
        }
        result = cal.run_calibration(read_func, config=config)
        self.assertIsNone(result)
        self.assertGreaterEqual(calls[0], cal.MAX_READ_FAILURES)

    def test_slow_decline_then_stable_detects(self):
        """模拟真实浇水曲线：缓慢下降 -> 趋平 -> 稳定。"""
        readings = []
        # 缓慢下降 40 步（从浇水瞬间开始即下降，无平直段）
        for i in range(40):
            readings.append(5900.0 - i * 3)
        # 趋平
        readings += [5780.0] * 40

        idx = [0]

        def read_func():
            if idx[0] >= len(readings):
                return None
            v = readings[idx[0]]
            idx[0] += 1
            return v

        config = {
            "window_size": 10,
            "settle_delay_sec": 0.10,    # 10 个样本
            "sample_interval_sec": 0.01,
            "stable_threshold": 18,
            "stable_confirm": 2,
            "timeout_min": 5,
        }
        result = cal.run_calibration(read_func, config=config)
        self.assertIsNotNone(result, "缓慢下降趋平后应检测到稳定")
        self.assertAlmostEqual(result, 5780.0, delta=30.0)


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
