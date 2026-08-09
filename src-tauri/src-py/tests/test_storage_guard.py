import tempfile
import unittest
from pathlib import Path

from jetson.storage_guard import StorageGuardError, validate_record_storage


class StorageGuardTests(unittest.TestCase):
    def test_validates_writable_development_directory_when_root_is_explicitly_allowed(self):
        with tempfile.TemporaryDirectory() as temporary:
            info = validate_record_storage(
                Path(temporary) / "flight-recordings",
                min_free_bytes=1,
                allow_root=True,
            )

        self.assertGreater(info.free_bytes, 0)
        self.assertEqual(info.record_dir.name, "flight-recordings")

    def test_rejects_root_mount_by_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(StorageGuardError, "root filesystem"):
                validate_record_storage(Path(temporary), min_free_bytes=1)


if __name__ == "__main__":
    unittest.main()
