"""core.logic.light.compute_next_boundary —— 手动覆盖的失效时刻。"""

import unittest
from datetime import datetime

from core.logic.light import compute_next_boundary

ON = 7 * 60 + 30    # 07:30
OFF = 21 * 60 + 30  # 21:30


class ComputeNextBoundaryTest(unittest.TestCase):

    def test_before_both_boundaries_returns_todays_on_time(self):
        now = datetime(2026, 8, 2, 6, 0)
        self.assertEqual(compute_next_boundary(now, ON, OFF), datetime(2026, 8, 2, 7, 30))

    def test_between_boundaries_returns_todays_off_time(self):
        now = datetime(2026, 8, 2, 12, 0)
        self.assertEqual(compute_next_boundary(now, ON, OFF), datetime(2026, 8, 2, 21, 30))

    def test_after_both_boundaries_rolls_over_to_tomorrow(self):
        now = datetime(2026, 8, 2, 23, 0)
        self.assertEqual(compute_next_boundary(now, ON, OFF), datetime(2026, 8, 3, 7, 30))

    def test_rollover_crosses_month_end(self):
        now = datetime(2026, 8, 31, 23, 59)
        self.assertEqual(compute_next_boundary(now, ON, OFF), datetime(2026, 9, 1, 7, 30))

    def test_rollover_crosses_year_end(self):
        now = datetime(2026, 12, 31, 22, 0)
        self.assertEqual(compute_next_boundary(now, ON, OFF), datetime(2027, 1, 1, 7, 30))

    def test_exactly_on_a_boundary_skips_to_the_next_one(self):
        # 边界判定是严格大于（b > current_minutes），正处在开灯分钟上时
        # 该边界已经过去，覆盖应持续到关灯那一刻。
        now = datetime(2026, 8, 2, 7, 30)
        self.assertEqual(compute_next_boundary(now, ON, OFF), datetime(2026, 8, 2, 21, 30))

    def test_seconds_and_microseconds_are_zeroed(self):
        now = datetime(2026, 8, 2, 6, 0, 42, 123456)
        result = compute_next_boundary(now, ON, OFF)
        self.assertEqual((result.second, result.microsecond), (0, 0))

    def test_argument_order_does_not_matter(self):
        # 函数对两个边界排序后取用，跨午夜配置（先关后开）走同一条路径
        now = datetime(2026, 8, 2, 12, 0)
        self.assertEqual(compute_next_boundary(now, ON, OFF),
                         compute_next_boundary(now, OFF, ON))

    def test_overnight_schedule_after_lights_on(self):
        # 21:30 开、07:30 关的越冬补光配置：23:00 手动切灯持续到次日 07:30
        now = datetime(2026, 8, 2, 23, 0)
        self.assertEqual(compute_next_boundary(now, OFF, ON), datetime(2026, 8, 3, 7, 30))

    def test_identical_boundaries_still_return_a_future_time(self):
        # 配置错误导致开关同一时刻时不应返回过去的时间，否则覆盖立即失效
        now = datetime(2026, 8, 2, 12, 0)
        result = compute_next_boundary(now, ON, ON)
        self.assertEqual(result, datetime(2026, 8, 3, 7, 30))
        self.assertGreater(result, now)

    def test_result_is_always_in_the_future(self):
        for hour in range(24):
            for minute in (0, 29, 30, 31, 59):
                now = datetime(2026, 8, 2, hour, minute)
                with self.subTest(hour=hour, minute=minute):
                    self.assertGreater(compute_next_boundary(now, ON, OFF), now)


if __name__ == "__main__":
    unittest.main()
