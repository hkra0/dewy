"""每日温度分位数平滑密度带与 API 端点测试。"""

import importlib.util
import os
import pathlib
import tempfile
import threading
import unittest

import tests  # noqa: F401 — 加载 core 桩
import core.state as state

_spec = importlib.util.spec_from_file_location(
    "tests._real_core_database_daily_density",
    pathlib.Path(__file__).resolve().parent.parent / "core" / "database.py",
)
db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db)

from api.routers import get_history_data


class DailyTempDensityTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        state.DB_FILE = self._tmp.name
        state.db_lock = threading.RLock()
        db.init_db()

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_query_daily_temp_distribution_percentiles_and_filtering(self):
        with db.get_conn() as conn:
            # 1. 插入 35 天前的数据（超过默认 30 天窗口，应被排除）
            conn.execute('''
                INSERT INTO node_data (node_id, temperature, timestamp)
                VALUES ('main', 10.0, datetime('now', '-35 days'))
            ''')

            # 2. 插入 2 天前某日的 5 条有效数据：10.0, 20.0, 30.0, 40.0, 50.0
            # min=10.0, max=50.0
            # 线性插值分位数:
            # p25: k = 0.25 * 4 = 1.0 -> 20.0
            # p75: k = 0.75 * 4 = 3.0 -> 40.0
            for t, m in [(10.0, 10), (20.0, 20), (30.0, 30), (40.0, 40), (50.0, 50)]:
                conn.execute(f'''
                    INSERT INTO node_data (node_id, temperature, timestamp)
                    VALUES ('main', {t}, datetime('now', '-2 days', 'start of day', '+{m} minutes'))
                ''')

            # 3. 插入 2 天前带有 is_anomaly = 1 的异常记录（应被排除）
            conn.execute('''
                INSERT INTO node_data (node_id, temperature, timestamp, is_anomaly)
                VALUES ('main', 999.0, datetime('now', '-2 days', 'start of day', '+12 hours'), 1)
            ''')

            # 4. 插入 1 天前仅有 1 条采样的数据（边界测试：单点 min=p25=p75=max）
            conn.execute('''
                INSERT INTO node_data (node_id, temperature, timestamp)
                VALUES ('main', 25.5, datetime('now', '-1 days', 'start of day', '+12 hours'))
            ''')

        res = db.query_daily_temp_distribution("main", limit=30)
        self.assertEqual(len(res), 2)

        # 检查 2 天前的分位数
        day2_key = list(res.keys())[0]
        day2_dist = res[day2_key]
        self.assertAlmostEqual(day2_dist["min"], 10.0)
        self.assertAlmostEqual(day2_dist["p25"], 20.0)
        self.assertAlmostEqual(day2_dist["p75"], 40.0)
        self.assertAlmostEqual(day2_dist["max"], 50.0)

        # 检查 1 天前的单点边界
        day1_key = list(res.keys())[1]
        day1_dist = res[day1_key]
        self.assertAlmostEqual(day1_dist["min"], 25.5)
        self.assertAlmostEqual(day1_dist["p25"], 25.5)
        self.assertAlmostEqual(day1_dist["p75"], 25.5)
        self.assertAlmostEqual(day1_dist["max"], 25.5)

    def test_router_daily_includes_temp_dist(self):
        with db.get_conn() as conn:
            conn.execute('''
                INSERT INTO node_data (node_id, temperature, humidity, soil_moisture, pressure, timestamp)
                VALUES ('main', 20.0, 50.0, 40.0, 1012.0, datetime('now', '-1 days', 'start of day', '+10 hours'))
            ''')
            conn.execute('''
                INSERT INTO node_data (node_id, temperature, humidity, soil_moisture, pressure, timestamp)
                VALUES ('main', 30.0, 60.0, 42.0, 1014.0, datetime('now', '-1 days', 'start of day', '+14 hours'))
            ''')

        import core.database as stub_db
        orig_daily = getattr(stub_db, "query_daily_history", None)
        orig_metrics = getattr(stub_db, "query_daily_metrics", None)
        orig_dist = getattr(stub_db, "query_daily_temp_distribution", None)
        try:
            stub_db.query_daily_history = db.query_daily_history
            stub_db.query_daily_metrics = db.query_daily_metrics
            stub_db.query_daily_temp_distribution = db.query_daily_temp_distribution

            res = get_history_data(hist_type="daily", node_id="main")
            self.assertEqual(len(res), 1)
            item = res[0]
            self.assertEqual(item["temp"], 25.0)
            self.assertIsNotNone(item["temp_dist"])
            self.assertEqual(item["temp_dist"]["min"], 20.0)
            self.assertEqual(item["temp_dist"]["max"], 30.0)
            self.assertAlmostEqual(item["temp_dist"]["p25"], 22.5)
            self.assertAlmostEqual(item["temp_dist"]["p75"], 27.5)
        finally:
            if orig_daily is not None:
                stub_db.query_daily_history = orig_daily
            if orig_metrics is not None:
                stub_db.query_daily_metrics = orig_metrics
            if orig_dist is not None:
                stub_db.query_daily_temp_distribution = orig_dist


if __name__ == "__main__":
    unittest.main()
