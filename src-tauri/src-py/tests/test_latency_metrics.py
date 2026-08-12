import unittest

from app.services.latency_metrics import LatencyMetrics


class LatencyMetricsTests(unittest.TestCase):
    def test_snapshot_reports_bounded_percentiles(self):
        metrics = LatencyMetrics(capacity=3)
        for value in (1, 2, 3, 4):
            metrics.observe(value)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["count"], 3)
        self.assertEqual(snapshot["min_ms"], 2.0)
        self.assertEqual(snapshot["max_ms"], 4.0)
        self.assertEqual(snapshot["p50_ms"], 3.0)
        self.assertEqual(snapshot["p95_ms"], 3.9)

    def test_empty_and_invalid_samples_are_explicit(self):
        metrics = LatencyMetrics()
        self.assertIsNone(metrics.snapshot()["p95_ms"])
        with self.assertRaises(ValueError):
            metrics.observe(-1)
        with self.assertRaises(ValueError):
            metrics.observe(float("nan"))


if __name__ == "__main__":
    unittest.main()
