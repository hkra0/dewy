"""node_metrics —— node_data 固定列之外的测量量。

保证「装一个 schema 里没有的传感器」时数据不会被静默丢弃。
"""

import importlib.util
import os
import pathlib
import tempfile
import threading
import unittest

import core.state as state  # 本包 __init__ 装好的桩

# 这里要测的正是 core/database.py 本身，不能用桩。绕开 sys.modules 里的桩
# 单独加载一份真实模块——它内部 import 到的 core.state 仍是桩，
# 而它只用到桩的 DB_FILE 与 db_lock 两个属性，下面各给一个真值。
_spec = importlib.util.spec_from_file_location(
    "tests._real_core_database",
    pathlib.Path(__file__).resolve().parent.parent / "core" / "database.py",
)
db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db)


class NodeMetricsTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        state.DB_FILE = self._tmp.name
        state.db_lock = threading.RLock()
        db.init_db()

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_known_fields_go_to_node_data(self):
        db.insert_node_data([{"node_id": "main", "temperature": 21.5, "humidity": 60.0}])
        rows = db.query("SELECT temperature, humidity FROM node_data")
        self.assertEqual(rows, [(21.5, 60.0)])
        self.assertEqual(db.query_metric_keys("main"), [])

    def test_unknown_field_is_kept_as_a_metric(self):
        # BH1750 返回 illuminance，node_data 里没有这一列——旧实现会丢掉它
        db.insert_node_data([{"node_id": "main", "temperature": 21.5, "illuminance": 340.0}])
        self.assertEqual(db.query_metric_keys("main"), ["illuminance"])
        self.assertEqual(db.query_latest_metrics("main"), {"illuminance": 340.0})

    def test_metrics_are_scoped_per_node(self):
        db.insert_node_data([
            {"node_id": "main", "co2": 800},
            {"node_id": "sub1", "ec": 1.2},
        ])
        self.assertEqual(db.query_metric_keys("main"), ["co2"])
        self.assertEqual(db.query_metric_keys("sub1"), ["ec"])

    def test_latest_metrics_returns_the_newest_value_per_key(self):
        db.insert_node_data([{"node_id": "main", "co2": 800}])
        db.insert_node_data([{"node_id": "main", "co2": 950}])
        self.assertEqual(db.query_latest_metrics("main"), {"co2": 950.0})

    def test_non_numeric_and_none_values_are_skipped(self):
        # 驱动返回状态字符串是常见写法，塞进 REAL 列没有意义
        db.insert_node_data([{"node_id": "main", "status": "ok", "fw": None, "flag": True}])
        self.assertEqual(db.query_metric_keys("main"), [])

    def test_history_returns_points_in_chronological_order(self):
        for v in (1.0, 2.0, 3.0):
            db.insert_node_data([{"node_id": "main", "co2": v}])
        values = [v for _, v in db.query_metric_history("main", "co2")]
        self.assertEqual(values, [1.0, 2.0, 3.0])

    def test_history_of_unknown_key_is_empty(self):
        db.insert_node_data([{"node_id": "main", "co2": 800}])
        self.assertEqual(db.query_metric_history("main", "nope"), [])

    def test_both_tables_are_written_in_one_call(self):
        db.insert_node_data([{"node_id": "main", "temperature": 20.0, "co2": 800}])
        self.assertEqual(db.query("SELECT COUNT(*) FROM node_data")[0][0], 1)
        self.assertEqual(db.query("SELECT COUNT(*) FROM node_metrics")[0][0], 1)

    def test_prune_clears_expired_metric_rows(self):
        db.insert_node_data([{"node_id": "main", "co2": 800}])
        db.execute("UPDATE node_metrics SET timestamp = datetime('now', '-400 days')")
        db.execute("UPDATE node_data SET timestamp = datetime('now', '-400 days')")
        db.prune_node_data(retention_days=365)
        self.assertEqual(db.query("SELECT COUNT(*) FROM node_metrics")[0][0], 0)

    def test_prune_keeps_recent_metric_rows(self):
        db.insert_node_data([{"node_id": "main", "co2": 800}])
        db.prune_node_data(retention_days=365)
        self.assertEqual(db.query("SELECT COUNT(*) FROM node_metrics")[0][0], 1)

    def test_24h_metrics_are_bucketed_by_time(self):
        db.insert_node_data([{"node_id": "main", "co2": 800, "illuminance": 300.0}])
        rows = db.query_24h_metrics("main")
        self.assertEqual({(k, v) for _, k, v in rows}, {("co2", 800.0), ("illuminance", 300.0)})

    def test_24h_metrics_exclude_older_rows(self):
        db.insert_node_data([{"node_id": "main", "co2": 800}])
        db.execute("UPDATE node_metrics SET timestamp = datetime('now', '-2 days')")
        self.assertEqual(db.query_24h_metrics("main"), [])

    def test_daily_metrics_average_per_day(self):
        db.insert_node_data([{"node_id": "main", "co2": 800}])
        db.insert_node_data([{"node_id": "main", "co2": 1000}])
        rows = db.query_daily_metrics("main")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "co2")
        self.assertAlmostEqual(rows[0][2], 900.0)

    def test_daily_metrics_respect_the_window(self):
        db.insert_node_data([{"node_id": "main", "co2": 800}])
        db.execute("UPDATE node_metrics SET timestamp = datetime('now', '-40 days')")
        self.assertEqual(db.query_daily_metrics("main", days=30), [])

    def test_metric_queries_are_scoped_per_node(self):
        db.insert_node_data([{"node_id": "sub1", "co2": 800}])
        self.assertEqual(db.query_24h_metrics("main"), [])
        self.assertEqual(len(db.query_24h_metrics("sub1")), 1)

    def test_empty_records_is_a_noop(self):
        db.insert_node_data([])
        self.assertEqual(db.query("SELECT COUNT(*) FROM node_data")[0][0], 0)


if __name__ == "__main__":
    unittest.main()
