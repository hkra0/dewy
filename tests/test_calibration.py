"""土壤 ABC（自动基准校准）的单元测试。

测试 hardware/soil_calibration.py 的纯算法逻辑（百分位数、两级统计、
防错门控、EMA 融合）与持久化读写。该模块仅用标准库，无需 core 桩。

另测 hardware/manager.py 的 _build_device 注入元信息与 calibratable_sensors，
以及 core/logic/soil_abc.py 的编排逻辑（取数 -> 估计 -> 门控 -> 推送、
单个传感器失败隔离）。
"""

import importlib.util
import json
import os
import pathlib
import random
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# ---- 加载 soil_calibration（纯标准库模块，不需要 core 桩）----
_spec = importlib.util.spec_from_file_location(
    "tests._soil_calibration",
    pathlib.Path(__file__).resolve().parent.parent / "hardware" / "soil_calibration.py",
)
cal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cal)

import core.state as state  # 本包 __init__ 装好的桩

from hardware.manager import HardwareManager
from core.logic import soil_abc


# ==================== percentile ====================

class PercentileTest(unittest.TestCase):

    def test_single_value_returns_itself(self):
        self.assertEqual(cal.percentile([42.0], 0.05), 42.0)

    def test_q_zero_is_min(self):
        self.assertEqual(cal.percentile([1.0, 2.0, 3.0, 4.0], 0.0), 1.0)

    def test_q_one_is_max(self):
        self.assertEqual(cal.percentile([1.0, 2.0, 3.0, 4.0], 1.0), 4.0)

    def test_two_values_median(self):
        self.assertAlmostEqual(cal.percentile([10.0, 20.0], 0.5), 15.0)

    def test_linear_interpolation(self):
        # k = 0.05 * (5-1) = 0.2 -> 10*(1-0.2) + 20*0.2 = 12.0
        self.assertAlmostEqual(
            cal.percentile([10.0, 20.0, 30.0, 40.0, 50.0], 0.05), 12.0)


# ==================== field_capacity_estimate（两级统计） ====================

def _synthetic_series(watering_interval_days, total_days=30, samples_per_day=144,
                       wet_base=6000.0, dry_rate=80.0, noise=5.0, seed=42):
    """模拟固定间隔浇水下的 ADC 读数：浇水当天最湿，此后按天线性变干直到下次浇水。"""
    rng = random.Random(seed)
    day_values = []
    for day in range(total_days):
        days_since_water = day % watering_interval_days
        center = wet_base + days_since_water * dry_rate
        date_str = f"d{day:02d}"
        for _ in range(samples_per_day):
            day_values.append((date_str, center + rng.uniform(-noise, noise)))
    return day_values


