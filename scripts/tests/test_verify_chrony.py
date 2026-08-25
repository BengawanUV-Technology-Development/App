import unittest
from unittest.mock import patch

from scripts.verify_chrony import ChronyVerificationError, verify_chrony


TRACKING = """Reference ID    : 127.0.0.1
System time     : 0.000400 seconds fast of NTP time
Leap status     : Normal
"""
SOURCES = """Name/IP address      Stratum Poll Reach LastRx Last sample
^* 192.0.2.1                2   6   377    20   +0.1ms
"""


class ChronyVerificationTests(unittest.TestCase):
    @patch("scripts.verify_chrony._run", side_effect=[TRACKING, SOURCES])
    @patch("scripts.verify_chrony.shutil.which", return_value="chronyc")
    def test_client_accepts_normalized_clock(self, _which, _run):
        report = verify_chrony(role="jetson-client", max_offset_ms=5)
        self.assertTrue(report["ok"])
        self.assertEqual(report["offset_ms"], 0.4)
        self.assertTrue(report["selected_source"])

    @patch("scripts.verify_chrony._run", side_effect=[TRACKING.replace("0.000400", "0.010000"), SOURCES])
    @patch("scripts.verify_chrony.shutil.which", return_value="chronyc")
    def test_large_offset_is_rejected(self, _which, _run):
        with self.assertRaises(ChronyVerificationError):
            verify_chrony(role="jetson-client", max_offset_ms=5)

    @patch("scripts.verify_chrony._run", side_effect=[TRACKING, SOURCES])
    def test_explicit_chronyc_path_is_used(self, run):
        report = verify_chrony(
            role="ground-server",
            chronyc_path="/opt/homebrew/bin/chronyc",
        )
        self.assertTrue(report["ok"])
        self.assertEqual(run.call_args_list[0].args[0], "/opt/homebrew/bin/chronyc")
