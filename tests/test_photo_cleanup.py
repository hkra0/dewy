"""core.logic.photo._select_photos_to_delete —— 对数稀疏化的挑选逻辑。"""

import math
import unittest
from datetime import date, timedelta

from core.logic.photo import RECENT_KEEP_DAYS, _select_photos_to_delete

TODAY = date(2026, 8, 2)


def rows_for(dates):
    """按函数期望的形态构造行：(date_str, filename)，日期升序。"""
    return [(d.isoformat(), f"{d.isoformat()}.jpg") for d in dates]


def daily_rows(oldest_age, newest_age=0):
    """从 oldest_age 天前到 newest_age 天前，每天一张。"""
    return rows_for([TODAY - timedelta(days=a) for a in range(oldest_age, newest_age - 1, -1)])


def min_gap(age):
    return max(1, int(3 * math.log(age + 1)))


class SelectPhotosToDeleteTest(unittest.TestCase):

    def test_empty_input(self):
        self.assertEqual(_select_photos_to_delete([], TODAY), [])

    def test_photos_inside_the_protected_window_are_never_deleted(self):
        rows = daily_rows(RECENT_KEEP_DAYS)
        self.assertEqual(_select_photos_to_delete(rows, TODAY), [])

    def test_photo_exactly_at_the_protection_edge_is_kept(self):
        # age == RECENT_KEEP_DAYS 属于保护区（判定是 <=）
        rows = daily_rows(RECENT_KEEP_DAYS, RECENT_KEEP_DAYS)
        self.assertEqual(_select_photos_to_delete(rows, TODAY), [])

    def test_oldest_photo_is_always_kept_as_the_anchor(self):
        rows = daily_rows(400)
        deleted = {name for _, name in _select_photos_to_delete(rows, TODAY)}
        self.assertNotIn(rows[0][1], deleted)

    def test_dense_old_photos_get_thinned(self):
        rows = daily_rows(400)
        to_delete = _select_photos_to_delete(rows, TODAY)
        self.assertTrue(to_delete)
        self.assertLess(len(to_delete), len(rows))

    def test_kept_photos_respect_the_log_curve_gap(self):
        rows = daily_rows(400)
        deleted = {d for d, _ in _select_photos_to_delete(rows, TODAY)}
        kept = [date.fromisoformat(d) for d, _ in rows if d not in deleted]

        previous = kept[0]
        for current in kept[1:]:
            age = (TODAY - current).days
            if age <= RECENT_KEEP_DAYS:
                continue
            with self.subTest(kept=current.isoformat()):
                self.assertGreaterEqual((current - previous).days, min_gap(age))
            previous = current

    def test_older_photos_are_thinned_more_aggressively(self):
        """稀疏度随时间单调增：远期保留的张数应少于同长度的近期区间。"""
        rows = daily_rows(400)
        deleted = {d for d, _ in _select_photos_to_delete(rows, TODAY)}
        kept_ages = sorted((TODAY - date.fromisoformat(d)).days for d, _ in rows if d not in deleted)

        far = sum(1 for a in kept_ages if 300 <= a <= 400)
        near = sum(1 for a in kept_ages if 100 <= a <= 200)
        self.assertLess(far, near)

    def test_already_sparse_history_is_left_alone(self):
        # 每 90 天一张，远超任何 age 的 min_gap（400 天时约 18 天）
        rows = rows_for([TODAY - timedelta(days=a) for a in (720, 630, 540, 450, 360, 270, 180, 90)])
        self.assertEqual(_select_photos_to_delete(rows, TODAY), [])

    def test_malformed_date_is_skipped_not_deleted(self):
        rows = [("not-a-date", "junk.jpg")] + daily_rows(400)
        deleted = {name for _, name in _select_photos_to_delete(rows, TODAY)}
        self.assertNotIn("junk.jpg", deleted)

    def test_returns_rows_in_their_original_form(self):
        rows = daily_rows(400)
        to_delete = _select_photos_to_delete(rows, TODAY)
        for item in to_delete:
            self.assertIn(item, rows)

    def test_future_dated_photo_is_treated_as_protected(self):
        # 树莓派没同步 NTP 时可能写入未来日期，age 为负数，落入保护区
        rows = rows_for([TODAY + timedelta(days=1)])
        self.assertEqual(_select_photos_to_delete(rows, TODAY), [])


if __name__ == "__main__":
    unittest.main()