class FieldCapacityEstimateTest(unittest.TestCase):

    def test_insufficient_days_returns_none(self):
        day_values = [(f"d{d}", 6000.0) for d in range(5) for _ in range(200)]
        estimate, valid_days, total = cal.field_capacity_estimate(day_values)
        self.assertIsNone(estimate)
        self.assertEqual(valid_days, 5)
        self.assertEqual(total, 1000)

    def test_insufficient_samples_returns_none(self):
        day_values = [(f"d{d}", 6000.0) for d in range(10) for _ in range(10)]
        estimate, valid_days, total = cal.field_capacity_estimate(day_values)
        self.assertIsNone(estimate)
        self.assertEqual(valid_days, 10)
        self.assertEqual(total, 100)

    def test_none_values_are_ignored(self):
        day_values = [(f"d{d}", None) for d in range(10) for _ in range(60)]
        estimate, valid_days, total = cal.field_capacity_estimate(day_values)
        self.assertIsNone(estimate)
        self.assertEqual(valid_days, 0)
        self.assertEqual(total, 0)

    def test_sufficient_data_returns_estimate(self):
        day_values = [(f"d{d}", 6000.0 + (d % 5)) for d in range(10) for _ in range(60)]
        estimate, valid_days, total = cal.field_capacity_estimate(day_values)
        self.assertIsNotNone(estimate)
        self.assertEqual(valid_days, 10)
        self.assertEqual(total, 600)

    def test_intra_day_glitch_filtered(self):
        """单日内一次性瞬时积水异常低值不应拉低该日的代表值。"""
        day_values = []
        for d in range(10):
            date = f"d{d}"
            day_values += [(date, 6000.0)] * 143
            day_values.append((date, 1000.0))  # 单个毛刺
        estimate, _, _ = cal.field_capacity_estimate(day_values)
        self.assertAlmostEqual(estimate, 6000.0, delta=5.0)

    def test_cross_day_p10_bounds_single_anomalous_day_influence(self):
        """跨日 P10 不等同于直接取每日代表值的最小值——
        单个异常日（如传感器故障当天）不应单独定义估计结果。"""
        rng = random.Random(1)
        day_values = []
        for d in range(29):
            for _ in range(144):
                day_values.append((f"d{d:02d}", 6200.0 + rng.uniform(-5, 5)))
        # 第 30 天传感器故障，整天读数异常偏低（远超真实生理变化范围）
        day_values += [("d29", 3000.0)] * 144

        estimate, _, _ = cal.field_capacity_estimate(day_values)
        self.assertIsNotNone(estimate)
        self.assertGreater(estimate, 5000.0, "不应被单日故障拖到 3000 附近")
        self.assertAlmostEqual(estimate, 6200.0, delta=50.0)

    def test_estimate_stable_across_watering_intervals(self):
        """浇水间隔从 4 天到 15 天变化时，两级统计给出的候选值应保持接近，
        不因窗口期内浇水次数不同而系统性偏移。"""
        frequent = _synthetic_series(watering_interval_days=4)
        sparse = _synthetic_series(watering_interval_days=15)

        est_frequent, _, _ = cal.field_capacity_estimate(frequent)
        est_sparse, _, _ = cal.field_capacity_estimate(sparse)

        self.assertIsNotNone(est_frequent)
        self.assertIsNotNone(est_sparse)
        self.assertAlmostEqual(est_frequent, 6000.0, delta=100.0)
        self.assertLess(abs(est_frequent - est_sparse), 150.0)


# ==================== evaluate_update（防错门控 + EMA） ====================

