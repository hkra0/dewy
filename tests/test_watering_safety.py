"""水泵人工急停与土壤传感器离土联锁。"""

import unittest
from unittest.mock import MagicMock

import tests  # noqa: F401 — 加载 core 桩
import core.config as config
import core.database as db
import core.state as state
from core.logic import watering


def _status(**overrides):
    base = {
        "manual_stop": False,
        "sensor_interlock": False,
        "interlock_reason": None,
        "interlock_since": None,
        "recovery_count": 0,
        "updated_at": None,
    }
    base.update(overrides)
    return base


class WateringSafetyTest(unittest.TestCase):
    def setUp(self):
        config.global_config = {
            "auto_water": {
                "actuator_id": "pump",
                "sensor_air_threshold": 15.0,
                "sensor_drop_threshold": 40.0,
                "sensor_recovery_threshold": 30.0,
                "sensor_recovery_rise": 15.0,
                "sensor_recovery_samples": 3,
            }
        }
        state.hardware_manager = MagicMock()
        state.hardware_manager.trigger_actuator.return_value = True
        state.watering_lock = __import__("threading").RLock()

        db.query_watering_safety = MagicMock(return_value=_status())
        db.query_latest_soil = MagicMock(return_value=90.0)
        db.latch_soil_sensor_interlock = MagicMock(
            return_value=_status(sensor_interlock=True, interlock_reason="soil_drop"))
        db.set_soil_sensor_recovery = MagicMock()
        db.clear_soil_sensor_interlock = MagicMock()
        db.set_manual_watering_stop = MagicMock()

    def test_abrupt_drop_near_air_latches_and_forces_off(self):
        result = watering.evaluate_soil_sensor_safety("main", 10.0, previous_soil=90.0)

        self.assertTrue(result["sensor_interlock"])
        db.latch_soil_sensor_interlock.assert_called_once()
        state.hardware_manager.trigger_actuator.assert_called_once_with(
            "main", "pump", state=False)

    def test_low_but_not_abrupt_reading_does_not_latch(self):
        watering.evaluate_soil_sensor_safety("main", 12.0, previous_soil=35.0)

        db.latch_soil_sensor_interlock.assert_not_called()
        state.hardware_manager.trigger_actuator.assert_not_called()

    def test_recovery_needs_initial_rise_then_consecutive_samples(self):
        db.query_watering_safety.return_value = _status(
            sensor_interlock=True, recovery_count=0)
        db.set_soil_sensor_recovery.return_value = _status(
            sensor_interlock=True, recovery_count=1)

        watering.evaluate_soil_sensor_safety("main", 40.0, previous_soil=10.0)
        db.set_soil_sensor_recovery.assert_called_once_with("main", 1)
        db.clear_soil_sensor_interlock.assert_not_called()

        db.query_watering_safety.return_value = _status(
            sensor_interlock=True, recovery_count=2)
        db.clear_soil_sensor_interlock.return_value = _status()
        result = watering.evaluate_soil_sensor_safety("main", 42.0, previous_soil=41.0)
        self.assertFalse(result["sensor_interlock"])
        db.clear_soil_sensor_interlock.assert_called_once_with("main")

    def test_stable_high_value_cannot_start_recovery_without_a_rise(self):
        db.query_watering_safety.return_value = _status(
            sensor_interlock=True, recovery_count=0)

        watering.evaluate_soil_sensor_safety("main", 40.0, previous_soil=38.0)

        db.set_soil_sensor_recovery.assert_not_called()
        db.clear_soil_sensor_interlock.assert_not_called()

    def test_manual_stop_is_persistent_and_forces_off(self):
        db.set_manual_watering_stop.return_value = _status(manual_stop=True)

        result = watering.set_manual_emergency_stop("main", True)

        self.assertTrue(result["manual_stop"])
        self.assertTrue(result["pump_off_sent"])
        db.set_manual_watering_stop.assert_called_once_with("main", True)
        state.hardware_manager.trigger_actuator.assert_called_once_with(
            "main", "pump", state=False)

    def test_auto_recovery_never_clears_manual_stop(self):
        db.query_watering_safety.return_value = _status(
            manual_stop=True, sensor_interlock=True, recovery_count=2)
        db.clear_soil_sensor_interlock.return_value = _status(manual_stop=True)

        result = watering.evaluate_soil_sensor_safety("main", 50.0, previous_soil=45.0)

        self.assertTrue(result["manual_stop"])
        db.set_manual_watering_stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
