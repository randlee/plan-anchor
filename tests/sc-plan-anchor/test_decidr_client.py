"""Contract tests for plan-anchor's wheel boundary; no network or clocks."""
import json
import tempfile
import sys
import types
import unittest
from unittest import mock

from layout_support import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import decidr_client
import jev_judge as judge


class DecidrClientTests(unittest.TestCase):
    def test_request_timeout_and_injected_objects_reach_wheel(self):
        body = {"model": "jev-latest", "state": {"text": "hello"}, "questions": {}}
        logger, cancel = object(), object()
        wheel_send = mock.Mock(return_value=json.dumps({"response": {"answers": {}}}))
        with mock.patch.dict(sys.modules, {"sc_agent": types.SimpleNamespace(send=wheel_send)}):
            result = decidr_client.send(body, 17, general_log=logger, cancel=cancel)
        args, kwargs = wheel_send.call_args
        self.assertEqual(json.loads(args[0]), body)
        self.assertEqual(kwargs["timeout_secs"], 17)
        self.assertIs(kwargs["general_log"], logger)
        self.assertIs(kwargs["cancel"], cancel)
        self.assertEqual(kwargs["provider"], "typesafe")
        self.assertEqual(result, {"response": {"answers": {}}})

    def test_failed_result_preserves_wheel_error(self):
        error = {"id": "decision.api_status", "message": "HTTP 401", "cause": {"id": "remote"}}
        wheel_send = mock.Mock(return_value=json.dumps({"error": error}))
        with mock.patch.dict(sys.modules, {"sc_agent": types.SimpleNamespace(send=wheel_send)}):
            result = decidr_client.send({"model": "jev-latest"}, 30)
        self.assertEqual(result["error"], error)
        wheel_send.assert_called_once()

    def test_batch_correlates_out_of_order_results_and_preserves_callback(self):
        bodies = [{"model": "jev-latest", "state": {"text": str(i)}} for i in range(3)]
        lines = [json.dumps({"position": i, "response": {"model": "jev"}}) for i in (2, 0, 1)]
        callback = mock.Mock()
        batch = mock.Mock(return_value=lines)
        with mock.patch.dict(sys.modules, {"sc_agent": types.SimpleNamespace(send_batch=batch)}):
            results = decidr_client.send_batch(bodies, 25, on_result=callback)
        self.assertEqual([result["position"] for result in results], [0, 1, 2])
        self.assertEqual([json.loads(item) for item in batch.call_args.args[0]], bodies)
        self.assertEqual(batch.call_args.kwargs["timeout_secs"], 25)
        self.assertIs(batch.call_args.kwargs["on_result"], callback)

    def test_batch_refuses_duplicate_or_missing_positions(self):
        bodies = [{"model": "jev-latest"}, {"model": "jev-latest"}]
        for positions in ([0, 0], [0], [0, 2], [0, True]):
            with self.subTest(positions=positions):
                batch = mock.Mock(return_value=[json.dumps({"position": pos}) for pos in positions])
                with mock.patch.dict(sys.modules, {"sc_agent": types.SimpleNamespace(send_batch=batch)}):
                    with self.assertRaises(ValueError):
                        decidr_client.send_batch(bodies, 30)

    def test_unsupported_timeout_is_not_silently_dropped(self):
        def old_send(request, *, model, project, agent_role, provider, general_log, cancel):
            self.fail("an unsupported timeout must not be ignored")
        with mock.patch.dict(sys.modules, {"sc_agent": types.SimpleNamespace(send=old_send)}):
            with self.assertRaises(TypeError):
                decidr_client.send({"model": "jev-latest"}, 30)


