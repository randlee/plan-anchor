"""Exercise live-harness setup with controlled client calls, without a provider."""
from contextlib import ExitStack
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


class LiveHarnessSetupTests(unittest.TestCase):
    def test_keychain_case_accepts_only_success_or_typed_timeout(self):
        path = Path(__file__).resolve().parents[1] / "integration" / "test_installed_wheel.py"
        spec = importlib.util.spec_from_file_location("controlled_keychain_harness", path)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, {"PLAN_ANCHOR_LIVE_INTEGRATION": "1"}), \
                mock.patch.dict(sys.modules, {"pytest": types.SimpleNamespace(fixture=lambda function: function)}):
            spec.loader.exec_module(module)
        outcomes = [module.jj.Ok({}), module.jj.Err(module.jj.ClientError("AUTH.CREDENTIALS", "timeout", data={"id": "secrets.keyring_timeout"}))]
        with mock.patch.dict(os.environ, {"PLAN_ANCHOR_INTEGRATION_KEY_VARIABLE": "TYPESAFE_API_KEY"}), \
                mock.patch.object(module.jj, "call_jev", side_effect=outcomes):
            for expected in ("default keychain: success", "default keychain: secrets.keyring_timeout"):
                record = mock.Mock()
                monkeypatch = mock.Mock()
                module.test_default_keychain_succeeds_or_times_out(Path("unused"), monkeypatch, record)
                monkeypatch.delenv.assert_called_once_with('TYPESAFE_API_KEY', raising=False)
                record.assert_called_once_with("result", expected)
        keyring_read = module.jj.Err(module.jj.ClientError(
            "AUTH.CREDENTIALS", "denied", data={"id": "secrets.keyring_read"}))
        with mock.patch.dict(os.environ, {"PLAN_ANCHOR_INTEGRATION_KEY_VARIABLE": "TYPESAFE_API_KEY"}), \
                mock.patch.object(module, "secret_service_available", return_value=True), \
                mock.patch.object(module.jj, "call_jev", return_value=keyring_read):
            with self.assertRaises(AssertionError):
                module.test_default_keychain_succeeds_or_times_out(Path("unused"), mock.Mock(), mock.Mock())
        with mock.patch.dict(os.environ, {"PLAN_ANCHOR_INTEGRATION_KEY_VARIABLE": "TYPESAFE_API_KEY"}), \
                mock.patch.object(module, "secret_service_available", return_value=False), \
                mock.patch.object(module.jj, "call_jev", return_value=keyring_read):
            record = mock.Mock()
            module.test_default_keychain_succeeds_or_times_out(Path("unused"), mock.Mock(), record)
            self.assertEqual(
                record.call_args_list[0],
                mock.call("result", "default keychain: secret service absent: secrets.keyring_read"),
            )
        other_error = module.jj.Err(module.jj.ClientError(
            "AUTH.CREDENTIALS", "missing data", data={"id": "secrets.keyring_miss"}))
        with mock.patch.dict(os.environ, {"PLAN_ANCHOR_INTEGRATION_KEY_VARIABLE": "TYPESAFE_API_KEY"}), \
                mock.patch.object(module, "secret_service_available", return_value=False), \
                mock.patch.object(module.jj, "call_jev", return_value=other_error):
            with self.assertRaises(AssertionError):
                module.test_default_keychain_succeeds_or_times_out(Path("unused"), mock.Mock(), mock.Mock())

    def test_fixture_routes_both_current_client_calls_to_isolated_config(self):
        path = Path(__file__).resolve().parents[1] / "integration" / "test_installed_wheel.py"
        spec = importlib.util.spec_from_file_location("controlled_live_harness", path)
        module = importlib.util.module_from_spec(spec)
        fake_pytest = types.SimpleNamespace(fixture=lambda function: function)
        with mock.patch.dict(os.environ, {"PLAN_ANCHOR_LIVE_INTEGRATION": "1"}), \
                mock.patch.dict(sys.modules, {"pytest": fake_pytest}):
            spec.loader.exec_module(module)

        single, batch = mock.Mock(return_value="single"), mock.Mock(return_value="batch")
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {"PLAN_ANCHOR_INTEGRATION_WHEEL_VERSION": "test"}))
            stack.enter_context(mock.patch.object(module.importlib.metadata, "version", return_value="test"))
            stack.enter_context(mock.patch.object(module, "run_test_child"))
            stack.enter_context(mock.patch.object(module.jj.decidr_client, "call_result", single))
            stack.enter_context(mock.patch.object(module.jj.decidr_client, "call_batch_results", batch))
            monkeypatch = mock.Mock()
            monkeypatch.setattr.side_effect = lambda target, name, value: stack.enter_context(mock.patch.object(target, name, value))
            root = Path(tmp)
            module.live(root, monkeypatch, mock.Mock())
            self.assertEqual(module.jj.decidr_client.call_result("request", model="jev"), "single")
            self.assertEqual(module.jj.decidr_client.call_batch_results(["request"], model="jev"), "batch")
            single.assert_called_once_with("request", model="jev", config_dir=str(root / "wheel-config"))
            batch.assert_called_once_with(["request"], model="jev", config_dir=str(root / "wheel-config"))
            monkeypatch.chdir.assert_called_once_with(root)


if __name__ == "__main__":
    unittest.main()
