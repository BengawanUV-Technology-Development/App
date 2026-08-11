import tempfile
import unittest
import uuid
from pathlib import Path

from flask import Flask, jsonify

from app.auth import BearerAuthenticator, TokenConfig
from app.contracts import ContractError, FrameIdentity, validate_detection_event, validate_normalized_xyxy
from app.persistence import Database
from app.routes import api_v1 as api_routes


def identity_payload():
    return {
        "schema_version": "2.0",
        "mission_id": f"mission-{uuid.uuid4()}",
        "capture_epoch": 1,
        "frame_id": 0,
        "camera_id": "arducam",
        "capture_utc_ns": 1786401234281000000,
        "capture_monotonic_ns": 928193821000,
        "source_pts_ns": 0,
    }


class ContractTests(unittest.TestCase):
    def test_v2_identity_and_exact_key(self):
        identity = FrameIdentity.from_mapping(identity_payload())
        self.assertEqual(identity.key[1:], (1, 0, "arducam"))

    def test_v1_is_rejected(self):
        payload = identity_payload()
        payload["schema_version"] = "1.1"
        with self.assertRaisesRegex(ContractError, "2.0"):
            FrameIdentity.from_mapping(payload)

    def test_bbox_is_normalized_xyxy(self):
        self.assertEqual(validate_normalized_xyxy([0.1, 0.2, 0.8, 0.9]), (0.1, 0.2, 0.8, 0.9))
        with self.assertRaises(ContractError):
            validate_normalized_xyxy([0.8, 0.2, 0.1, 0.9])

    def test_detection_forbids_fabricated_coordinates(self):
        payload = {
            **identity_payload(), "type": "vision.detection_event",
            "detection_id": str(uuid.uuid4()), "class": "person", "confidence": 0.9,
            "bbox_normalized_xyxy": [0.1, 0.2, 0.8, 0.9], "coordinate": {"status": "not_available"},
        }
        self.assertEqual(validate_detection_event(payload)["coordinate"]["status"], "not_available")
        payload["coordinate"] = {"status": "available", "latitude": 0, "longitude": 0}
        with self.assertRaises(ContractError):
            validate_detection_event(payload)


class PersistenceTests(unittest.TestCase):
    def test_epoch_is_durable_and_detection_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "buv.sqlite3"
            database = Database(path)
            mission_id = identity_payload()["mission_id"]
            database.create_mission(mission_id)
            self.assertEqual(database.next_epoch(mission_id), 1)
            self.assertEqual(Database(path).next_epoch(mission_id), 2)
            detection = {
                **identity_payload(), "mission_id": mission_id, "capture_epoch": 2,
                "type": "vision.detection_event",
                "detection_id": str(uuid.uuid4()), "class": "person", "confidence": 0.9,
                "bbox_normalized_xyxy": [0.1, 0.2, 0.8, 0.9], "coordinate": {"status": "not_available"},
            }
            self.assertTrue(database.insert_detection(detection))
            self.assertFalse(database.insert_detection(detection))


class AuthTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        auth = BearerAuthenticator(TokenConfig("operator-secret", "ingest-secret", "agent-secret"))
        app.before_request(lambda: auth.authenticate(__import__("flask").request))
        app.add_url_rule("/api/v1/commands/arm", endpoint="arm", view_func=lambda: jsonify(ok=True), methods=["POST"])
        app.add_url_rule("/api/v1/detection/ingest", endpoint="ingest", view_func=lambda: jsonify(ok=True), methods=["POST"])
        app.add_url_rule("/api/v1/health", endpoint="health", view_func=lambda: jsonify(ok=True), methods=["GET"])
        self.client = app.test_client()

    def test_protected_routes_reject_missing_or_wrong_role(self):
        self.assertEqual(self.client.post("/api/v1/commands/arm").status_code, 401)
        wrong = self.client.post("/api/v1/detection/ingest", headers={"Authorization": "Bearer operator-secret"})
        self.assertEqual(wrong.status_code, 401)

    def test_role_tokens_and_public_read(self):
        operator = self.client.post("/api/v1/commands/arm", headers={"Authorization": "Bearer operator-secret"})
        ingest = self.client.post("/api/v1/detection/ingest", headers={"Authorization": "Bearer ingest-secret"})
        self.assertEqual((operator.status_code, ingest.status_code, self.client.get("/api/v1/health").status_code), (200, 200, 200))


class DetectionIngestRouteTests(unittest.TestCase):
    def test_event_ingest_is_validated_persistent_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Flask(__name__)
            api_routes._database = Database(Path(directory) / "buv.sqlite3")
            app.register_blueprint(api_routes.api_v1_bp)
            client = app.test_client()
            payload = {
                **identity_payload(),
                "type": "vision.detection_event",
                "detection_id": str(uuid.uuid4()),
                "class": "person",
                "confidence": 0.9,
                "bbox_normalized_xyxy": [0.1, 0.2, 0.8, 0.9],
                "coordinate": {"status": "not_available"},
            }

            created = client.post("/api/v1/detection/ingest", json=payload)
            duplicate = client.post("/api/v1/detection/ingest", json=payload)
            invalid = client.post(
                "/api/v1/detection/ingest",
                json={**payload, "coordinate": {"status": "available", "latitude": 0}},
            )

            self.assertEqual(created.status_code, 202)
            self.assertTrue(created.get_json()["accepted"])
            self.assertEqual(duplicate.status_code, 200)
            self.assertTrue(duplicate.get_json()["duplicate"])
            self.assertEqual(invalid.status_code, 400)
            self.assertNotIn("ai_decision", created.get_json())


if __name__ == "__main__":
    unittest.main()