class EvaluateUpdateTest(unittest.TestCase):

    def test_accepts_within_bounds_and_blends_ema(self):
        new_val, reason = cal.evaluate_update(6883.0, 6883.0, 17545.0, 7000.0)
        self.assertIsNone(reason)
        self.assertAlmostEqual(new_val, round(0.2 * 7000.0 + 0.8 * 6883.0, 1))

    def test_rejects_when_candidate_is_none(self):
        new_val, reason = cal.evaluate_update(6883.0, 6883.0, 17545.0, None)
        self.assertIsNone(new_val)
        self.assertIn("样本不足", reason)

    def test_rejects_excessive_single_step_drift(self):
        candidate = 6883.0 * 1.30  # 30% 漂移，超过默认 15% 阈值
        new_val, reason = cal.evaluate_update(6883.0, 6883.0, 17545.0, candidate)
        self.assertIsNone(new_val)
        self.assertIn("漂移", reason)

    def test_rejects_outside_absolute_factory_bound(self):
        """单步漂移不大，但候选值相对出厂值的累积偏移超出绝对夹紧范围。"""
        factory = 6883.0
        old = 8500.0     # 假设已经历过几次同方向的小步漂移
        candidate = 9000.0  # 相对 old 仅漂移 5.9%，但相对 factory 已超 30%
        new_val, reason = cal.evaluate_update(old, factory, 17545.0, candidate)
        self.assertIsNone(new_val)
        self.assertIn("出厂值", reason)

    def test_rejects_candidate_too_close_to_val_air(self):
        val_air = 17545.0
        factory = 15000.0
        old = 15750.0
        candidate = 15000.0  # 仅比 VAL_AIR 低 14.5%，低于 20% 安全余量
        new_val, reason = cal.evaluate_update(old, factory, val_air, candidate)
        self.assertIsNone(new_val)
        self.assertIn("VAL_AIR", reason)

    def test_custom_max_drift_ratio_is_respected(self):
        candidate = 6883.0 * 1.10  # 10% 漂移
        rejected, _ = cal.evaluate_update(6883.0, 6883.0, 17545.0, candidate,
                                           max_drift_ratio=0.05)
        accepted, reason = cal.evaluate_update(6883.0, 6883.0, 17545.0, candidate,
                                                max_drift_ratio=0.15)
        self.assertIsNone(rejected)
        self.assertIsNotNone(accepted)
        self.assertIsNone(reason)


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
    """_build_device 注入元信息、calibratable_sensors 鸭子类型筛选。"""

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

    def test_calibratable_sensors_returns_matching_sensors(self):
        """只返回同时实现了 calibration_state 与 apply_calibration 的传感器。"""
        class SoilSensor:
            def calibration_state(self):
                return {}

            def apply_calibration(self, val):
                return True

        class OtherSensor:
            pass  # 无校准接口，应被排除

        hm = self._manager()
        soil = SoilSensor()
        other = OtherSensor()
        hm.local_sensors = {"main": {"soil": soil, "sht30": other}}

        self.assertEqual(hm.calibratable_sensors("main"), {"soil": soil})

    def test_calibratable_sensors_unknown_node_returns_empty(self):
        hm = self._manager()
        hm.local_sensors = {}
        self.assertEqual(hm.calibratable_sensors("nonexistent"), {})

    def test_calibratable_sensors_requires_both_methods(self):
        """只实现其中一个方法的传感器不算可校准。"""
        class PartialSensor:
            def calibration_state(self):
                return {}
            # 缺少 apply_calibration

        hm = self._manager()
        hm.local_sensors = {"main": {"partial": PartialSensor()}}
        self.assertEqual(hm.calibratable_sensors("main"), {})


# ==================== core/logic/soil_abc.py 编排 ====================

