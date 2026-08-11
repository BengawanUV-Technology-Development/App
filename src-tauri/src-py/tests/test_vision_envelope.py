import unittest

from app.services.frame_sync import CanonicalKey, MatchedFrame
from app.services.vision_envelope import decode_vision_envelope, encode_vision_envelope


class VisionEnvelopeTests(unittest.TestCase):
    def test_binary_envelope_keeps_jpeg_and_exact_metadata_together(self):
        key = CanonicalKey("mission-00000000-0000-0000-0000-000000000004", 1, 9, "arducam")
        frame = MatchedFrame(
            key, b"\xff\xd8jpeg\xff\xd9",
            {**key.as_dict(), "source_width": 1920, "source_height": 1080, "detector": {"status": "RUNNING"},
             "detections": [{"detection_id": "d", "class": "person", "confidence": 0.9,
                             "bbox_normalized_xyxy": [0.1, 0.2, 0.5, 0.8]}]},
            123, 1, "MATCHED",
        )
        header, jpeg = decode_vision_envelope(encode_vision_envelope(
            frame, preview_width=960, preview_height=540, fps=15, stream_state="RUNNING"
        ))
        self.assertEqual((header["frame_id"], header["detection_state"]), (9, "DETECTED"))
        self.assertEqual(header["detections"][0]["bbox_normalized_xyxy"], [0.1, 0.2, 0.5, 0.8])
        self.assertEqual(jpeg, frame.jpeg)

    def test_timeout_is_distinct_from_no_detection(self):
        key = CanonicalKey("mission-00000000-0000-0000-0000-000000000004", 1, 10, "arducam")
        timeout = MatchedFrame(key, b"\xff\xd8x\xff\xd9", None, 1, 1, "METADATA_TIMEOUT")
        header, _ = decode_vision_envelope(encode_vision_envelope(
            timeout, preview_width=960, preview_height=540, fps=15, stream_state="RUNNING"
        ))
        self.assertEqual(header["detection_state"], "METADATA_TIMEOUT")
        no_detection = MatchedFrame(
            key, b"\xff\xd8x\xff\xd9",
            {**key.as_dict(), "detector": {"status": "RUNNING"}, "detections": []},
            1, 1, "MATCHED",
        )
        no_detection_header, _ = decode_vision_envelope(encode_vision_envelope(
            no_detection, preview_width=960, preview_height=540, fps=15, stream_state="RUNNING"
        ))
        self.assertEqual(no_detection_header["detection_state"], "NO_DETECTION")


if __name__ == "__main__":
    unittest.main()
