"""Versioned snapshots and schema validation, using the existing hardware stubs."""
import copy
import importlib.util
import pathlib
import unittest
from unittest.mock import MagicMock, patch

import core.state as state
import core.config as config
from core.mqtt_handler import update_node_snapshot, node_snapshot
from core.logic.sensor_aggregator import SensorAggregator, aggregator
from core.logic import node_config


class AquaProtocolTest(unittest.TestCase):
    def setUp(self):
        self.patches = [patch.object(state, "hardware_manager", MagicMock()),
                        patch.object(state, "mqtt_latest_data", {"tank": {"data": {}, "updated": False}}),
                        patch.object(state, "node_config_state", {}),
                        patch.object(config, "global_config", {"node_settings": {}})]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        state.hardware_manager.mqtt_nodes = {"tank": {"metrics": ["water_temp", "fed", "feeding_score"],
            "settings_schema": {"enabled": {"type": "boolean"},
                                "mode": {"type": "select", "options": ["daily", "temperature_accumulation"]},
                                "rate": {"type": "number", "min": 0, "max": 20, "step": .05}}}}
        aggregator.reset_window()
        self.addCleanup(aggregator.reset_window)

    def test_v2_clears_invalid_and_missing_fields(self):
        update_node_snapshot("tank", {"data_version": 2, "water_temp": 22, "water_temp_valid": True,
                             "fed": 1, "fed_time": "2026-12-31 08:00", "feeding_score": 12}, 100)
        update_node_snapshot("tank", {"data_version": 2, "water_temp_valid": False,
                             "fed": 0, "fed_time": None, "feeding_state": "probe_fault"}, 105)
        data = state.mqtt_latest_data["tank"]["data"]
        self.assertIsNone(data["water_temp"])
        self.assertIsNone(data["feeding_score"])
        self.assertIsNone(data["fed_time"])
        self.assertEqual(data["feeding_state"], "probe_fault")
        summary = aggregator.get_window_summary("tank", data)
        self.assertIsNone(summary["water_temp"])
        self.assertEqual(summary["fed"], 0)
        self.assertFalse(node_snapshot(state.mqtt_latest_data["tank"], 130)["stale"])
        self.assertTrue(node_snapshot(state.mqtt_latest_data["tank"], 136)["stale"])

    def test_legacy_partial_updates_and_time_clear(self):
        update_node_snapshot("tank", {"water_temp": 20, "fed": 1, "fed_time": "07:30"})
        update_node_snapshot("tank", {"fed": 0})
        self.assertEqual(state.mqtt_latest_data["tank"]["data"]["water_temp"], 20)
        self.assertIsNone(state.mqtt_latest_data["tank"]["data"]["fed_time"])

    def test_unknown_protocol_does_not_refresh_old_snapshot(self):
        update_node_snapshot("tank", {"data_version": 3, "water_temp": 25}, 100)
        self.assertTrue(node_snapshot(state.mqtt_latest_data["tank"], 100)["stale"])

    def test_firmware_rollback_restores_legacy_card(self):
        update_node_snapshot("tank", {"data_version": 2, "feeding_state": "due", "feeding_score": 110})
        update_node_snapshot("tank", {"fed": 1, "fed_time": "07:30"})
        self.assertNotIn("feeding_state", state.mqtt_latest_data["tank"]["data"])
        self.assertNotIn("feeding_score", state.mqtt_latest_data["tank"]["data"])

    def test_latest_and_custom_state_metadata(self):
        a = SensorAggregator()
        for fed, score, code in [(0, 80, 1), (1, 0, 3)]:
            a.record_sample("tank", {"fed": fed, "feeding_score": score, "code": code},
                            {"code": {"aggregation": "latest"}})
        self.assertEqual(a.get_window_summary("tank"), {"fed": 1, "feeding_score": 0, "code": 3})

    def test_continuous_recovers_after_explicit_null(self):
        a = SensorAggregator()
        for v in [20, None, 23]:
            a.record_sample("tank", {"water_temp": v})
        self.assertEqual(a.get_window_summary("tank")["water_temp"], 23)

    def test_schema_validation_rejects_wrong_types_and_bounds(self):
        node_config.validate_node_settings({"tank": {"enabled": False, "mode": "daily", "rate": 2.25}})
        for key, value in [("enabled", 1), ("mode", "other"), ("rate", True),
                           ("rate", float("nan")), ("rate", 21), ("rate", 2.23)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                node_config.validate_node_settings({"tank": {key: value}})

    def test_config_report_is_not_assumed_applied(self):
        config.global_config["node_settings"] = {"tank": {"enabled": True}}
        self.assertEqual(node_config.config_status()["tank"]["status"], "pending")
        state.node_config_state["tank"] = {"enabled": False, "config_error": "inconsistent_fields"}
        self.assertEqual(node_config.config_status()["tank"]["status"], "rejected")
        state.node_config_state["tank"] = {"enabled": True, "config_error": "", "config_version": 2}
        self.assertEqual(node_config.config_status()["tank"]["status"], "applied")

    def test_default_migration_keeps_existing_daily(self):
        spec = importlib.util.spec_from_file_location("tests.aqua_real_config",
            pathlib.Path(__file__).resolve().parents[1] / "core" / "config.py")
        real_config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(real_config)
        state.hardware_manager.mqtt_nodes["tank"]["settings_schema"] = {
            "feeding_mode": {"default": "temperature_accumulation"}, "feed_start_hour": {"default": 7},
            "low_alarm_enabled": {"default": False}, "feed_max_temp": {"default": 31.5}}
        existing = {"node_settings": {"tank": {"feed_reset_hour": 9, "temp_alarm_high": 32}}}
        migrated = real_config.merge_defaults(copy.deepcopy(existing))
        self.assertEqual(migrated["node_settings"]["tank"]["feeding_mode"], "daily")
        self.assertEqual(migrated["node_settings"]["tank"]["feed_start_hour"], 9)
        self.assertTrue(migrated["node_settings"]["tank"]["low_alarm_enabled"])
        self.assertEqual(migrated["node_settings"]["tank"]["feed_max_temp"], 32)
        new = real_config.merge_defaults({})
        self.assertEqual(new["node_settings"]["tank"]["feeding_mode"], "temperature_accumulation")
