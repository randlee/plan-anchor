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
