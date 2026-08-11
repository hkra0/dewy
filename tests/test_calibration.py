"""土壤校准算法的单元测试。

测试 hardware/soil_calibration.py 的纯算法逻辑（EMA、滑动窗口、稳定判定）
与持久化读写。该模块仅用标准库，无需 core 桩。

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


class SlidingWindowTest(unittest.TestCase):
    """滑动窗口：固定长度、首尾差值。"""

    def setUp(self):
        self.c = cal.SoilCalibrator({"window_size": 5})

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


class StabilityDetectionTest(unittest.TestCase):
    """稳定判定：连续 N 次 |Δ| < threshold。"""

    def setUp(self):
        # threshold=10, confirm=3, window_size=5
        self.c = cal.SoilCalibrator({
            "window_size": 5,
            "stable_threshold": 10.0,
            "stable_confirm": 3,
        })

    def test_three_consecutive_small_deltas_triggers_stable(self):
        # Fill window with stable values (delta < 10)
        stable_val = 7000.0
        for _ in range(5):
            self.c.push_and_check(stable_val)
        # Now push 3 more stable values; each delta ~0 < 10
        stable_hits = 0
        for _ in range(3):
            _, _, is_stable = self.c.push_and_check(stable_val)
            if is_stable:
                break
            stable_hits += 1
        # After window full (5) + 3 more = need 3 consecutive since window full
        # Actually: window fills at push 5. Then pushes 6,7,8 are the 3 consecutive.
        # But push_and_check already incremented stable_count from push 5.
        # Let's re-check: at push 5, delta=0 < 10, stable_count=1
        # push 6: delta=0, stable_count=2
        # push 7: delta=0, stable_count=3 -> is_stable=True
        # So we need pushes 5,6,7 to get stable.
        # The test above pushes 5 to fill, then 3 more (6,7,8).
        # At push 5: count=1, at push 6: count=2, at push 7: count=3 -> stable
        # So is_stable should be True at push 7, which is the 3rd extra push.
        # The loop breaks on first True.
        self.assertTrue(is_stable)

    def test_large_delta_resets_count(self):
        stable_val = 7000.0
        # Fill window
        for _ in range(5):
            self.c.push_and_check(stable_val)
        # stable_count should be 1 now
        self.assertEqual(self.c.stable_count, 1)

        # Push a large jump -> resets to 0
        _, _, is_stable = self.c.push_and_check(7100.0)
        self.assertEqual(self.c.stable_count, 0)
        self.assertFalse(is_stable)

    def test_threshold_boundary(self):
        """|Δ| exactly equal to threshold should NOT count as stable (strict <)."""
        self.c = cal.SoilCalibrator({
            "window_size": 3,
            "stable_threshold": 10.0,
            "stable_confirm": 1,
        })
        # Fill window: values 0, 5, 10 -> delta = 10-0 = 10, |10| < 10 is False
        for v in [0.0, 5.0, 10.0]:
            _, _, is_stable = self.c.push_and_check(v)
        self.assertFalse(is_stable)
        self.assertEqual(self.c.stable_count, 0)

    def test_just_below_threshold_counts(self):
        """|Δ| just below threshold should count."""
        self.c = cal.SoilCalibrator({
            "window_size": 3,
            "stable_threshold": 10.0,
            "stable_confirm": 1,
        })
        # values 0, 4.9, 9.9 -> delta = 9.9 - 0 = 9.9, |9.9| < 10 is True
        for v in [0.0, 4.9, 9.9]:
            _, _, is_stable = self.c.push_and_check(v)
        self.assertTrue(is_stable)


# ==================== run_calibration 集成 ====================

class RunCalibrationTest(unittest.TestCase):
    """run_calibration 的端到端测试（用假 read_func）。"""

    def test_detects_stable_plateau(self):
        """模拟排水曲线：先下降、后稳定，校准应返回稳定值。"""
        readings = list(range(8000, 7400, -20))  # 30 drops of 20 each (draining)
        readings += [7400.0] * 30                 # 30 stable readings

        idx = [0]

        def read_func():
            if idx[0] >= len(readings):
                return None
            v = readings[idx[0]]
            idx[0] += 1
            return v

        config = {
            "window_size": 10,
            "stable_threshold": 20.0,
            "stable_confirm": 3,
            "settle_delay_sec": 0,
            "sample_interval_sec": 0.01,
            "timeout_min": 5,
        }
        result = cal.run_calibration(read_func, config=config)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 7400.0, delta=5.0)

    def test_timeout_returns_none(self):
        """持续不稳定的输入应超时返回 None。"""
        counter = [0]

        def read_func():
            counter[0] += 1
            # Always changing, never stable
            return 7000.0 + counter[0] * 100

        config = {
            "window_size": 5,
            "stable_threshold": 10.0,
            "stable_confirm": 3,
            "settle_delay_sec": 0,
            "sample_interval_sec": 0.01,
            "timeout_min": 0.005,  # ~0.3 seconds timeout
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
            "window_size": 100,  # Never fills
            "stable_threshold": 1.0,
            "stable_confirm": 10,
            "settle_delay_sec": 0,
            "sample_interval_sec": 0.01,
            "timeout_min": 5,
        }

        # Start calibration in a thread
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
            "stable_threshold": 10.0,
            "stable_confirm": 3,
            "settle_delay_sec": 0,
            "sample_interval_sec": 0.01,
            "timeout_min": 5,
        }
        result = cal.run_calibration(read_func, config=config)
        self.assertIsNone(result)
        # Should have tried MAX_READ_FAILURES + some extra (loop checks failure count)
        self.assertGreaterEqual(calls[0], cal.MAX_READ_FAILURES)


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
        obj = hm._build_device("main", "传感器", "soil", {"driver": "Spy"})
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
        # 手动建一张老 schema 的表
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

        # init_db 应自动迁移
        db.init_db()

        with db.get_conn() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(node_data)")]
            self.assertIn("soil_adc_raw", cols)
            # 老数据保留，soil_adc_raw 为 NULL
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
        db.init_db()  # 二次运行
        db.init_db()  # 三次运行
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
