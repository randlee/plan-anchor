"""Tests for the Result<T, E> helpers and how expected failures propagate through the scripts.

result.py is the shared discriminated union (Ok / Err, ToolError, err). The
scripts return Err for every expected failure; only their CLI boundary turns
an Err into a JSON envelope and an exit code. These tests pin both halves.
Standard library only.
"""
import contextlib
import dataclasses
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
from layout_support import SCRIPTS  # noqa: E402 - the scripts as installed for one tracker
sys.path.insert(0, str(SCRIPTS))
import anchor_runner_contract as rc  # noqa: E402
import anchor_tuning_contract as tc  # noqa: E402
import jev_judge as jj  # noqa: E402
import result  # noqa: E402
from result import Err, Ok, ToolError, err  # noqa: E402


class ResultHelperTests(unittest.TestCase):
    def test_ok_and_err_are_discriminated_by_the_ok_literal(self):
        self.assertIs(Ok(1).ok, True)
        self.assertIs(Err("x").ok, False)
        self.assertEqual(Ok(1).value, 1)
        self.assertEqual(Err("x").error, "x")
        self.assertNotIsInstance(Ok(1), Err)
        self.assertNotIsInstance(Err("x"), Ok)

    def test_variants_are_frozen_value_objects(self):
        self.assertEqual(Ok([1]), Ok([1]))
        self.assertNotEqual(Ok(1), Err(1))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            Ok(1).value = 2
        with self.assertRaises(TypeError):
            Ok(1, ok=False)  # the discriminant is not settable

    def test_tool_error_envelope_and_err_helper(self):
        made = err("CODE.X", "went wrong", "do this", {"k": 1})
        self.assertIsInstance(made, Err)
        self.assertEqual(made.error, ToolError("CODE.X", "went wrong", "do this", {"k": 1}))
        self.assertEqual(list(made.error.to_json().items()),
                         [("code", "CODE.X"), ("message", "went wrong"), ("recoverable", False), ("suggested_action", "do this")])
        self.assertIsNone(err("C", "m").error.to_json()["suggested_action"])

    def test_scripts_share_one_result_module(self):
        for module in (rc, tc, jj):
            self.assertIs(module.Ok, result.Ok)
            self.assertIs(module.Err, result.Err)


class ScriptErrValueTests(unittest.TestCase):
    """Expected failures come back as Err values, not exceptions."""

    def test_runner_contract(self):
        dup = rc.parse_single_fenced_json('```json\n{"a": 1, "a": 2}\n```', kind="request")
        self.assertEqual(dup.error, ToolError("ENVELOPE.DUPLICATE_KEY", "JSON object contains a duplicate key"))
        self.assertEqual(rc.validate_runtime([]).error.code, "ENVELOPE.RUNTIME")

    def test_tuning_contract(self):
        checked = tc.reject_forbidden({"x": [{"desired_verdict": 1}]})
        self.assertIsInstance(checked, Err)
        self.assertEqual(tc.render_error(checked.error), "VALIDATION.FORBIDDEN_FIELD: $.x[0].desired_verdict")
        self.assertIs(tc.reject_forbidden({"x": [1]}), tc.OK)

    def test_jev_judge(self):
        missing = jj.load_json("/nonexistent/x.json", "thing")
        self.assertEqual((missing.error.code, missing.error.message), ("INPUT.MISSING", "thing not found: '/nonexistent/x.json'"))
        self.assertEqual(jj.check_api_key("").error.code, "AUTH.CREDENTIALS")
        self.assertEqual(jj.check_api_key("k"), Ok(None))

    def test_judge_error_is_a_value_not_an_exception(self):
        self.assertFalse(issubclass(jj.JudgeError, BaseException))
        e = jj.JudgeError("C.X", "msg", recoverable=True, action="act")
        self.assertEqual(str(e), "msg")
        self.assertEqual(jj.fail("C.X", "msg").error.to_json()["error"]["message"], "msg")


class JevPropagationTests(unittest.TestCase):
    """An Err from the transport travels up unchanged, with its attempt bookkeeping, and becomes one envelope in main."""

    def body(self):
        return {"model": "m", "questions": {}, "state": {"anchor": {"statement": "s"}}}

    def test_non_transient_err_is_returned_with_meta(self):
        refused = jj.JudgeError("AUTH.CREDENTIALS", "Jev HTTP 401", status=401)
        with mock.patch.object(jj, "call_jev", return_value=Err(refused)) as called:
            out = jj.judge_with_policy(self.body(), "k", 1.0, 24000, 2000, {})
        self.assertIs(out.error, refused)
        self.assertEqual(out.error.meta["attempts"], 1)
        self.assertEqual(called.call_count, 1)

    def test_transient_err_is_retried_then_returned(self):
        down = jj.JudgeError("JEV.NETWORK", "down", recoverable=True)
        sleeps = []
        with mock.patch.object(jj, "call_jev", return_value=Err(down)) as called, mock.patch.object(jj, "_sleep", sleeps.append):
            out = jj.judge_with_policy(self.body(), "k", 1.0, 24000, 2000, {})
        self.assertIs(out.error, down)
        self.assertEqual((called.call_count, out.error.meta["attempts"], len(sleeps)), (jj.MAX_ATTEMPTS, jj.MAX_ATTEMPTS, jj.MAX_ATTEMPTS - 1))

    def test_invalid_ok_response_becomes_err(self):
        with mock.patch.object(jj, "call_jev", return_value=Ok({"answers": []})), mock.patch.object(jj, "_sleep", lambda s: None):
            out = jj.judge_with_policy(self.body(), "k", 1.0, 24000, 2000, {})
        self.assertEqual(out.error.code, "JEV.RESPONSE_INVALID")

    def run_main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = jj.main(argv)
        return code, json.loads(buf.getvalue())

    def test_main_emits_an_err_as_the_envelope_and_exits_2(self):
        code, out = self.run_main(["validate", "--anchors", "/nonexistent/anchors.json"])
        self.assertEqual(code, 2)
        self.assertEqual(set(out), {"success", "data", "error"})
        self.assertEqual((out["success"], out["error"]["code"]), (False, "INPUT.MISSING"))

    def test_main_reports_an_unexpected_exception_as_script_internal(self):
        with mock.patch.object(jj, "load_record", side_effect=RuntimeError("boom")):
            code, out = self.run_main(["validate", "--anchors", "x"])
        self.assertEqual((code, out["error"]["code"], out["error"]["message"]), (2, "SCRIPT.INTERNAL", "RuntimeError: boom"))


if __name__ == "__main__":
    unittest.main()
