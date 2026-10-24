"""7天小时级历史数据聚合与 API 端点测试。"""

import importlib.util
import os
import pathlib
import tempfile
import threading
import unittest

import tests  # noqa: F401 — 加载 core 桩
import core.state as state

_spec = importlib.util.spec_from_file_location(
    "tests._real_core_database_7d",
    pathlib.Path(__file__).resolve().parent.parent / "core" / "database.py",
)
db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db)

from api.routers import get_history_data


class History7dTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        state.DB_FILE = self._tmp.name
        state.db_lock = threading.RLock()
        db.init_db()

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_query_7d_history_aggregates_hourly_and_excludes_old_or_anomalies(self):
        # 1. 插入 8 天前的记录（应被排除）
        with db.get_conn() as conn:
            conn.execute('''
                INSERT INTO node_data (node_id, temperature, humidity, soil_moisture, pressure, timestamp)
                VALUES ('main', 15.0, 40.0, 30.0, 1010.0, datetime('now', '-8 days'))
            ''')

            # 2. 插入 3 天前的两条正常记录（同一小时，应求均值）
            conn.execute('''
                INSERT INTO node_data (node_id, temperature, humidity, soil_moisture, pressure, timestamp)
                VALUES ('main', 20.0, 50.0, 40.0, 1012.0, datetime('now', '-3 days', 'start of day', '+10 hours', '+10 minutes'))
            ''')
            conn.execute('''
                INSERT INTO node_data (node_id, temperature, humidity, soil_moisture, pressure, timestamp)
                VALUES ('main', 22.0, 60.0, 42.0, 1014.0, datetime('now', '-3 days', 'start of day', '+10 hours', '+40 minutes'))
            ''')

            # 3. 插入 3 天前同一小时但被标记为异常的记录（应被忽略）
            conn.execute('''
                INSERT INTO node_data (node_id, temperature, humidity, soil_moisture, pressure, timestamp, is_anomaly)
                VALUES ('main', 99.0, 99.0, 99.0, 9999.0, datetime('now', '-3 days', 'start of day', '+10 hours', '+20 minutes'), 1)
            ''')

            # 4. 插入 3 天前同一小时的两条浇水记录（时长应求和 SUM）
            conn.execute('''
                INSERT INTO watering_log (node_id, duration, soil_before, timestamp)
                VALUES ('main', 0.8, 38.0, datetime('now', '-3 days', 'start of day', '+10 hours', '+15 minutes'))
            ''')
            conn.execute('''
                INSERT INTO watering_log (node_id, duration, soil_before, timestamp)
                VALUES ('main', 0.7, 39.0, datetime('now', '-3 days', 'start of day', '+10 hours', '+45 minutes'))
            ''')

        sensor_rows, water_rows = db.query_7d_history("main", days=7)
        self.assertEqual(len(sensor_rows), 1)
        # 验证温湿度土壤求平均
        s_bucket, s_temp, s_hum, s_soil, s_pres, s_epoch = sensor_rows[0]
        self.assertAlmostEqual(s_temp, 21.0)
        self.assertAlmostEqual(s_hum, 55.0)
        self.assertAlmostEqual(s_soil, 41.0)
        self.assertAlmostEqual(s_pres, 1013.0)

        # 验证浇水时长求和
        self.assertEqual(len(water_rows), 1)
        w_bucket, w_dur, w_soil_before, w_epoch = water_rows[0]
        self.assertAlmostEqual(w_dur, 1.5)
        self.assertEqual(s_bucket, w_bucket)

    def test_query_7d_metrics_max_fed_and_avg_others(self):
        with db.get_conn() as conn:
            # 连续指标 lux：100 和 200，平均为 150
            conn.execute('''
                INSERT INTO node_metrics (node_id, key, value, timestamp)
                VALUES ('main', 'lux', 100.0, datetime('now', '-2 days', 'start of day', '+8 hours', '+10 minutes'))
            ''')
            conn.execute('''
                INSERT INTO node_metrics (node_id, key, value, timestamp)
                VALUES ('main', 'lux', 200.0, datetime('now', '-2 days', 'start of day', '+8 hours', '+30 minutes'))
            ''')
            # 离散事件 fed：0 和 1，取 MAX 应为 1.0
            conn.execute('''
                INSERT INTO node_metrics (node_id, key, value, timestamp)
                VALUES ('main', 'fed', 0.0, datetime('now', '-2 days', 'start of day', '+8 hours', '+05 minutes'))
            ''')
            conn.execute('''
                INSERT INTO node_metrics (node_id, key, value, timestamp)
                VALUES ('main', 'fed', 1.0, datetime('now', '-2 days', 'start of day', '+8 hours', '+20 minutes'))
            ''')

        metrics = db.query_7d_metrics("main", days=7)
        metrics_dict = {key: val for _, key, val in metrics}
        self.assertAlmostEqual(metrics_dict['lux'], 150.0)
        self.assertEqual(metrics_dict['fed'], 1.0)

    def test_router_7d_endpoint_combines_timeline(self):
        # 存入一条数据，测试通过 routers.get_history_data 返回的格式
        with db.get_conn() as conn:
            conn.execute('''
                INSERT INTO node_data (node_id, temperature, humidity, soil_moisture, pressure, timestamp)
                VALUES ('main', 24.56, 65.43, 50.12, 1011.8, datetime('now', '-1 days', 'start of day', '+14 hours'))
            ''')
            conn.execute('''
                INSERT INTO node_metrics (node_id, key, value, timestamp)
                VALUES ('main', 'water_temp', 23.45, datetime('now', '-1 days', 'start of day', '+14 hours', '+05 minutes'))
            ''')
            conn.execute('''
                INSERT INTO watering_log (node_id, duration, soil_before, timestamp)
                VALUES ('main', 1.2, 48.0, datetime('now', '-1 days', 'start of day', '+14 hours', '+10 minutes'))
            ''')

        # 将真实的 db 函数绑定到 tests 装好的桩模块上，供 routers 模块调用
        import core.database as stub_db
        orig_history = getattr(stub_db, "query_7d_history", None)
        orig_metrics = getattr(stub_db, "query_7d_metrics", None)
        try:
            stub_db.query_7d_history = db.query_7d_history
            stub_db.query_7d_metrics = db.query_7d_metrics

            res = get_history_data(hist_type="7d", node_id="main")
            self.assertEqual(len(res), 1)
            point = res[0]
            # time 格式应为 MM-DD HH:00 (长度 11)
            self.assertEqual(len(point["time"]), 11)
            self.assertTrue(point["time"].endswith(":00"))
            self.assertEqual(point["temp"], 24.6)
            self.assertEqual(point["hum"], 65.4)
            self.assertEqual(point["soil"], 50.1)
            self.assertEqual(point["pressure"], 1011.8)
            self.assertEqual(point["water"], 1.2)
            self.assertEqual(point["extra"], {"water_temp": 23.45})
        finally:
            if orig_history is not None:
                stub_db.query_7d_history = orig_history
            if orig_metrics is not None:
                stub_db.query_7d_metrics = orig_metrics


if __name__ == "__main__":
    unittest.main()