class JudgeWheelIntegrationTests(unittest.TestCase):
    def test_wheel_response_is_validated_and_not_retried_by_consumer(self):
        body = {"model": "jev-latest", "state": {"item": {"text": "A"}},
                "questions": {"q": {"type": "noul"}}}
        response = {"response": {"answers": {"q": {"type": "noul", "noul": 0.8}}}}
        with mock.patch.object(decidr_client, "send", return_value=response) as send:
            result = judge.judge_with_policy(body, "", 13, 10000, 1, body["questions"])
        self.assertIsInstance(result, judge.Ok)
        self.assertEqual(result.value[0]["answers"]["q"]["noul"], 0.8)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1], 13)

    def test_failed_wheel_result_preserves_error_and_does_not_retry(self):
        body = {"model": "jev-latest", "state": {"item": {"text": "A"}},
                "questions": {"q": {"type": "noul"}}}
        detail = {"id": "decision.api_status", "message": "HTTP 429 busy", "cause": {"id": "busy"}}
        with mock.patch.object(decidr_client, "send", return_value={"error": detail}) as send:
            result = judge.judge_with_policy(body, "", 30, 10000, 1, body["questions"])
        self.assertIsInstance(result, judge.Err)
        self.assertEqual(result.error.code, detail["id"])
        self.assertEqual(result.error.data, detail)
        send.assert_called_once()

    def test_context_mapping_does_not_turn_server_errors_into_context_errors(self):
        for status, expected in ((400, "JEV.CONTEXT_EXCEEDED"), (422, "JEV.CONTEXT_EXCEEDED"),
                                 (500, "decision.api_status")):
            detail = {"id": "decision.api_status", "message": f"HTTP {status}: max_tokens exceeded"}
            with self.subTest(status=status), mock.patch.object(decidr_client, "send", return_value={"error": detail}):
                result = judge.call_jev({"model": "jev-latest"}, "", 30)
            self.assertEqual((result.error.code, result.error.data), (expected, detail))

    def test_policy_forwards_injected_logger_and_cancellation(self):
        body = {"model": "jev-latest", "state": {"item": {"text": "A"}},
                "questions": {"q": {"type": "noul"}}}
        logger, cancel = object(), object()
        response = {"response": {"answers": {"q": {"type": "noul", "noul": 0.8}}}}
        with mock.patch.object(decidr_client, "send", return_value=response) as send:
            result = judge.judge_with_policy(body, "", 30, 10000, 1, body["questions"],
                                             general_log=logger, cancel=cancel)
        self.assertIsInstance(result, judge.Ok)
        self.assertIs(send.call_args.kwargs["general_log"], logger)
        self.assertIs(send.call_args.kwargs["cancel"], cancel)

    def test_installed_judge_correlates_batch_results_by_position(self):
        from test_jev_judge import Judged, Transport, anchor, plan_answers
        lines = [json.dumps({"position": 1, "response": {"model": "jev", "answers": plan_answers(comp="no")}}),
                 json.dumps({"position": 0, "response": {"model": "jev", "answers": plan_answers()}})]
        batch = mock.Mock(return_value=lines)
        wheel = types.SimpleNamespace(send_batch=batch)
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(sys.modules, {"sc_agent": wheel}):
            result = Judged(directory, Transport(), anchors=[anchor(), anchor("ANC-002")], extra_args=["--no-confirm"], batch_stub=False)
        self.assertEqual(result.code, 0)
        self.assertEqual({row["anchor_id"]: row["verdict"] for row in result.run["results"]},
                         {"ANC-001": "satisfied", "ANC-002": "not_addressed"})
        self.assertEqual(len(batch.call_args.args[0]), 2)
        batch.assert_called_once()

    def test_batch_failure_preserves_successful_anchor_and_provider_details(self):
        from test_jev_judge import Judged, Transport, anchor, plan_answers
        detail = {"id": "decision.api_status", "message": "HTTP 529 busy"}
        lines = [json.dumps({"position": 1, "response": {"model": "jev", "answers": plan_answers()}}),
                 json.dumps({"position": 0, "error": detail})]
        batch = mock.Mock(return_value=lines)
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(sys.modules, {"sc_agent": types.SimpleNamespace(send_batch=batch)}):
            result = Judged(directory, Transport(), anchors=[anchor(), anchor("ANC-002")], extra_args=["--no-confirm"], batch_stub=False)
        self.assertEqual(result.code, 2)
        rows = {row["anchor_id"]: row for row in result.run["results"]}
        self.assertEqual((rows["ANC-001"]["verdict"], rows["ANC-002"]["verdict"]), ("error", "satisfied"))
        self.assertEqual(rows["ANC-001"]["error"]["data"], detail)
        batch.assert_called_once()

    def test_batch_context_error_shortens_only_the_affected_development_item(self):
        from test_jev_judge import Judged, Transport, anchor, dev_answers
        lines = [json.dumps({"position": 1, "response": {"model": "jev", "answers": dev_answers()}}),
                 json.dumps({"position": 0, "error": {"id": "decision.api_status", "message": "HTTP 400 max_tokens exceeded"}})]
        batch = mock.Mock(return_value=lines)
        transport = Transport(gate="dev")
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(sys.modules, {"sc_agent": types.SimpleNamespace(send_batch=batch)}):
            result = Judged(directory, transport, gate="dev", item_text="z" * 3000,
                            anchors=[anchor(), anchor("ANC-002")],
                            extra_args=["--min-item-chars", "1000", "--no-confirm"], batch_stub=False)
        self.assertEqual(result.code, 0)
        rows = {row["anchor_id"]: row for row in result.run["results"]}
        self.assertTrue(rows["ANC-001"]["item_shortened"])
        self.assertEqual((rows["ANC-001"]["attempts"], rows["ANC-002"]["attempts"]), (2, 1))
        self.assertEqual(len(transport.bodies), 1)
        self.assertEqual(transport.bodies[0]["state"]["anchor"]["id"], "ANC-001")

    def test_batch_command_failure_preserves_the_partial_run(self):
        from test_jev_judge import Judged, Transport, anchor
        batch = mock.Mock(side_effect=ValueError("controlled malformed batch result"))
        transport = Transport()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(decidr_client, "send_batch", batch):
            result = Judged(directory, transport, anchors=[anchor(), anchor("ANC-002")],
                            extra_args=["--no-confirm"], batch_stub=False)
        self.assertEqual(result.code, 2)
        self.assertEqual({row["anchor_id"]: row["verdict"] for row in result.run["results"]},
                         {"ANC-001": "error", "ANC-002": "error"})
        self.assertEqual(result.out["error"]["code"], "JEV.RESPONSE_INVALID")
        self.assertEqual(transport.bodies, [])
        batch.assert_called_once()

    def test_wheel_credential_error_keeps_chain_and_aborts_as_auth(self):
        class SagError(Exception):
            pass
        for key_error in ("secrets.key_missing", "secrets.key_malformed"):
            detail = {"id": "decidr.secrets", "cause": {"id": key_error, "message": "credential error"}}
            wheel = types.SimpleNamespace(SagError=SagError)
            with self.subTest(key_error=key_error), mock.patch.dict(sys.modules, {"sc_agent": wheel}), \
                    mock.patch.object(decidr_client, "send", side_effect=SagError("decidr.secrets", "credential error", json.dumps(detail))):
                result = judge.call_jev({"model": "jev-latest"}, "", 30)
            self.assertIsInstance(result, judge.Err)
            self.assertEqual(result.error.code, "AUTH.CREDENTIALS")
            self.assertEqual(result.error.data, detail)

    def test_denied_consent_does_not_resolve_credentials_or_send(self):
        denied = judge.fail("POLICY.REMOTE_JUDGE_DISABLED", "denied")
        with mock.patch.object(judge, "remote_judge_consent", return_value=denied), \
                mock.patch.object(decidr_client, "send") as send:
            result = judge.remote_preflight(object(), "text")
        self.assertIs(result, denied)
        send.assert_not_called()

    def test_invalid_response_ids_fail_without_a_second_send(self):
        body = {"model": "jev-latest", "state": {"item": {"text": "A"}},
                "questions": {"q": {"type": "noul"}}}
        with mock.patch.object(decidr_client, "send", return_value={"response": {"answers": {}}}) as send:
            result = judge.judge_with_policy(body, "", 30, 10000, 1, body["questions"])
        self.assertIsInstance(result, judge.Err)
        self.assertEqual(result.error.code, "JEV.RESPONSE_INVALID")
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
