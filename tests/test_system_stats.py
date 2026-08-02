"""core.logic.system 的平台探测。

这些读数过去写死了 wlan0、thermal_zone0 和 /proc/meminfo 的字段下标，
换台机器（有线接入、别的网卡名、别的内核）就悄悄读成 0 或读错值。
"""

import unittest
from unittest.mock import mock_open, patch

from core.logic import system

MEMINFO = """MemTotal:        1000 kB
MemFree:          100 kB
MemAvailable:     250 kB
Buffers:           50 kB
"""

# 字段顺序与上面不同，且 MemAvailable 不在第 4 行——旧的固定下标解析会读错
MEMINFO_REORDERED = """MemTotal:        1000 kB
Buffers:           50 kB
Cached:           200 kB
MemFree:          100 kB
MemAvailable:     250 kB
"""


class CarrierTest(unittest.TestCase):

    def test_any_connected_interface_counts(self):
        # 有线接入的机器上没有 wlan0，但 eth0 的 carrier 是 1
        with patch.object(system, "NET_INTERFACE", ""), \
             patch("glob.glob", return_value=["/sys/class/net/eth0/carrier"]), \
             patch("builtins.open", mock_open(read_data="1\n")):
            self.assertTrue(system._carrier_is_up())

    def test_all_interfaces_down(self):
        with patch.object(system, "NET_INTERFACE", ""), \
             patch("glob.glob", return_value=["/sys/class/net/eth0/carrier"]), \
             patch("builtins.open", mock_open(read_data="0\n")):
            self.assertFalse(system._carrier_is_up())

    def test_no_sys_class_net_at_all(self):
        # 非 Linux：没有 /sys，应干净地返回 False 而不是抛异常
        with patch.object(system, "NET_INTERFACE", ""), \
             patch("glob.glob", return_value=[]):
            self.assertFalse(system._carrier_is_up())

    def test_explicit_interface_is_honoured(self):
        opened = []

        def fake_open(path, *a, **kw):
            opened.append(path)
            return mock_open(read_data="1\n")()

        with patch.object(system, "NET_INTERFACE", "wlp2s0"), \
             patch("builtins.open", fake_open):
            self.assertTrue(system._carrier_is_up())
        self.assertEqual(opened, ["/sys/class/net/wlp2s0/carrier"])

    def test_unreadable_interface_does_not_raise(self):
        with patch.object(system, "NET_INTERFACE", ""), \
             patch("glob.glob", return_value=["/sys/class/net/eth0/carrier"]), \
             patch("builtins.open", side_effect=OSError):
            self.assertFalse(system._carrier_is_up())


class CpuTempTest(unittest.TestCase):

    def read_zones(self, values):
        paths = [f"/sys/class/thermal/thermal_zone{i}/temp" for i in range(len(values))]
        data = dict(zip(paths, values))

        def fake_open(path, *a, **kw):
            return mock_open(read_data=data[path])()

        with patch("glob.glob", return_value=paths), patch("builtins.open", fake_open):
            return system._read_cpu_temp()

    def test_single_zone(self):
        self.assertEqual(self.read_zones(["48123\n"]), 48.123)

    def test_hottest_zone_wins(self):
        # 板子上 zone0 未必是 CPU，取最高值比盲信 zone0 稳
        self.assertAlmostEqual(self.read_zones(["30000\n", "55000\n"]), 55.0)

    def test_implausible_readings_are_ignored(self):
        self.assertAlmostEqual(self.read_zones(["0\n", "44000\n", "9999000\n"]), 44.0)

    def test_no_thermal_zones_returns_zero(self):
        with patch("glob.glob", return_value=[]):
            self.assertEqual(system._read_cpu_temp(), 0.0)

    def test_garbage_content_returns_zero(self):
        with patch("glob.glob", return_value=["/sys/class/thermal/thermal_zone0/temp"]), \
             patch("builtins.open", mock_open(read_data="n/a")):
            self.assertEqual(system._read_cpu_temp(), 0.0)


class RamUsageTest(unittest.TestCase):

    def test_parses_by_field_name(self):
        with patch("builtins.open", mock_open(read_data=MEMINFO)):
            self.assertEqual(system._read_ram_used_pct(), 75.0)

    def test_field_order_does_not_matter(self):
        with patch("builtins.open", mock_open(read_data=MEMINFO_REORDERED)):
            self.assertEqual(system._read_ram_used_pct(), 75.0)

    def test_missing_field_returns_zero(self):
        with patch("builtins.open", mock_open(read_data="MemTotal: 1000 kB\n")):
            self.assertEqual(system._read_ram_used_pct(), 0.0)

    def test_missing_file_returns_zero(self):
        with patch("builtins.open", side_effect=OSError):
            self.assertEqual(system._read_ram_used_pct(), 0.0)


if __name__ == "__main__":
    unittest.main()
