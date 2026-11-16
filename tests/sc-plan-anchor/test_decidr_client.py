from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from unittest.mock import Mock, call, patch

from layout_support import SCRIPTS


def load_client():
    path = SCRIPTS / "decidr_client.py"
    spec = importlib.util.spec_from_file_location("plan_anchor_decidr_client_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DecidrClientTests(unittest.TestCase):
    def setUp(self):
        self.client = load_client()
        self.old_agent = sys.modules.get("sc_agent")
        self.agent = types.ModuleType("sc_agent")
        self.agent.SagError = type("SagError", (Exception,), {})
        self.agent.category = lambda detail: json.loads(detail).get("category")
        self.agent.CancelToken = type("CancelToken", (), {"cancel": Mock()})
        sys.modules["sc_agent"] = self.agent

    def tearDown(self):
        if self.old_agent is None:
            sys.modules.pop("sc_agent", None)
        else:
            sys.modules["sc_agent"] = self.old_agent

    def test_client_records_exact_sc_agent_prerelease_source(self):
        self.assertEqual(self.client.SC_DECIDR_VERSION, "0.2.0")
        self.assertEqual(self.client.SC_AGENT_RELEASE_TAG, "prerelease/v0.2.0")
        self.assertEqual(self.client.SC_AGENT_RELEASE_COMMIT, "e1f0bf94a10de80d908b1bacce86cee80ea29250")
        self.assertEqual(self.client.SC_AGENT_RELEASE_URL,
                         "https://github.com/randlee/sc-agent/releases/tag/prerelease/v0.2.0")

    def test_call_passes_model_keyring_timeout_and_logging(self):
        self.agent.send = Mock(return_value='{"response":{"text":"ok"}}')
        general_sink = Mock()
        cancel = self.agent.CancelToken()
        result = self.client.call(
            "request", model="model-selector", project="demo", agent_role="planner",
            abort_on=frozenset(), category_codes={}, cancel=cancel,
            config_dir="/tmp/config", keyring_service="plan-anchor",
            keyring_account="typesafe-api-key", general_log=general_sink,
            timeout_secs=45,
        )
        self.assertEqual(result, ('{"response":{"text":"ok"}}', None))
        self.agent.send.assert_called_once_with(
            "request", model="model-selector", project="demo", agent_role="planner",
            cancel=cancel, images=None, long_context=False, config_dir="/tmp/config",
            keyring_service="plan-anchor", keyring_account="typesafe-api-key",
            general_log=general_sink, timeout_secs=45,
        )
        self.assertNotIn("session_log", self.agent.send.call_args.kwargs)
        self.assertNotIn("api-key", result[0])

    def test_default_keyring_location_is_forwarded_for_both_calls(self):
        self.agent.send = Mock(return_value='{"response": {}}')
        self.agent.send_batch = Mock(return_value=[])
        common = dict(model="m", project="p", agent_role="r", abort_on=frozenset(),
                      category_codes={}, cancel=Mock())
        self.client.call("request", **common)
        self.client.call_batch(["request"], **common)
        for method in (self.agent.send, self.agent.send_batch):
            self.assertEqual(method.call_count, 1)
            self.assertEqual(method.call_args.kwargs["keyring_service"], "plan-anchor")
            self.assertEqual(method.call_args.kwargs["keyring_account"], "typesafe-api-key")

    def test_invalid_abort_on_fails_before_import_or_send(self):
        self.agent.send = Mock()
        with self.assertRaises(ValueError):
            self.client.call("request", model="m", project="p", agent_role="r",
                             abort_on=frozenset({"quota"}), category_codes={}, cancel=Mock())
        self.agent.send.assert_not_called()

    def test_sag_error_is_mapped_and_selected_category_cancels(self):
        error = self.agent.SagError("typed")
        error.category = "auth"
        self.agent.send = Mock(side_effect=error)
        cancel = Mock()
        with self.assertRaises(self.agent.SagError):
            self.client.call("request", model="m", project="p", agent_role="r",
                             abort_on=frozenset({"auth"}), category_codes={"auth": "AUTH"}, cancel=cancel)
        cancel.cancel.assert_called_once_with()

    def test_unknown_result_category_maps_to_none(self):
        self.agent.send = Mock(return_value='{"error":{"id":"other","category":"unmapped"}}')
        result = self.client.call("request", model="m", project="p", agent_role="r",
                                  abort_on=frozenset(), category_codes={"auth": "AUTH"}, cancel=Mock())
        self.assertEqual(result, ('{"error":{"id":"other","category":"unmapped"}}', None))

    def test_call_cancels_on_selected_result_category(self):
        self.agent.send = Mock(return_value='{"error":{"id":"auth","category":"auth"}}')
        cancel = Mock()
        result = self.client.call("request", model="m", project="p", agent_role="r",
                                  abort_on=frozenset({"auth"}), category_codes={"auth": "AUTH"}, cancel=cancel)
        self.assertEqual(result[1], "AUTH")
        cancel.cancel.assert_called_once_with()

    def test_module_import_is_offline_and_missing_wheel_is_typed(self):
        with patch.dict(sys.modules, {"sc_agent": None}):
            offline_client = load_client()
            with self.assertRaises(offline_client.ClientError) as raised:
                offline_client.call("request", model="m", project="p", agent_role="r",
                                    abort_on=frozenset(), category_codes={}, cancel=Mock())
        self.assertEqual(raised.exception.code, "DEPENDENCY.SC_DECIDR")

    def test_batch_maps_errors_cancels_and_forwards_callback(self):
        lines = [
            '{"response":{"text":"one"}}',
            '{"error":{"id":"http.auth","category":"auth"}}',
        ]

        def send_batch(requests, *, on_result, **kwargs):
            for line in reversed(lines):
                on_result(line)
            return list(lines)

        self.agent.send_batch = Mock(side_effect=send_batch)
        cancel = Mock()
        callback = Mock()
        out = self.client.call_batch(
            ["one", "two"], model="m", project="p", agent_role="r",
            abort_on=frozenset({"auth"}), category_codes={"auth": "AUTH"}, cancel=cancel,
            workers=3, timeout_secs=30, on_result=callback,
        )
        self.assertEqual(out, [(lines[0], None), (lines[1], "AUTH")])
        cancel.cancel.assert_called_once_with()
        self.assertEqual(callback.call_args_list, [call(lines[1]), call(lines[0])])
        self.assertNotIn("session_log", self.agent.send_batch.call_args.kwargs)
        self.assertEqual(self.agent.send_batch.call_args.kwargs["workers"], 3)
        self.assertEqual(self.agent.send_batch.call_args.kwargs["timeout_secs"], 30)

    def test_keyboard_interrupt_cancels(self):
        self.agent.send = Mock(side_effect=KeyboardInterrupt)
        cancel = Mock()
        with self.assertRaises(KeyboardInterrupt):
            self.client.call("request", model="m", project="p", agent_role="r",
                             abort_on=frozenset(), category_codes={}, cancel=cancel)
        cancel.cancel.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
