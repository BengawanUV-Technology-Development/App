import unittest
from unittest.mock import Mock

from jetson.camera_stream_service import CameraStreamService


class CameraStreamServiceTests(unittest.TestCase):
    def test_recording_marker_stops_process_to_release_camera_devices(self):
        service = CameraStreamService()
        service.loop = Mock()
        service.recording_active = Mock(return_value=True)

        self.assertFalse(service.poll_state())
        self.assertTrue(service.stop_requested)
        service.loop.quit.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
