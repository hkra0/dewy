"""core.logic.watering.clean_soil_anomalies —— 浇水后土壤突刺的标记逻辑。

rows 的形态与 db.query_recent_soil 一致：[(id, soil_moisture), ...]，
按 id 倒序，即 rows[0] 是最新一条。
"""

import unittest
from unittest.mock import patch

from core.logic import watering

NODE = "node-a"


class CleanSoilAnomaliesTest(unittest.TestCase):

    def run_with(self, rows):
        """用给定读数跑一次，返回被标记的 id 列表；未调用标记时返回 None。"""
        with patch.object(watering.db, "query_recent_soil", return_value=rows), \
             patch.object(watering.db, "mark_anomalies") as mark:
            watering.clean_soil_anomalies(NODE)
        return mark.call_args[0][0] if mark.called else None

    def test_too_few_rows_does_nothing(self):
        self.assertIsNone(self.run_with([(2, 40), (1, 38)]))

    def test_no_jump_does_nothing(self):
        # 最新读数只比上一条高 2，没到 >10 的突刺门槛
        self.assertIsNone(self.run_with([(3, 40), (2, 38), (1, 37)]))

    def test_single_dip_is_marked(self):
        # 40 → 5 → 38：中间那条是浇水瞬间的假低值
        self.assertEqual(self.run_with([(3, 38), (2, 5), (1, 40)]), [2])

    def test_two_consecutive_dips_are_marked(self):
        self.assertEqual(self.run_with([(4, 38), (3, 5), (2, 4), (1, 40)]), [3, 2])

    def test_three_consecutive_dips_are_marked(self):
        self.assertEqual(self.run_with([(5, 38), (4, 5), (3, 4), (2, 3), (1, 40)]), [4, 3, 2])

    def test_dip_longer_than_the_window_marks_nothing(self):
        # 四条连续低值超出可识别范围，没有分支命中，标记空列表
        rows = [(5, 38), (4, 5), (3, 4), (2, 3), (1, 2)]
        self.assertEqual(self.run_with(rows), [])

    def test_gradual_recovery_is_not_an_anomaly(self):
        # 上一条并不低（>=10），只是正常回升，不该被标记
        self.assertEqual(self.run_with([(3, 40), (2, 25), (1, 24)]), [])

    def test_none_readings_are_ignored(self):
        self.assertIsNone(self.run_with([(3, None), (2, 5), (1, 40)]))
        self.assertIsNone(self.run_with([(3, 38), (2, None), (1, 40)]))

    def test_none_before_the_dip_marks_nothing(self):
        # rows[2] 缺值时无法确认这是突刺，保持不标记
        self.assertEqual(self.run_with([(3, 38), (2, 5), (1, None)]), [])

    def test_boundary_jump_of_exactly_ten_is_not_an_anomaly(self):
        # 判定是严格大于 10
        self.assertIsNone(self.run_with([(3, 15), (2, 5), (1, 40)]))

    def test_dip_value_at_the_low_threshold_is_not_marked(self):
        # 分支要求 last_soil < 10，正好 10 不算
        self.assertEqual(self.run_with([(3, 38), (2, 10), (1, 40)]), [])


if __name__ == "__main__":
    unittest.main()
