import unittest

from app.services.vision_overlay import VisionOverlayError, VisionOverlayStore


def overlay_payload():
    return {
        "schema_version": "1.0",
        "type": "vision.overlay",
        "detection_id": "FRAME-12-abcd1234",
        "timestamp": "2026-08-07T00:00:00Z",
        "frame_id": 12,
        "frame_timestamp": "2026-08-07T00:00:00Z",
        "pts_ns": 400_000_000,
        "source_width": 1920,
        "source_height": 1080,
        "network_width": 960,
        "network_height": 540,
        "detections": [
            {
                "class": "person",
                "confidence": 0.91,
                "bbox_highres": [100.0, 200.0, 500.0, 800.0],
                "bbox_network": [50.0, 100.0, 250.0, 400.0],
                "bbox_norm_highres": [0.05, 0.18, 0.26, 0.74],
            }
        ],
    }


class VisionOverlayStoreTests(unittest.TestCase):
    def test_latest_payload_is_available_without_triggering_other_services(self):
        store = VisionOverlayStore(ttl_seconds=1.0)

        response = store.ingest(overlay_payload())

        self.assertTrue(response["ok"])
        self.assertFalse(response["stale"])
        self.assertEqual(response["frame_id"], 12)
        self.assertEqual(response["detections"][0]["bbox_network"], [50.0, 100.0, 250.0, 400.0])

    def test_overlay_expires_and_clears_boxes(self):
        store = VisionOverlayStore(ttl_seconds=0.1)
        store.ingest(overlay_payload())
        store._received_monotonic -= 1

        response = store.latest()

        self.assertTrue(response["stale"])
        self.assertEqual(response["detections"], [])
        self.assertEqual(response["frame_id"], 12)

    def test_overlay_keeps_b0249_preview_compatibility_context(self):
        payload = overlay_payload()
        payload.update(
            camera_id="b0249",
            preview_source_at_detection="analog",
            overlay_compatible=False,
        )

        response = VisionOverlayStore().ingest(payload)

        self.assertEqual(response["camera_id"], "b0249")
        self.assertEqual(response["preview_source_at_detection"], "analog")
        self.assertFalse(response["overlay_compatible"])

    def test_invalid_box_is_rejected(self):
        payload = overlay_payload()
        payload["detections"][0]["bbox_network"] = [50, 100, 1000, 400]

        with self.assertRaises(VisionOverlayError):
            VisionOverlayStore().ingest(payload)

    def test_empty_store_is_explicitly_stale(self):
        response = VisionOverlayStore().latest()

        self.assertTrue(response["ok"])
        self.assertTrue(response["stale"])
        self.assertEqual(response["detections"], [])

    def test_clear_discards_live_overlay_correlation(self):
        store = VisionOverlayStore()
        store.ingest(overlay_payload())

        store.clear()
        response = store.latest()

        self.assertTrue(response["stale"])
        self.assertIsNone(response["frame_id"])


if __name__ == "__main__":
    unittest.main()
