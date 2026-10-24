import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import Mock, patch

from core.logic import maintenance as m


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.key = "a" * 64
        self.topic = "device/aqua/config/maintenance/state"
        self.hardware = patch.object(m.state, "hardware_manager", Mock(mqtt_nodes={
            "aqua": {"config_topic": "device/aqua/config", "maintenance_key": self.key}}))
        self.hardware.start()
        self.addCleanup(self.hardware.stop)
        m._nodes.clear()
        m._jobs.clear()
        self.report = {"boot": "old", "board": "lolin_s3_mini", "build": "0" * 32,
                       "ota_max": 1310720, "rollback": True, "ota_protocol": "DEWY_OTA:2", "boot_state": "valid"}
        self.emit(self.report)

    def emit(self, report, key=None):
        body = json.dumps(report)
        m.receive(self.topic, {"body": body, "mac": hmac.new(
            (key or self.key).encode(), body.encode(), hashlib.sha256).hexdigest()})

    def image(self, node="aqua", board="lolin_s3_mini"):
        return b"\xe9" + f"DEWY_TARGET:{node}:{board}\0DEWY_BUILD:{'1' * 32}\0DEWY_OTA:2\0".encode() + b"X" * 1600

    def test_signature_and_bounded_log_cursor(self):
        self.emit({**self.report, "log": "forged"}, "wrong")
        self.assertEqual(m.status("aqua")["cursor"], 0)
        for i in range(310):
            self.emit({**self.report, "log": f"<script>{i}</script>"})
        result = m.status("aqua", after=305)
        self.assertEqual(len(m._nodes["aqua"]["logs"]), 300)
        self.assertEqual([x["seq"] for x in result["logs"]], [306, 307, 308, 309, 310])
        self.assertEqual(result["cursor"], 310)

    def test_unknown_or_unprovisioned_node(self):
        with self.assertRaises(ValueError):
            m.status("main")
        m.state.hardware_manager.mqtt_nodes["aqua"]["maintenance_key"] = ""
        with self.assertRaises(ValueError):
            m.start_update("aqua", self.image())

    def test_image_preflight(self):
        self.assertEqual(m.validate_image(self.image(), "aqua", "lolin_s3_mini"), "1" * 32)
        for image in (b"\0" * 512, self.image("other"), self.image(board="esp32dev"),
                      self.image().replace(b"DEWY_BUILD:", b"INVALID_ID:")):
            with self.assertRaises(ValueError):
                m.start_update("aqua", image)
        self.emit({**self.report, "ota_max": 1000})
        with self.assertRaises(ValueError):
            m.start_update("aqua", self.image())

    def test_unprotected_images_and_baselines_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "rollback protocol"):
            m.validate_image(self.image().replace(b"DEWY_OTA:2", b"DEWY_OTA:1"), "aqua", "lolin_s3_mini")
        self.emit({**self.report, "rollback": False})
        with self.assertRaisesRegex(ValueError, "USB"):
            m.start_update("aqua", self.image())
        self.emit({**self.report, "boot_state": "pending_verify"})
        with self.assertRaisesRegex(RuntimeError, "awaiting"):
            m.start_update("aqua", self.image())

    def test_new_boot_alone_never_confirms_success(self):
        job = {"id": "s", "build": "1" * 32, "boot": "old", "status": "rebooting"}
        report = {**self.report, "boot": "new", "build": "1" * 32, "boot_state": "pending_verify",
                  "update_result": {"session": "s", "build": "1" * 32, "status": "pending"}}
        self.assertFalse(m._reconcile_result(job, report))
        report["update_result"]["status"] = "succeeded"
        self.assertFalse(m._reconcile_result(job, report))
        report["boot_state"] = "valid"
        report["update_result"]["session"] = "unrelated"
        self.assertFalse(m._reconcile_result(job, report))
        report["update_result"]["session"] = "s"
        self.assertTrue(m._reconcile_result(job, report))
        self.assertEqual(job["status"], "succeeded")

    def test_rollback_matches_session_and_same_build_reflash(self):
        job = {"id": "s", "build": "0" * 32, "boot": "old", "status": "verifying"}
        report = {**self.report, "boot": "restored", "update_result": {"session": "s", "build": "0" * 32,
                  "status": "rolled_back", "code": "main_loop_stalled"}}
        self.assertTrue(m._reconcile_result(job, report))
        self.assertEqual(job["error_code"], "rolled_back")
        self.assertEqual(job["device_error"], "main_loop_stalled")

    def test_unconfirmed_outcome_does_not_abort_committed_image_and_late_result_updates(self):
        job = {"id": "s", "build": "1" * 32, "boot": "old", "status": "sending", "sent": 0}
        with patch.object(m, "_exchange"), patch.object(m, "_send") as send, patch.object(m, "BOOT_CONFIRM_TIMEOUT", 0):
            m._transfer("aqua", self.image(), self.report, job)
        self.assertEqual(job["error_code"], "outcome_unknown")
        self.assertEqual([call.args[1]["op"] for call in send.call_args_list], ["end"])
        m._jobs["aqua"] = job
        self.emit({**self.report, "boot": "restored", "update_result": {"session": "s", "build": "1" * 32,
                   "status": "rolled_back", "code": "confirmation_timeout"}})
        self.assertEqual(m.status("aqua")["job"]["error_code"], "rolled_back")

    def test_offline_and_concurrent_update(self):
        m._nodes["aqua"]["seen"] = time.monotonic() - 21
        with self.assertRaises(RuntimeError):
            m.start_update("aqua", self.image())
        self.emit(self.report)
        m._jobs["aqua"] = {"status": "sending"}
        with self.assertRaises(RuntimeError):
            m.start_update("aqua", self.image())

    def test_mqtt_transfer_and_new_boot_confirmation(self):
        received = bytearray()
        commands = []
        def publish(topic, envelope, qos, retain):
            self.assertFalse(retain)
            self.assertEqual(qos, 1)
            packet = json.loads(envelope)
            expected = hmac.new(self.key.encode(), packet["body"].encode(), hashlib.sha256).hexdigest()
            self.assertTrue(hmac.compare_digest(expected, packet["mac"]))
            command = json.loads(packet["body"])
            commands.append(command)
            response = {**self.report, "session": command["session"], "ack": command["op"]}
            if command["op"] == "chunk":
                import base64
                self.assertEqual(command["offset"], len(received))
                received.extend(base64.b64decode(command["data"]))
            response["offset"] = len(received)
            if command["op"] in ("end", "confirm"):
                response.update(boot="new", build="1" * 32, boot_state="pending_verify", health_ready=True)
            if command["op"] == "confirm":
                self.assertEqual(command["boot"], "new")
                response.update(boot_state="valid", update_result={"session": command["session"],
                                "build": "1" * 32, "status": "succeeded", "code": ""})
            self.emit(response)
            return Mock(rc=0)
        client = Mock()
        client.publish.side_effect = publish
        with patch.object(m.state, "global_mqtt_client", client):
            job = m.start_update("aqua", self.image())
            deadline = time.monotonic() + 3
            while m.status("aqua")["job"]["status"] in m.ACTIVE_STATUSES and time.monotonic() < deadline:
                time.sleep(.01)
        result = m.status("aqua")["job"]
        self.assertEqual(result["id"], job["id"])
        self.assertEqual(result["status"], "succeeded", result)
        self.assertEqual(bytes(received), self.image())
        self.assertEqual(commands[0]["md5"], hashlib.md5(received).hexdigest())
        self.assertIn("confirm", [c["op"] for c in commands])

    def test_device_rejection_aborts_job(self):
        def reject(node, command):
            if command["op"] != "abort":
                self.emit({**self.report, "session": command["session"], "error": "Not enough space"})
        with patch.object(m, "_send", side_effect=reject):
            m.start_update("aqua", self.image())
            deadline = time.monotonic() + 2
            while m.status("aqua")["job"]["status"] == "sending" and time.monotonic() < deadline:
                time.sleep(.01)
            result = m.status("aqua")["job"]
            self.assertEqual(result["status"], "failed")
            self.assertIn("Not enough space", result["error"])

    def test_exchange_retries_and_reboot_rejected(self):
        command = {"op": "begin", "session": "s", "boot": "old"}
        # Immediate fake deadlines exercise the timeout/retry path without 20s waits.
        times = iter([0, 6] * 4)
        with patch.object(m, "_send") as send, patch.object(m.time, "monotonic", side_effect=lambda: next(times)):
            with self.assertRaises(RuntimeError):
                m._exchange("aqua", command, 0)
            self.assertEqual(send.call_count, 4)
        self.emit({**self.report, "boot": "new"})
        with patch.object(m, "_send"):
            with self.assertRaisesRegex(RuntimeError, "rebooted"):
                m._exchange("aqua", command, 0)
