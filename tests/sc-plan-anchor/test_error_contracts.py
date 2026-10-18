"""Characterization tests for the scripts' typed error contracts.

Pinned before the Result<T, E> refactor so it is provably behaviour-preserving:
every case asserts the exact JSON envelope (code, message, recoverable,
suggested_action, data) and exit code a caller sees. The Jev transport is
exercised at the urllib boundary, so these tests do not depend on how
expected failures travel inside the scripts. Standard library only; no
network is touched.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins" / "sc-plan-anchor" / "skills" / "plan-anchoring"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))
import anchor_runner_contract as rc  # noqa: E402
import jev_judge as jj  # noqa: E402

STATEMENT = "The runtime crates are created by copying the legacy repo's runtime crates and deleting the legacy-specific modules; no runtime crate is written from scratch."
QUOTE = "copy the libraries from the legacy repo as the starting point and remove the legacy-specific code"
OPTIONS = ("yes", "no", "unclear")


def answer(choice, p=0.9, options=OPTIONS):
    rest = round((1 - p) / (len(options) - 1), 4)
    return {"type": "choice", "choice": choice, "confidence": p, "probabilities": {o: (p if o == choice else rest) for o in options}}


def plan_answers(comp="yes"):
    return {"relevant": answer("yes"), "addressed": answer(comp), "contradicted": answer("no")}


def rubric_answers(choice="yes"):
    return {q: answer(choice, options=("no", "unclear", "yes")) for q in jj.RUBRIC_QUESTIONS}


def anchor(aid="ANC-001", status="locked", statement=STATEMENT, quote=QUOTE, **extra):
    rec = {"id": aid, "source_type": "ANC", "source_ref": None, "statement": statement, "quote": quote,
           "stated_by": "the user", "stated_at": "2026-10-09", "context": "planning session", "summary": "",
           "scope": "the runtime crates", "deterministic_check": "", "fixtures": {"pass": [], "fail": []},
           "question_overrides": {}, "version": 1, "status": status, "promoted_to": None,
           "beads": {"anchor": None, "plan_questions": None, "dev_questions": None}, "history": []}
    rec.update(extra)
    return rec


def record(*anchors):
    return {"schema": "plan-anchoring/anchors/1", "plan": "phase-current", "intent_ref": "intent.md", "anchors": list(anchors)}


def run_file(gate="plan", item="ex-42", results=None):
    return {"schema": "plan-anchoring/run/1", "run_id": f"{gate}-x", "gate": gate, "created_at": "2026-10-10T00:00:00+00:00",
            "item": {"id": item, "title": "", "chars": 1}, "threshold": 0.6, "dry_run": False,
            "results": results if results is not None else [{"anchor_id": "ANC-001", "verdict": "satisfied"}],
            "summary": {"pass": True}}


class Workspace:
    """A temporary working directory holding the given files; paths in argv are relative to it."""

    def __init__(self, files=None):
        self.td = tempfile.TemporaryDirectory()
        self.path = Path(self.td.name).resolve()
        for rel, content in (files or {}).items():
            p = self.path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                p.write_bytes(content)
            elif isinstance(content, str):
                p.write_text(content, encoding="utf-8")
            else:
                p.write_text(json.dumps(content), encoding="utf-8")

    def __enter__(self):
        self.cwd = os.getcwd()
        os.chdir(self.path)
        return self

    def __exit__(self, *exc):
        os.chdir(self.cwd)
        self.td.cleanup()


def call_main(main, argv, *, env=None, stdin=None):
    buf = io.StringIO()
    environment = {"PATH": os.environ.get("PATH", ""), **(env or {})}
    with mock.patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(buf), \
            mock.patch.object(sys, "stdin", io.StringIO(stdin or "")):
        code = main(argv)
    return code, json.loads(buf.getvalue())


class FakeResponse:
    def __init__(self, raw: bytes):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=-1):
        return self.raw[:n] if n >= 0 else self.raw


def http_error(status, body=b"", headers=None):
    return urllib.error.HTTPError("http://jev", status, "x", headers or {}, io.BytesIO(body))


LIVE = {"TYPESAFE_API_KEY": "sk-test-0001"}
LOCKED = record(anchor())
ITEM = "Sprint 2 copies the legacy runtime crates.\n"
JUDGE = ["judge", "--anchors", "anchors.json", "--gate", "plan", "--all", "--item-id", "ex-42", "--item-file", "item.txt", "--run-dir", "runs"]
ADD = ["add", "--anchors", "anchors.json", "--stated-at", "2026-10-09"]

# name: (argv, files, env, stdin, exit code, expected error object or None, expected data)
JEV_CASES = {
    "auth_missing_key": (JUDGE, {"anchors.json": LOCKED, "item.txt": ITEM}, {}, None, 2,
                         {"code": "AUTH.CREDENTIALS", "message": "TYPESAFE_API_KEY is not set", "recoverable": False,
                          "suggested_action": "Export TYPESAFE_API_KEY, or use --dry-run / --answers-file."}, None),
    "auth_bad_format": (JUDGE, {"anchors.json": LOCKED, "item.txt": ITEM}, {"TYPESAFE_API_KEY": "ské"}, None, 2,
                        {"code": "AUTH.CREDENTIALS", "message": "TYPESAFE_API_KEY has invalid formatting (whitespace, control or non-ASCII characters)",
                         "recoverable": False, "suggested_action": "Re-export TYPESAFE_API_KEY with the key exactly as issued."}, None),
    # A repository (".git") whose settings file does not record allow_remote_judge. The workspace is cwd. The key must
    # not be a substring of the message: output redacts it.
    "policy_disabled": (JUDGE, {"anchors.json": LOCKED, "item.txt": ITEM, ".git/HEAD": "ref: refs/heads/main\n"}, LIVE, None, 2,
                        {"code": "POLICY.REMOTE_JUDGE_DISABLED",
                         "message": "Sending plan text to TypeSafe is disabled. The anchor statement and the item text would leave this machine. "
                                    ".sc/plan-anchor/settings.yaml does not set allow_remote_judge.",
                         "recoverable": False,
                         "suggested_action": "Ask the user once whether plan text may be sent to TypeSafe (Jev) for judging, record the answer with "
                                             "`python3 scripts/plan_anchor_settings.py set allow_remote_judge true|false`, and commit "
                                             ".sc/plan-anchor/settings.yaml. Never infer consent from existing run files or past runs. "
                                             "Use --dry-run to inspect the request instead."}, None),
    # The variable that used to opt in has no effect any more.
    "policy_env_var_ignored": (JUDGE, {"anchors.json": LOCKED, "item.txt": ITEM, ".git/HEAD": "ref: refs/heads/main\n"},
                               dict(LIVE, PLAN_ANCHOR_ALLOW_REMOTE_JUDGE="1"), None, 2,
                               {"code": "POLICY.REMOTE_JUDGE_DISABLED",
                                "message": "Sending plan text to TypeSafe is disabled. The anchor statement and the item text would leave this machine. "
                                           ".sc/plan-anchor/settings.yaml does not set allow_remote_judge.",
                                "recoverable": False,
                                "suggested_action": "Ask the user once whether plan text may be sent to TypeSafe (Jev) for judging, record the answer with "
                                                    "`python3 scripts/plan_anchor_settings.py set allow_remote_judge true|false`, and commit "
                                                    ".sc/plan-anchor/settings.yaml. Never infer consent from existing run files or past runs. "
                                                    "Use --dry-run to inspect the request instead."}, None),
    "allow_remote_flag_removed": (JUDGE + ["--allow-remote"], {"anchors.json": LOCKED, "item.txt": ITEM}, {"TYPESAFE_API_KEY": "sk"}, None, 2,
                                  {"code": "VALIDATION.INPUT", "message": "jev_judge.py: unrecognized arguments: --allow-remote",
                                   "recoverable": False,
                                   "suggested_action": "Run 'jev_judge.py <subcommand> --help' for the accepted arguments."}, None),
    "validation_anchors": (JUDGE + ["--dry-run"], {"anchors.json": record(anchor(statement="")), "item.txt": ITEM}, {}, None, 2,
                           {"code": "VALIDATION.ANCHORS", "message": "anchors.json has problems: ANC-001: statement is empty", "recoverable": True,
                            "suggested_action": "Run `jev_judge.py validate` and fix the record first."}, None),
    "validation_input_threshold": (JUDGE + ["--dry-run", "--threshold", "1.5"], {"anchors.json": LOCKED, "item.txt": ITEM}, {}, None, 2,
                                   {"code": "VALIDATION.INPUT", "message": "--threshold must be between 0 and 1, got 1.5", "recoverable": False,
                                    "suggested_action": ""}, None),
    "validation_input_positive": (JUDGE + ["--dry-run", "--max-code-lines", "0"], {"anchors.json": LOCKED, "item.txt": ITEM}, {}, None, 2,
                                  {"code": "VALIDATION.INPUT", "message": "--max-code-lines must be a positive integer, got 0", "recoverable": False,
                                   "suggested_action": ""}, None),
    "questions_roles": (JUDGE + ["--dry-run", "--overrides-file", "o.json"],
                        {"anchors.json": LOCKED, "item.txt": ITEM, "o.json": {"ANC-001": {"roles": {"compliance": "covers"}}}}, {}, None, 2,
                        {"code": "QUESTIONS.ROLES", "message": "question set for ANC-001 after overrides must map role 'compliance' to a question id in the set",
                         "recoverable": False, "suggested_action": "See references/verdict-gating.md for the role contract."}, None),
    "anchor_unknown": (["update", "--anchors", "anchors.json", "--id", "ANC-404", "--scope", "x"], {"anchors.json": LOCKED}, {}, None, 2,
                       {"code": "ANCHOR.UNKNOWN", "message": "No anchor with id ANC-404", "recoverable": False,
                        "suggested_action": "Check anchors.json for the exact ID."}, None),
    "anchor_duplicate": (ADD + ["--statement", "Every command must emit JSON.", "--source-type", "REQ", "--source-ref", "REQ-014"],
                         {"anchors.json": record(anchor("REQ-014", source_type="REQ", source_ref="REQ-014"))}, {}, None, 2,
                         {"code": "ANCHOR.DUPLICATE", "message": "REQ-014 already recorded", "recoverable": False, "suggested_action": ""}, None),
    "anchor_none": (JUDGE + ["--dry-run"], {"anchors.json": record(anchor(status="proposed")), "item.txt": ITEM}, {}, None, 2,
                    {"code": "ANCHOR.NONE", "message": "no locked anchors to judge", "recoverable": False,
                     "suggested_action": "Lock at least one anchor, or pass --anchor."}, None),
    "anchor_not_locked": (["judge", "--anchors", "anchors.json", "--gate", "plan", "--anchor", "ANC-001", "--item-id", "x", "--item-file", "item.txt"],
                          {"anchors.json": record(anchor(status="proposed")), "item.txt": ITEM}, {}, None, 2,
                          {"code": "ANCHOR.NOT_LOCKED", "message": "anchors not locked or promoted: ANC-001", "recoverable": False,
                           "suggested_action": "Lock the anchor first, or pass --include-unlocked to judge a proposed or retired anchor deliberately."}, None),
    "anchor_duplicate_candidate": (ADD + ["--statement", STATEMENT, "--quote", "other words"], {"anchors.json": LOCKED}, {}, None, 2,
                                   {"code": "ANCHOR.DUPLICATE_CANDIDATE", "message": "the new anchor looks like an existing one: ANC-001 (jaccard 1.0, statement/statement)",
                                    "recoverable": True,
                                    "suggested_action": "Update ANC-001 instead (or retire it with --replaced-by), or pass --allow-similar if it is really a different constraint."}, None),
    "anchor_not_testable": (ADD + ["--statement", "Every command must emit JSON.", "--quote", "json", "--rubric", "--answers-file", "a.json"],
                            {"a.json": {"*": rubric_answers("no")}}, {}, None, 2,
                            {"code": "ANCHOR.NOT_TESTABLE",
                             "message": "the statement did not pass the testability rubric (needs_work): single_constraint, observable, faithful, scoped, self_contained",
                             "recoverable": True,
                             "suggested_action": "Reword the statement so each failing criterion holds (see references/anchor-capture.md), re-run `rubric --statement ... --quote ...`, or pass --allow-untestable to record it anyway."}, None),
    "anchor_lint": (ADD + ["--statement", "We should keep things clean.", "--quote", "x y z", "--strict"], {}, {}, None, 2,
                    {"code": "ANCHOR.LINT",
                     "message": "statement has testability warnings: hedged wording; state the requirement; written as speech, not as a requirement; not phrased as a testable requirement; vague term; name the observable outcome",
                     "recoverable": True,
                     "suggested_action": "Reword the statement (see references/anchor-capture.md), or drop --strict to record it anyway."}, None),
    "verbatim_statement": (ADD + ["--statement", "Copy it must.", "--quote", "copy it must"], {}, {}, None, 2,
                           {"code": "VALIDATION.INPUT", "message": "statement is the verbatim quote; write a testable anchor (see references/anchor-capture.md)",
                            "recoverable": True,
                            "suggested_action": "Write the statement as a testable requirement in the orchestrator's words; keep the user's words in --quote."}, None),
    "input_missing": (["validate", "--anchors", "missing.json"], {}, {}, None, 2,
                      {"code": "INPUT.MISSING", "message": "anchors.json not found: 'missing.json'", "recoverable": False,
                       "suggested_action": "Pass the path of an existing file for the anchors.json."}, None),
    "input_missing_directory": (["validate", "--anchors", "dir"], {"dir/x": "1"}, {}, None, 2,
                                {"code": "INPUT.MISSING", "message": "anchors.json not found: 'dir' (not a regular file)", "recoverable": False,
                                 "suggested_action": "Pass the path of an existing file for the anchors.json."}, None),
    "input_malformed_json": (["validate", "--anchors", "anchors.json"], {"anchors.json": "{"}, {}, None, 2,
                             {"code": "INPUT.MALFORMED", "message": "anchors.json is not valid JSON: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
                              "recoverable": False, "suggested_action": "Fix the JSON in anchors.json."}, None),
    "input_malformed_stdin": (["validate", "--anchors", "-"], {}, {}, "{", 2,
                              {"code": "INPUT.MALFORMED", "message": "anchors.json on stdin is not valid JSON: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
                               "recoverable": False, "suggested_action": ""}, None),
    "input_malformed_shape": (["validate", "--anchors", "anchors.json"], {"anchors.json": [1]}, {}, None, 2,
                              {"code": "INPUT.MALFORMED", "message": "anchors.json must be a JSON object", "recoverable": False,
                               "suggested_action": "See references/anchor-document.md for the schema."}, None),
    "input_empty": (JUDGE + ["--dry-run"], {"anchors.json": LOCKED, "item.txt": " \n"}, {}, None, 2,
                    {"code": "INPUT.EMPTY", "message": "item text is empty", "recoverable": False,
                     "suggested_action": "Pass the bead or work description via --item-file."}, None),
    "fixture_missing": (JUDGE + ["--answers-file", "a.json"], {"anchors.json": LOCKED, "item.txt": ITEM, "a.json": {"other": plan_answers()}}, {}, None, 1,
                        None, None),
    "fixture_none": (["check-fixtures", "--anchors", "anchors.json", "--gate", "plan", "--all", "--dry-run"], {"anchors.json": LOCKED}, {}, None, 2,
                     {"code": "FIXTURE.NONE", "message": "no fixture sentences recorded on the selected anchors", "recoverable": False,
                      "suggested_action": "Add fixtures with `update --id ANC-NNN --fixture-pass ... --fixture-fail ...`."}, None),
    "runs_none": (["coverage", "--runs", "runs"], {"runs/x.txt": "x"}, {}, None, 2,
                  {"code": "RUNS.NONE", "message": "no run files found", "recoverable": False,
                   "suggested_action": "Run `judge` first, or check the --runs path."}, None),
    "runs_mismatch_gate": (["diff", "--prev", "p.json", "--next", "n.json"], {"p.json": run_file(), "n.json": run_file(gate="dev")}, {}, None, 2,
                           {"code": "RUNS.MISMATCH", "message": "runs are for different gates", "recoverable": False, "suggested_action": ""}, None),
    "runs_mismatch_item": (["diff", "--prev", "p.json", "--next", "n.json"], {"p.json": run_file(), "n.json": run_file(item="ex-9")}, {}, None, 2,
                           {"code": "RUNS.MISMATCH", "message": "runs are for different items (ex-42 vs ex-9)", "recoverable": False,
                            "suggested_action": "Diff two runs of the same bead or sprint."}, None),
    "script_internal": (["coverage", "--runs", "runs"], {"runs/a.json": run_file(results=[{"verdict": "x"}])}, {}, None, 2,
                        {"code": "SCRIPT.INTERNAL", "message": "KeyError: 'anchor_id'", "recoverable": False,
                         "suggested_action": "Report this with the command line; check the JSON inputs against references/anchor-document.md."}, None),
    "plan_too_large": (JUDGE + ["--dry-run", "--max-item-chars", "100"], {"anchors.json": LOCKED, "item.txt": "# T\n\n## Description\n\n" + "prose " * 40}, {}, None, 2,
                       {"code": "PLAN.TOO_LARGE",
                        "message": "plan bead ex-42 is 261 characters after long code was reduced to signatures (261 prose, 0 code; by section: Description 257, (title) 5); the plan-gate item budget is --max-item-chars 100. A reasonable plan bead fits in one Jev request; this one is asking too much",
                        "recoverable": False,
                        "suggested_action": "Oversize is a symptom; judge its cause before changing the bead. First remove work that no anchor, requirement or user-approved issue asks for and the change does not need. Then cut prose and process ceremony that does not serve a deliverable. Split only approved work that is still too large after that. Never split, trim or raise a limit just to pass the gate. See references/plan-size-and-shape.md"},
                       {"item_id": "ex-42", "size": {"sections": {"(title)": 5, "Description": 257}, "code_chars": 0, "prose_chars": 261},
                        "shape": {"chars": 261, "chars_after_reduction": 261, "code_reduced": {"blocks": 0, "lines": 0},
                                  "sections": {"title": 5, "description": 257}, "code_chars": 0, "prose_chars": 261, "code_lines": 0,
                                  "prose_lines": 2, "fenced_blocks": 0, "bullets": 0, "table_rows": 0,
                                  "references": {"github": [], "req": [], "adr": [], "anc": []}, "no_issue_reference": True,
                                  "chars_before_reduction": 261}}),
    "validation_path": (["agent-preflight", "--workspace-root", ".", "--script", str(SCRIPTS / "jev_judge.py"), "--anchors", ""], {}, {}, None, 2,
                        {"code": "VALIDATION.PATH", "message": "anchors file is empty", "recoverable": False,
                         "suggested_action": "Pass a anchors file inside the repository."}, None),
    "validation_id": (["agent-preflight", "--workspace-root", ".", "--script", str(SCRIPTS / "jev_judge.py"), "--anchors", "anchors.json", "--identifier", "../x"],
                      {"anchors.json": LOCKED}, {}, None, 2,
                      {"code": "VALIDATION.ID", "message": "unsafe agent identifier: '../x'", "recoverable": False,
                       "suggested_action": "Use 1-128 letters, digits, dots, underscores, colons or hyphens; do not use paths or whitespace."}, None),
}


class JevJudgeErrorContracts(unittest.TestCase):
    def test_every_offline_error_code_keeps_its_exact_envelope(self):
        for name, (argv, files, env, stdin, exit_code, error, data) in JEV_CASES.items():
            with self.subTest(name), Workspace(files):
                code, out = call_main(jj.main, list(argv), env=env, stdin=stdin)
                self.assertEqual(code, exit_code)
                if error is None:
                    continue
                self.assertEqual(out, {"success": False, "data": data, "error": error})

    def test_fixture_missing_is_a_per_anchor_error_verdict(self):
        argv, files, env, stdin, _, _, _ = JEV_CASES["fixture_missing"]
        with Workspace(files):
            code, out = call_main(jj.main, list(argv), env=env)
        result = out["data"]["results"][0]
        self.assertEqual((code, result["verdict"], result["attempts"]), (1, "error", 0))
        self.assertEqual(result["error"], {"code": "FIXTURE.MISSING", "message": "answers fixture has no entry for ANC-001 (or '*')",
                                           "recoverable": False, "suggested_action": ""})

    def test_validate_problems_and_lint_warnings_exit_one(self):
        with Workspace({"anchors.json": record(anchor(statement=""))}):
            code, out = call_main(jj.main, ["validate", "--anchors", "anchors.json"])
            self.assertEqual(code, 1)
            self.assertEqual(out["error"], {"code": "VALIDATION.ANCHORS", "message": "1 problem(s) in anchors.json", "recoverable": True,
                                            "suggested_action": "Fix the listed problems and re-run validate."})

    def test_non_numeric_flag_exits_two_with_json(self):
        for flag, value, kind in (("--max-item-chars", "lots", "int"), ("--max-code-lines", "8.5", "int"), ("--threshold", "high", "float")):
            proc = subprocess.run([sys.executable, str(SCRIPTS / "jev_judge.py"), "judge", "--anchors", "x", "--gate", "plan", "--all",
                                   "--item-id", "ex-1", "--item-text", "t", "--dry-run", flag, value],
                                  capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 2, flag)
            self.assertEqual(json.loads(proc.stdout), {"success": False, "data": None, "error": {
                "code": "VALIDATION.INPUT", "message": f"jev_judge.py judge: argument {flag}: invalid {kind} value: {value!r}",
                "recoverable": False, "suggested_action": "Run 'jev_judge.py <subcommand> --help' for the accepted arguments."}})


class JevTransportErrorContracts(unittest.TestCase):
    """call_jev and its retry policy, driven through urllib so the internal error channel is not assumed."""

    def judge(self, responses, extra=(), gate="plan", item=ITEM):
        sleeps = []
        with Workspace({"anchors.json": LOCKED, "item.txt": item}), \
                mock.patch.object(jj.urllib.request, "urlopen", side_effect=list(responses)) as opened, \
                mock.patch.object(jj, "_sleep", sleeps.append), \
                mock.patch.object(jj, "remote_judge_consent", return_value=jj.Ok(None)):
            argv = ["judge", "--anchors", "anchors.json", "--gate", gate, "--all", "--item-id", "ex-42", "--item-file", "item.txt",
                    "--run-dir", "runs", "--no-confirm", *extra]
            code, out = call_main(jj.main, argv, env=LIVE)
        return code, out, opened.call_count, sleeps

    def ok_response(self, comp="yes"):
        return FakeResponse(json.dumps({"model": "jev-x", "answers": plan_answers(comp)}).encode("utf-8"))

    def test_401_aborts_the_run_with_body_withheld(self):
        code, out, calls, _ = self.judge([http_error(401, b"Bearer sk-test-0001 is wrong")])
        self.assertEqual((code, calls), (2, 1))
        self.assertEqual(out, {"success": False, "data": None, "error": {
            "code": "AUTH.CREDENTIALS", "message": "Jev HTTP 401; response body withheld", "recoverable": False,
            "suggested_action": "Check TYPESAFE_API_KEY."}})

    def test_transient_codes_retry_three_times_then_record_an_error_verdict(self):
        cases = (
            (http_error(429, headers={"Retry-After": "7"}), "JEV.RATE_LIMITED", "Jev HTTP 429; response body withheld", [7.0, 2.0]),
            (http_error(529), "JEV.OVERLOADED", "Jev HTTP 529; response body withheld", [1.0, 2.0]),
            (http_error(503), "JEV.HTTP", "Jev HTTP 503; response body withheld", [1.0, 2.0]),
            (urllib.error.URLError("refused"), "JEV.NETWORK", "Could not reach Jev: refused", [1.0, 2.0]),
            (ConnectionResetError("reset"), "JEV.NETWORK", "Jev connection failed: ConnectionResetError: reset", [1.0, 2.0]),
            (FakeResponse(b"not json"), "JEV.RESPONSE_INVALID", "Jev response was not JSON", [1.0, 2.0]),
            (FakeResponse(b"[1]"), "JEV.RESPONSE_INVALID", "Jev response was not a JSON object", [1.0, 2.0]),
            (FakeResponse(b"x" * (jj.MAX_RESPONSE_BYTES + 1)), "JEV.RESPONSE_INVALID", "Jev response exceeded the size limit", [1.0, 2.0]),
            (FakeResponse(b'{"answers": {}}'), "JEV.RESPONSE_INVALID",
             "Jev answer ids differ from the questions (missing ['addressed', 'contradicted', 'relevant'], unexpected [])", [1.0, 2.0]),
        )
        for failure, error_code, message, delays in cases:
            with self.subTest(error_code=error_code, message=message):
                code, out, calls, sleeps = self.judge([failure, failure, failure])
                result = out["data"]["results"][0]
                self.assertEqual((code, calls, sleeps, result["verdict"], result["attempts"]), (1, 3, delays, "error", 3))
                self.assertEqual((result["error"]["code"], result["error"]["message"], result["error"]["recoverable"]), (error_code, message, True))

    def test_transient_failure_then_success_passes(self):
        code, out, calls, sleeps = self.judge([http_error(500), self.ok_response()])
        self.assertEqual((code, calls, sleeps, out["data"]["results"][0]["verdict"], out["data"]["results"][0]["attempts"]), (0, 2, [1.0], "satisfied", 2))

    def test_non_transient_http_errors_are_recorded_without_retry(self):
        code, out, calls, _ = self.judge([http_error(422, b"questions.addressed is invalid")])
        self.assertEqual((code, calls), (1, 1))
        self.assertEqual(out["data"]["results"][0]["error"], {"code": "JEV.VALIDATION", "message": "Jev HTTP 422: questions.addressed is invalid",
                                                               "recoverable": False, "suggested_action": "Fix the named field; usually a malformed question override."})
        code, out, calls, _ = self.judge([http_error(418, b"teapot")])
        self.assertEqual((code, calls), (1, 1))
        self.assertEqual(out["data"]["results"][0]["error"], {"code": "JEV.HTTP", "message": "Jev HTTP 418; response body withheld",
                                                               "recoverable": False, "suggested_action": "Check the request body."})

    def test_plan_gate_context_overflow_is_plan_too_large_and_dev_gate_shortens(self):
        code, out, calls, _ = self.judge([http_error(400, b"max_tokens exceeded")])
        error = out["data"]["results"][0]["error"]
        self.assertEqual((code, calls, error["code"], error["recoverable"]), (1, 1, "PLAN.TOO_LARGE", False))
        self.assertIn("Jev rejected it for context size (Jev HTTP 400: request exceeds the model's context window)", error["message"])
        self.assertEqual(error["data"]["item_id"], "ex-42")

        code, out, calls, _ = self.judge([http_error(400, b"max_tokens"), http_error(400, b"max_tokens")], gate="dev",
                                         extra=("--min-item-chars", "1000"), item="evidence " * 200)
        result = out["data"]["results"][0]
        self.assertEqual((code, calls, result["item_shortened"], result["attempts"]), (1, 2, True, 2))
        self.assertEqual(result["error"], {
            "code": "JEV.CONTEXT_EXCEEDED",
            "message": "Jev rejected the request for context size with the item at 1055 chars (floor --min-item-chars 1000): "
                       "Jev HTTP 400: request exceeds the model's context window",
            "recoverable": False,
            "suggested_action": "Shorten the evidence for this item: sprint report and PR body summaries, file names and counts only; or lower --min-item-chars."})

    def test_dry_run_request_that_cannot_fit_reports_context_exceeded(self):
        with Workspace({"anchors.json": LOCKED, "item.txt": "evidence " * 1000}):
            code, out = call_main(jj.main, ["judge", "--anchors", "anchors.json", "--gate", "dev", "--all", "--item-id", "ex-42", "--item-file", "item.txt",
                                            "--run-dir", "runs", "--dry-run", "--max-request-bytes", "1000", "--min-item-chars", "2000"])
        result = out["data"]["results"][0]
        self.assertEqual((code, result["explanation"]), (0, "dry run; request does not fit"))
        self.assertEqual(result["error"], {
            "code": "JEV.CONTEXT_EXCEEDED",
            "message": "request is 5727 bytes with the item at 2055 chars, over --max-request-bytes 1000; the item is already at --min-item-chars 2000",
            "recoverable": False,
            "suggested_action": "Shorten the evidence for this item (names, counts and summaries only), shorten the question overrides, or raise --max-request-bytes."})


def contract_error(code, message):
    return {"success": False, "data": None, "error": {"code": code, "message": message, "recoverable": False, "suggested_action": None}}


class RunnerContractErrorContracts(unittest.TestCase):
    def fence(self, files, kind="request", extra=()):
        with Workspace(files):
            return call_main(rc.main, ["validate-fence", "--kind", kind, "--file", "f.md", *extra])

    def test_fence_error_envelopes(self):
        runtime = {"agent": "anchor-tuning", "harness": "codex", "path": ".codex/agents/anchor-tuning.md", "version": "0.5.0",
                   "model": "sol", "sha256": "a" * 64}
        request = {"schema_version": "1.0.0", "runtime": runtime, "operation": "tune", "correlation_id": "c-1", "params": {}}

        def fenced(value):
            return "```json\n" + (value if isinstance(value, str) else json.dumps(value)) + "\n```"

        cases = (
            (fenced(request) + "\n" + fenced(request), contract_error("ENVELOPE.REQUEST_FENCE", "request must be exactly one fenced JSON object")),
            (fenced("{bad"), contract_error("ENVELOPE.REQUEST_JSON", "request JSON is malformed")),
            (fenced("[1]"), contract_error("ENVELOPE.REQUEST_JSON", "request JSON must be an object")),
            (fenced('{"x": {"a": 1, "a": 2}, bad}'), contract_error("ENVELOPE.DUPLICATE_KEY", "JSON object contains a duplicate key")),
            (fenced(dict(request, extra=1)), contract_error("ENVELOPE.REQUEST", "request must contain only the required top-level fields")),
            (fenced(dict(request, schema_version="2")), contract_error("ENVELOPE.VERSION", "request schema_version is unsupported")),
            (fenced(dict(request, operation="x")), contract_error("ENVELOPE.OPERATION", "request operation is unsupported")),
            (fenced(dict(request, correlation_id="../x")), contract_error("ENVELOPE.CORRELATION", "request correlation_id is invalid")),
            (fenced(dict(request, params=[])), contract_error("ENVELOPE.PARAMS", "request params must be an object")),
            (fenced(dict(request, runtime=dict(runtime, sha256="x"))), contract_error("ENVELOPE.RUNTIME", "runtime sha256 is invalid")),
            (fenced(dict(request, runtime=dict(runtime, path="a/../b"))), contract_error("ENVELOPE.RUNTIME", "runtime path must not traverse its plugin root")),
            (b"\xff", contract_error("SCRIPT.IO", "input could not be read")),
        )
        for text, expected in cases:
            with self.subTest(expected=expected["error"]["message"]):
                self.assertEqual(self.fence({"f.md": text}), (2, expected))
        self.assertEqual(self.fence({"f.md": fenced(request)}, kind="result"),
                         (2, contract_error("ENVELOPE.CORRELATION", "result validation requires correlation_id")))

    def test_resolve_error_envelopes(self):
        registry = 'agents:\n  anchor-tuning:\n    version: "0.5.0"\n    path: .codex/agents/anchor-tuning.md\n'
        agent = "---\nname: anchor-tuning\nversion: 0.5.0\nmodel: sol\n---\nbody\n"
        cases = (
            (registry + "   garbage\n", agent, contract_error("RUNTIME.REGISTRY", "agent registry is malformed")),
            (registry + "  anchor-tuning:\n", agent, contract_error("RUNTIME.REGISTRY", "agent registry has a duplicate identity")),
            ("agents:\n  other:\n    version: 1\n    path: x\n", agent, contract_error("RUNTIME.REGISTRY", "agent registry lacks the requested agent")),
            ("agents:\n  anchor-tuning:\n    version: 1\n", agent, contract_error("RUNTIME.REGISTRY", "agent registry entry has an invalid shape")),
            (registry.replace("anchor-tuning.md", "nope.md"), agent, contract_error("RUNTIME.PATH", "registered agent path does not resolve")),
            (registry, "no frontmatter\n", contract_error("RUNTIME.FRONTMATTER", "agent definition lacks YAML frontmatter")),
            (registry, "---\nname: x\n", contract_error("RUNTIME.FRONTMATTER", "agent definition has unterminated YAML frontmatter")),
            (registry, agent.replace("name: anchor-tuning", "name: other"), contract_error("RUNTIME.IDENTITY", "agent frontmatter identity differs from registry")),
            (registry, agent.replace("0.5.0", "0.4.0"), contract_error("RUNTIME.VERSION", "agent frontmatter version differs from registry")),
            (registry, agent.replace("sol", "luna"), contract_error("RUNTIME.MODEL", "agent frontmatter model is invalid for its harness and role")),
            (registry, b"\xff", contract_error("RUNTIME.PATH", "registered agent definition is not readable UTF-8")),
        )
        for reg, definition, expected in cases:
            files = {"plug/.codex/agents/registry.yaml": reg, "plug/.codex/agents/anchor-tuning.md": definition}
            with self.subTest(expected=expected["error"]["message"]), Workspace(files) as ws:
                argv = ["resolve", "--plugin-root", str(ws.path / "plug"), "--harness", "codex", "--agent", "anchor-tuning"]
                self.assertEqual(call_main(rc.main, argv), (2, expected))
        with Workspace({}) as ws:
            self.assertEqual(call_main(rc.main, ["resolve", "--plugin-root", str(ws.path / "nope"), "--harness", "codex", "--agent", "anchor-tuning"]),
                             (2, contract_error("RUNTIME.PATH", "plugin root does not resolve")))
            self.assertEqual(call_main(rc.main, ["resolve", "--plugin-root", str(ws.path), "--harness", "codex", "--agent", "anchor-tuning"]),
                             (2, contract_error("RUNTIME.REGISTRY", "agent registry is missing or not a regular file")))


class TuningContractCli(unittest.TestCase):
    def run_cli(self, kind, value):
        with Workspace({"f.json": value}) as ws:
            proc = subprocess.run([sys.executable, str(SCRIPTS / "anchor_tuning_contract.py"), kind, str(ws.path / "f.json")],
                                  capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, proc.stdout

    def test_cli_reports_every_error_as_an_envelope_with_exit_two(self):
        cases = (
            ("result", {"x": [{"desired_verdict": 1}]}, "VALIDATION.FORBIDDEN_FIELD", "$.x[0].desired_verdict"),
            ("result", {"success": True, "data": {"operation": "x"}}, "VALIDATION.OPERATION", "unknown result operation"),
            ("request", {"runtime": {"harness": "codex", "model": "opus"}}, "VALIDATION.MODEL", "codex anchor-tuning requires sol"),
            ("request", {"runtime": {}}, "VALIDATION.MISSING_FIELD", "required field is missing: harness"),
            ("request", "{", "VALIDATION.JSON", "input is not valid JSON: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"),
            ("result", [1], "VALIDATION.SHAPE", "result must be a JSON object"),
            ("request", b"\xff", "SCRIPT.IO", "input could not be read"),
        )
        for kind, value, code, message in cases:
            with self.subTest(code=code):
                rc_, out = self.run_cli(kind, value)
                self.assertEqual((rc_, json.loads(out)), (2, contract_error(code, message)))
                self.assertEqual(out, json.dumps(contract_error(code, message), sort_keys=True, separators=(",", ":")) + "\n")
        rc_, out = self.run_cli("result", {"success": False})
        self.assertEqual((rc_, json.loads(out)), (0, {"success": True, "error": None, "data": {
            "valid": True, "sha256": hashlib.sha256(b'{"success":false}').hexdigest()}}))

    def test_unexpected_failure_is_script_internal(self):
        rc_, out = self.run_cli("request", {"runtime": []})
        error = json.loads(out)["error"]
        self.assertEqual((rc_, error["code"], error["message"].split(":")[0]), (2, "SCRIPT.INTERNAL", "TypeError"))
        self.assertEqual(error["suggested_action"], "Validate the object against its JSON schema first, then report this with the input.")


if __name__ == "__main__":
    unittest.main()
