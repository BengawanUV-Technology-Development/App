import unittest

from app.services.browser_render_metrics import BrowserRenderMetrics, BrowserRenderMetricsError


MISSION = "mission-00000000-0000-0000-0000-000000000020"


def metric(frame_id=1, value=10):
    return {
        "schema_version": "2.0",
        "mission_id": MISSION,
        "capture_epoch": 1,
        "frame_id": frame_id,
        "camera_id": "arducam",
        "receive_to_render_ms": value,
    }


class BrowserRenderMetricsTests(unittest.TestCase):
    def test_identity_is_deduplicated_and_percentile_is_bounded(self):
        metrics = BrowserRenderMetrics(capacity=2)
        self.assertTrue(metrics.record(metric(1, 10))["accepted"])
        self.assertFalse(metrics.record(metric(1, 20))["accepted"])
        self.assertTrue(metrics.record(metric(2, 20))["accepted"])
        self.assertEqual(metrics.snapshot()["receive_to_render"]["count"], 2)
        self.assertEqual(metrics.snapshot()["duplicate_count"], 1)

    def test_invalid_timing_is_rejected(self):
        with self.assertRaises(BrowserRenderMetricsError):
            BrowserRenderMetrics().record(metric(value=-1))


if __name__ == "__main__":
    unittest.main()
