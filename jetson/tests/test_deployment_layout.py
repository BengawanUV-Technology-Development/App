import unittest
from pathlib import Path


JETSON_DIR = Path(__file__).parents[1]
CANONICAL_ROOT = "/home/bengawan/Documents/app-mavproxy"


class JetsonDeploymentLayoutTests(unittest.TestCase):
    def test_camera_service_uses_canonical_repository(self):
        unit = (JETSON_DIR / "buv-camera-stream.service").read_text(encoding="utf-8")

        self.assertIn(f"WorkingDirectory={CANONICAL_ROOT}", unit)
        self.assertIn(
            f"ExecStart=/usr/bin/python3 {CANONICAL_ROOT}/jetson/camera_stream_service.py",
            unit,
        )
        self.assertNotIn("App-v03", unit)

    def test_recording_service_manifest_uses_canonical_repository(self):
        unit_path = JETSON_DIR / "buv-recording-agent.service"
        self.assertTrue(unit_path.is_file())
        unit = unit_path.read_text(encoding="utf-8")

        self.assertIn(f"WorkingDirectory={CANONICAL_ROOT}", unit)
        self.assertIn(
            f"ExecStart=/usr/bin/python3 {CANONICAL_ROOT}/jetson/recording_agent.py",
            unit,
        )
        self.assertNotIn("/opt/buv-app", unit)

    def test_jetson_deployment_guide_exists(self):
        guide = JETSON_DIR / "README.md"
        self.assertTrue(guide.is_file())
        contents = guide.read_text(encoding="utf-8")
        self.assertIn(CANONICAL_ROOT, contents)
        self.assertIn("App-v03", contents)

    def test_source_tree_has_no_timestamped_backup_files(self):
        backups = sorted(
            path.name
            for pattern in ("*.bak-*", "*~")
            for path in JETSON_DIR.glob(pattern)
        )
        self.assertEqual([], backups)
        self.assertFalse((JETSON_DIR / "buv-recording-agent.service.example").exists())


if __name__ == "__main__":
    unittest.main()
