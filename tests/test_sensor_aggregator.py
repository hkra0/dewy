import threading
import unittest

from core.logic.sensor_aggregator import SensorAggregator, _trimmed_mean


class TestSensorAggregator(unittest.TestCase):
    def setUp(self):
        self.agg = SensorAggregator()

    def test_trimmed_mean_calculation(self):
        # 样本数少于 4 时直接算术平均
        self.assertIsNone(_trimmed_mean([]))
        self.assertEqual(_trimmed_mean([25.0]), 25.0)
        self.assertAlmostEqual(_trimmed_mean([20.0, 30.0]), 25.0)
        self.assertAlmostEqual(_trimmed_mean([10.0, 20.0, 30.0]), 20.0)

        # 样本数 >= 4 时剔除最高与最低极值
        # [0, 25, 25, 25, 25, 25, 25, 100] -> 掐头去尾剔除 0 和 100，剩余均值 25.0
        data = [0.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 100.0]
        self.assertAlmostEqual(_trimmed_mean(data), 25.0)

    def test_record_and_window_summary(self):
        # 模拟 10 分钟内上报 6 次温度和湿度
        temps = [26.0, 26.2, 35.0, 26.1, 15.0, 26.3]  # 35 和 15 是极值
        for t in temps:
            self.agg.record_sample("aqua", {"temperature": t, "humidity": 60.0})

        summary = self.agg.get_window_summary("aqua", {"node_id": "aqua", "temperature": 26.3})
        # 剔除 15 和 35 后，[26.0, 26.1, 26.2, 26.3] 均值约为 26.15
        self.assertAlmostEqual(summary["temperature"], 26.15, places=2)
        self.assertEqual(summary["humidity"], 60.0)
        self.assertEqual(summary["node_id"], "aqua")

    def test_fallback_when_no_samples(self):
        # 窗口内无样本时，使用快照兜底
        summary = self.agg.get_window_summary("offline_node", {"temperature": 22.5, "status": "ok"})
        self.assertEqual(summary["temperature"], 22.5)
        self.assertEqual(summary["status"], "ok")

    def test_discrete_and_boolean_state(self):
        self.agg.record_sample("aqua", {"temperature": 25.0, "fed": 1, "fed_time": "08:30"})
        self.agg.record_sample("aqua", {"temperature": 25.2, "fed": 1, "fed_time": "08:30"})

        summary = self.agg.get_window_summary("aqua")
        self.assertEqual(summary["fed"], 1)
        self.assertEqual(summary["fed_time"], "08:30")
        self.assertAlmostEqual(summary["temperature"], 25.1)

    def test_window_reset(self):
        self.agg.record_sample("node1", {"temperature": 20.0})
        self.agg.record_sample("node2", {"temperature": 30.0})

        # 只重置 node1
        self.agg.reset_window("node1")
        s1 = self.agg.get_window_summary("node1", {"temperature": 0.0})
        s2 = self.agg.get_window_summary("node2")
        self.assertEqual(s1["temperature"], 0.0)  # 回退到 fallback
        self.assertEqual(s2["temperature"], 30.0)

        # 重置全部
        self.agg.reset_window()
        s2_after = self.agg.get_window_summary("node2", {"temperature": 99.0})
        self.assertEqual(s2_after["temperature"], 99.0)

    def test_thread_safety(self):
        # 多线程并发写入
        def worker():
            for i in range(50):
                self.agg.record_sample("test", {"temperature": 25.0 + i * 0.01})

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        summary = self.agg.get_window_summary("test")
        self.assertIn("temperature", summary)
        self.assertGreater(summary["temperature"], 24.0)


if __name__ == "__main__":
    unittest.main()