class ABCOrchestrationTest(unittest.TestCase):
    """run_abc_calibration：取数 -> 估计 -> 门控 -> 推送，单个传感器失败隔离。

    enabled / window_days / max_drift_ratio 是全局用户配置
    （`core.config.global_config["soil_calibration"]`），不再是传感器实例的
    属性——`calibration_state()` 现在只报告 val_water / val_air /
    factory_val_water（见 hardware/drivers/ads1115.py 的同名方法）。
    """

    DEFAULT_CFG = {"enabled": True, "window_days": 30, "max_drift_ratio": 0.15}

    @staticmethod
    def _sensor(val_water=6883.0, val_air=17545.0, factory=None):
        sensor = MagicMock()
        sensor.calibration_state.return_value = {
            "val_water": val_water,
            "val_air": val_air,
            "factory_val_water": factory if factory is not None else val_water,
        }
        sensor.apply_calibration.return_value = True
        return sensor

    @staticmethod
    def _day_values(center, days=10, samples_per_day=60):
        return [(f"d{d}", center) for d in range(days) for _ in range(samples_per_day)]

    def _run_with(self, sensors, day_values, calib_cfg=None):
        hm = MagicMock(local_sensors={"main": {}},
                        calibratable_sensors=lambda node_id: sensors)
        cfg = {"soil_calibration": calib_cfg or self.DEFAULT_CFG}
        with patch.object(soil_abc.state, "hardware_manager", hm), \
             patch.object(soil_abc.db, "query_soil_adc_series", return_value=day_values), \
             patch.dict(soil_abc.config.global_config, cfg, clear=False):
            soil_abc.run_abc_calibration()

    def test_globally_disabled_skips_before_touching_any_sensor(self):
        """enabled=False 时整轮直接跳过，连 calibration_state() 都不该调用。"""
        sensor = self._sensor()
        self._run_with({"soil": sensor}, self._day_values(7000.0),
                        calib_cfg={"enabled": False, "window_days": 30, "max_drift_ratio": 0.15})
        sensor.calibration_state.assert_not_called()
        sensor.apply_calibration.assert_not_called()

    def test_enabled_missing_from_config_defaults_to_on(self):
        """soil_calibration 段缺失（老配置升级前）时默认按启用处理。"""
        sensor = self._sensor(val_water=6883.0, factory=6883.0)
        self._run_with({"soil": sensor}, self._day_values(7000.0), calib_cfg={})
        sensor.apply_calibration.assert_called_once()

    def test_insufficient_data_skips_update(self):
        sensor = self._sensor()
        self._run_with({"soil": sensor}, [])
        sensor.apply_calibration.assert_not_called()

    def test_accepted_candidate_applies_calibration(self):
        sensor = self._sensor(val_water=6883.0, factory=6883.0)
        self._run_with({"soil": sensor}, self._day_values(7000.0))
        sensor.apply_calibration.assert_called_once()
        new_val = sensor.apply_calibration.call_args[0][0]
        self.assertAlmostEqual(new_val, round(0.2 * 7000.0 + 0.8 * 6883.0, 1))

    def test_excessive_drift_rejects_update(self):
        sensor = self._sensor(val_water=6883.0, factory=6883.0)
        self._run_with({"soil": sensor}, self._day_values(9000.0))  # >15% 漂移
        sensor.apply_calibration.assert_not_called()

    def test_custom_window_days_is_forwarded_to_the_query(self):
        sensor = self._sensor(val_water=6883.0, factory=6883.0)
        with patch.object(soil_abc.state, "hardware_manager", MagicMock(
                local_sensors={"main": {}}, calibratable_sensors=lambda n: {"soil": sensor})), \
             patch.object(soil_abc.db, "query_soil_adc_series",
                           return_value=self._day_values(7000.0)) as query, \
             patch.dict(soil_abc.config.global_config,
                        {"soil_calibration": {"enabled": True, "window_days": 45, "max_drift_ratio": 0.15}},
                        clear=False):
            soil_abc.run_abc_calibration()
        query.assert_called_once_with("main", days=45)

    def test_one_sensor_failure_does_not_block_others(self):
        good = self._sensor(val_water=6883.0, factory=6883.0)
        bad = MagicMock()
        bad.calibration_state.side_effect = RuntimeError("I2C error")

        self._run_with({"bad": bad, "good": good}, self._day_values(7000.0))
        good.apply_calibration.assert_called_once()


# ==================== 数据库 schema 迁移 ====================

class DatabaseMigrationTest(unittest.TestCase):
    """soil_adc_raw 列的自动迁移：老库 ALTER TABLE、新库直接建、幂等。"""

    def setUp(self):
        import threading
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

    def test_query_soil_adc_series_excludes_anomalies_and_nulls(self):
        """query_soil_adc_series 排除 is_anomaly=1 与 soil_adc_raw IS NULL 的行。"""
        db = self._load_real_db()
        db.init_db()
        db.insert_node_data([
            {"node_id": "main", "soil_adc_raw": 6000.0},
            {"node_id": "main", "soil_adc_raw": 6100.0},
            {"node_id": "main"},  # soil_adc_raw NULL，应被排除
        ])
        with db.get_conn() as conn:
            conn.execute("UPDATE node_data SET is_anomaly = 1 WHERE soil_adc_raw = 6100.0")

        rows = db.query_soil_adc_series("main", days=30)
        values = [v for _, v in rows]
        self.assertEqual(values, [6000.0])


if __name__ == "__main__":
    unittest.main()
