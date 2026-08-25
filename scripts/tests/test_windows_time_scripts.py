import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]


class WindowsTimeScriptContractTests(unittest.TestCase):
    def test_setup_script_contains_server_and_scoped_firewall_contract(self):
        script = (SCRIPTS_DIR / "setup_chrony_ground_windows.ps1").read_text()
        for required in (
            "W32Time",
            "AnnounceFlags",
            "TimeProviders\\NtpServer",
            "New-NetFirewallRule",
            "-RemoteAddress $JetsonIp",
            "UDP",
            "LocalPort 123",
            "reg.exe",
            "[AllowEmptyString()]",
        ):
            self.assertIn(required, script)

    def test_verifier_checks_service_provider_and_jetson_firewall_scope(self):
        script = (SCRIPTS_DIR / "verify_windows_time_server.ps1").read_text()
        for required in (
            "Get-Service -Name W32Time",
            "w32tm.exe",
            "NtpServer",
            "Get-NetFirewallAddressFilter",
            "$remoteAddresses -contains $JetsonIp",
        ):
            self.assertIn(required, script)


if __name__ == "__main__":
    unittest.main()
