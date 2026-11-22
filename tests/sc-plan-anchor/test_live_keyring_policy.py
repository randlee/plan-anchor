import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from live_keyring_policy import (keyring_case_result, keyring_error_id, keyring_guidance_present,
                                 secret_service_available)


class SecretServiceDetectionTests(unittest.TestCase):
    def test_no_linux_session_bus_means_service_is_absent(self):
        self.assertIs(secret_service_available(platform="linux", environ={}), False)

    def test_bus_name_owner_reports_service_present(self):
        completed = subprocess.CompletedProcess([], 0, stdout="(true,)\n", stderr="")
        with patch("live_keyring_policy.shutil.which", return_value="/usr/bin/gdbus"), \
                patch("live_keyring_policy.subprocess.run", return_value=completed):
            result = secret_service_available(
                platform="linux", environ={"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
            )
        self.assertIs(result, True)

    def test_bus_without_secret_service_reports_absent(self):
        completed = [
            subprocess.CompletedProcess([], 0, stdout="(false,)\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="(['org.freedesktop.DBus'],)\n", stderr=""),
        ]
        with patch("live_keyring_policy.shutil.which", return_value="/usr/bin/gdbus"), \
                patch("live_keyring_policy.subprocess.run", side_effect=completed):
            result = secret_service_available(
                platform="linux", environ={"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
            )
        self.assertIs(result, False)

    def test_activatable_secret_service_counts_as_present(self):
        completed = [
            subprocess.CompletedProcess([], 0, stdout="(false,)\n", stderr=""),
            subprocess.CompletedProcess([], 0,
                                        stdout="(['org.freedesktop.secrets'],)\n", stderr=""),
        ]
        with patch("live_keyring_policy.shutil.which", return_value="/usr/bin/gdbus"), \
                patch("live_keyring_policy.subprocess.run", side_effect=completed):
            result = secret_service_available(
                platform="linux", environ={"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
            )
        self.assertIs(result, True)

    def test_unknown_bus_status_is_not_treated_as_absent(self):
        completed = subprocess.CompletedProcess([], 1, stdout="", stderr="unavailable")
        with patch("live_keyring_policy.shutil.which", return_value="/usr/bin/gdbus"), \
                patch("live_keyring_policy.subprocess.run", return_value=completed):
            result = secret_service_available(
                platform="linux", environ={"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
            )
        self.assertIsNone(result)


class KeyringOutcomeTests(unittest.TestCase):
    def test_success_is_accepted(self):
        self.assertEqual(keyring_case_result(None, None), "success")

    def test_bounded_timeout_is_accepted(self):
        self.assertEqual(keyring_case_result("secrets.keyring_timeout", None), "secrets.keyring_timeout")

    def test_read_error_is_accepted_only_when_service_is_absent(self):
        self.assertEqual(
            keyring_case_result("secrets.keyring_read", False),
            "secret service absent: secrets.keyring_read",
        )
        with self.assertRaisesRegex(AssertionError, "secrets.keyring_read"):
            keyring_case_result("secrets.keyring_read", True)
        with self.assertRaisesRegex(AssertionError, "secrets.keyring_read"):
            keyring_case_result("secrets.keyring_read", None)

    def test_other_errors_fail_even_when_service_is_absent(self):
        with self.assertRaisesRegex(AssertionError, "secrets.keyring_miss"):
            keyring_case_result("secrets.keyring_miss", False)

    def test_missing_error_id_is_not_treated_as_success(self):
        with self.assertRaisesRegex(AssertionError, "unknown"):
            keyring_case_result("unknown", False)

    def test_error_without_id_is_not_treated_as_success(self):
        outcome = SimpleNamespace(error=SimpleNamespace(data={}))
        self.assertEqual(keyring_error_id(outcome), "unknown")

    def test_keyring_error_guidance_checks_unavailable_and_fallback(self):
        helpful = SimpleNamespace(error=SimpleNamespace(
            message="The platform keyring is unavailable.",
            suggested_action="Set TYPESAFE_API_KEY in the environment or repository .env.",
        ))
        unhelpful = SimpleNamespace(error=SimpleNamespace(
            message="environment variable not found", suggested_action="Check the provider API key."
        ))
        self.assertTrue(keyring_guidance_present(helpful))
        self.assertFalse(keyring_guidance_present(unhelpful))


if __name__ == "__main__":
    unittest.main()
