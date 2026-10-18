"""0.8.3: a Jev call that got no answer is a tool failure, never a negative result.

Every case runs a real process. ``judge``, ``check-fixtures``, ``dedupe --jev``,
``rubric`` and ``add --rubric`` exit 2 with the typed envelope when any cell, pair
or candidate has no answer, and keep the partial work in ``data``. Live failures
use a closed local port (127.0.0.1:9) with a dummy key in the child only, and
consent recorded in a scratch repository; fixture failures use answers files. Jev
is never called. Refusals and no-ops exit 0; run files are redacted; every CLI
prints a CANCELED envelope and exits 130 on interrupt.
"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from layout_support import PLUGIN, SCRIPTS
from test_jev_judge import QUOTE, STATEMENT, anchor, plan_answers, record, rubric_answers

JJ = SCRIPTS / "jev_judge.py"
ERROR_KEYS = {"code", "message", "recoverable", "suggested_action"}
ITEM = "Sprint 2 copies the legacy runtime crates into crates/runtime and deletes the legacy-specific modules.\n"
DUMMY_KEY = "sk-test-closed-port-0000"  # never a real key: the only URL it can reach is a closed local port
# jev_judge.main with JEV_URL pointed at a closed local port (the connection is refused) and no back-off sleep;
# the retries themselves still run. argv[1] is the scripts directory, the rest is the command line.
CLOSED_PORT_RUNNER = (
    "import sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import jev_judge\n"
    "jev_judge.JEV_URL = 'http://127.0.0.1:9/v1/systemone'\n"
    "jev_judge._sleep = lambda seconds: None\n"
    "raise SystemExit(jev_judge.main(sys.argv[2:]))\n"
)
try:
    import yaml  # noqa: F401 - consent lives in settings.yaml, which the settings module reads with PyYAML
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False
needs_yaml = unittest.skipUnless(HAVE_YAML, "live-path cases read allow_remote_judge from settings.yaml (PyYAML)")


def child_env(**extra):
    environment = {k: v for k, v in os.environ.items() if k != "TYPESAFE_API_KEY"}
    environment.update(extra)
    return environment


class ProcessCase(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.d = Path(td.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.d)], check=True)

    def put(self, name, value):
        path = self.d / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        return str(path)

    def consent(self):
        """allow_remote_judge: true in this scratch repository's settings file (never the real one)."""
        proc = subprocess.run([sys.executable, str(SCRIPTS / "plan_anchor_settings.py"), "set", "allow_remote_judge", "true"],
                              cwd=str(self.d), env=child_env(), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def run_jj(self, *argv, live=False, env=None):
        if live:
            cmd = [sys.executable, "-c", CLOSED_PORT_RUNNER, str(SCRIPTS), *argv]
            environment = child_env(TYPESAFE_API_KEY=DUMMY_KEY, **(env or {}))
        else:
            cmd = [sys.executable, str(JJ), *argv]
            environment = child_env(**(env or {}))
        proc = subprocess.run(cmd, cwd=str(self.d), env=environment, capture_output=True, text=True,
                              encoding="utf-8", timeout=300)
        self.assertNotEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            self.fail(f"no JSON envelope: {proc.stdout!r} {proc.stderr!r}")
        return proc.returncode, out

    def failed(self, *argv, code, live=False):
        """Exit 2, success false, the four error keys, the given code; returns the envelope."""
        rc, out = self.run_jj(*argv, live=live)
        self.assertEqual((rc, out["success"]), (2, False), out)
        self.assertEqual(set(out["error"]), ERROR_KEYS)
        self.assertEqual(out["error"]["code"], code, out["error"])
        self.assertIn("got no answer from Jev", out["error"]["message"])
        self.assertTrue(out["data"]["failures"])
        self.assertTrue(all(f["code"] == code for f in out["data"]["failures"][:1]))
        return out

    def ran(self, *argv, env=None):
        rc, out = self.run_jj(*argv, env=env)
        self.assertEqual((rc, out["success"], out["error"]), (0, True, None), out)
        return out["data"]


SIMILAR = "The runtime crates are copied from the legacy repository with the legacy-specific modules removed."


class JudgeAndCheckFixtures(ProcessCase):
    def judge_argv(self, *extra):
        return ["judge", "--anchors", self.put("anchors.json", record(anchor(), anchor("ANC-002"))), "--gate", "plan", "--all",
                "--item-id", "ex-42", "--item-file", self.put("item.txt", ITEM), "--run-dir", str(self.d / "runs"), *extra]

    @needs_yaml
    def test_judge_with_jev_unreachable_exits_2_and_keeps_the_partial_run(self):
        self.consent()
        out = self.failed(*self.judge_argv("--no-confirm"), code="JEV.NETWORK", live=True)
        self.assertTrue(out["error"]["recoverable"])
        self.assertEqual(sorted(f["id"] for f in out["data"]["failures"]), ["ANC-001", "ANC-002"])
        on_disk = json.loads(Path(out["data"]["run_path"]).read_text(encoding="utf-8"))
        self.assertEqual({r["verdict"] for r in on_disk["results"]}, {"error"})
        self.assertEqual({r["attempts"] for r in on_disk["results"]}, {3})  # retried, then failed

    def test_judge_with_a_missing_fixture_entry_exits_2_and_keeps_the_answered_cell(self):
        answers = self.put("a.json", {"ANC-001": plan_answers()})
        out = self.failed(*self.judge_argv("--answers-file", answers), code="FIXTURE.MISSING")
        self.assertEqual([f["id"] for f in out["data"]["failures"]], ["ANC-002"])
        on_disk = json.loads(Path(out["data"]["run_path"]).read_text(encoding="utf-8"))
        self.assertEqual({r["anchor_id"]: r["verdict"] for r in on_disk["results"]}, {"ANC-001": "satisfied", "ANC-002": "error"})

    def test_judge_with_a_malformed_fixture_answer_exits_2(self):
        bad = plan_answers()
        bad["relevant"]["probabilities"]["yes"] = 0.1
        self.failed(*self.judge_argv("--answers-file", self.put("a.json", {"*": bad})), code="JEV.RESPONSE_INVALID")

    def test_an_answers_file_that_is_not_an_object_stays_exit_2(self):
        rc, out = self.run_jj(*self.judge_argv("--answers-file", self.put("a.json", [1])))
        self.assertEqual((rc, out["success"], set(out["error"])), (2, False, ERROR_KEYS))

    def fixture_anchors(self, **fields):
        return self.put("anchors.json", record(anchor(fixtures={"pass": ["We copy the legacy runtime crates."],
                                                                 "fail": ["We write the runtime crates from scratch."]}, **fields)))

    def test_check_fixtures_with_a_missing_fixture_entry_exits_2(self):
        out = self.failed("check-fixtures", "--anchors", self.fixture_anchors(), "--gate", "plan", "--all",
                          "--answers-file", self.put("a.json", {"other": plan_answers()}), "--run-dir", str(self.d / "runs"),
                          code="FIXTURE.MISSING")
        self.assertEqual(sorted(f["id"] for f in out["data"]["failures"]), ["ANC-001:fail:1", "ANC-001:pass:1"])

    @needs_yaml
    def test_check_fixtures_with_jev_unreachable_exits_2(self):
        self.consent()
        self.failed("check-fixtures", "--anchors", self.fixture_anchors(), "--gate", "plan", "--all", "--no-confirm",
                    "--run-dir", str(self.d / "runs"), code="JEV.NETWORK", live=True)

    def test_check_fixtures_with_nothing_judged_is_not_a_pass(self):
        # a structural anchor at the plan gate is deterministic_only: no fixture is sent to Jev, so nothing was tested
        data = self.ran("check-fixtures", "--anchors", self.fixture_anchors(kind="structural"), "--gate", "plan", "--all",
                        "--answers-file", self.put("a.json", {"*": plan_answers()}), "--run-dir", str(self.d / "runs"))
        self.assertEqual((data["pass"], data["judged"], data["mismatches"]), (False, 0, []))
        self.assertIn("no fixture was judged", data["note"])


class DedupeAndRubric(ProcessCase):
    def pair(self):
        return self.put("anchors.json", record(anchor(), anchor("ANC-002", statement=SIMILAR, quote="copy the legacy code and strip it")))

    @needs_yaml
    def test_dedupe_with_jev_unreachable_exits_2(self):
        self.consent()
        out = self.failed("dedupe", "--anchors", self.pair(), "--threshold", "0.2", "--jev", code="JEV.NETWORK", live=True)
        self.assertEqual([f["id"] for f in out["data"]["failures"]], ["ANC-001|ANC-002"])

    def test_dedupe_with_a_missing_fixture_pair_exits_2(self):
        self.failed("dedupe", "--anchors", self.pair(), "--threshold", "0.2", "--answers-file", self.put("a.json", {"x|y": {}}),
                    code="FIXTURE.MISSING")

    @needs_yaml
    def test_rubric_with_jev_unreachable_exits_2(self):
        self.consent()
        out = self.failed("rubric", "--statement", STATEMENT, "--quote", QUOTE, code="JEV.NETWORK", live=True)
        self.assertEqual(out["data"]["anchors"][0]["verdict"], "error")

    def test_rubric_with_a_missing_fixture_entry_exits_2(self):
        self.failed("rubric", "--anchors", self.pair(), "--all", "--answers-file", self.put("a.json", {"ANC-001": rubric_answers()}),
                    code="FIXTURE.MISSING")

    def test_add_rubric_without_an_answer_records_nothing_even_with_allow_untestable(self):
        path = self.d / "anchors.json"
        missing = self.put("a.json", {"other": rubric_answers()})
        for extra in ([], ["--allow-untestable"]):
            with self.subTest(extra=extra):
                self.failed("add", "--anchors", str(path), "--statement", STATEMENT, "--quote", QUOTE, "--rubric",
                            "--answers-file", missing, *extra, code="FIXTURE.MISSING")
                self.assertFalse(path.exists())

    @needs_yaml
    def test_add_rubric_with_jev_unreachable_records_nothing(self):
        self.consent()
        path = self.d / "anchors.json"
        for extra in ([], ["--allow-untestable"]):
            with self.subTest(extra=extra):
                self.failed("add", "--anchors", str(path), "--statement", STATEMENT, "--quote", QUOTE, "--rubric", *extra,
                            code="JEV.NETWORK", live=True)
                self.assertFalse(path.exists())


class RefusalsAndNoOps(ProcessCase):
    """The command ran and the answer is no (refused) or nothing to do (changed false): exit 0."""

    def test_duplicate_id_and_verbatim_statement_are_refusals(self):
        path = self.put("anchors.json", record(anchor("REQ-014", source_type="REQ", source_ref="REQ-014")))
        before = Path(path).read_bytes()
        for extra, code in ((["--statement", "Every command must emit JSON.", "--source-type", "REQ", "--source-ref", "REQ-014"], "ANCHOR.DUPLICATE"),
                            (["--statement", "Copy it must.", "--quote", "copy it must"], "VALIDATION.INPUT")):
            with self.subTest(code):
                data = self.ran("add", "--anchors", path, *extra)
                self.assertEqual((data["added"], data["refused"]["code"], data["refused"]["recoverable"]), (False, code, True))
                self.assertEqual(set(data["refused"]), ERROR_KEYS)
                self.assertEqual(Path(path).read_bytes(), before)

    def test_every_refusal_carries_recoverable(self):
        data = self.ran("add", "--anchors", self.put("anchors.json", record(anchor())), "--statement", STATEMENT, "--quote", "other words")
        self.assertEqual((data["refused"]["code"], set(data["refused"])), ("ANCHOR.DUPLICATE_CANDIDATE", ERROR_KEYS))

    def test_no_op_update_retire_and_exclude_remove_exit_zero_unchanged(self):
        path = self.put("anchors.json", record(anchor(), anchor("ANC-002", status="retired")))
        before = Path(path).read_bytes()
        update = self.ran("update", "--anchors", path, "--id", "ANC-001", "--scope", anchor()["scope"])
        self.assertEqual((update["updated"], update["changed"]), (False, False))
        retire = self.ran("retire", "--anchors", path, "--id", "ANC-002")
        self.assertEqual((retire["status"], retire["changed"]), ("retired", False))
        exclude = self.ran("exclude", "--anchors", path, "--id", "ANC-001", "--item", "ex-42", "--remove")
        self.assertIs(exclude["changed"], False)
        self.assertEqual(Path(path).read_bytes(), before)


class RunFileRedaction(ProcessCase):
    """REQ-017: the key value and bearer tokens never reach a run file, whatever input carried them."""

    CANARY = "sk-canary-6f1c2a9e0b"
    BEARER = "tok-canary-77aa"

    def judge(self, *extra):
        item = self.put("item.txt", f"{ITEM}debug: TYPESAFE_API_KEY={self.CANARY}\nAuthorization: Bearer {self.BEARER}\n")
        data = self.ran("judge", "--anchors", self.put("anchors.json", record(anchor())), "--gate", "plan", "--all",
                        "--item-id", "ex-42", "--item-title", f"title {self.CANARY} Bearer {self.BEARER}", "--item-file", item,
                        "--run-dir", str(self.d / "runs"), *extra, env={"TYPESAFE_API_KEY": self.CANARY})
        return Path(data["run_path"]).read_text(encoding="utf-8")

    def assert_redacted(self, text, marker):
        self.assertIn(marker, text)  # the input carrying the canary was recorded ...
        self.assertNotIn(self.CANARY, text)  # ... without the key
        self.assertNotIn(self.BEARER, text)

    def test_a_key_in_the_item_title_never_reaches_a_fixture_run_file(self):
        self.assert_redacted(self.judge("--answers-file", self.put("a.json", {"*": plan_answers()})), '"title": "title ')

    def test_a_key_in_the_item_text_never_reaches_a_dry_run_file(self):
        self.assert_redacted(self.judge("--dry-run"), "debug: TYPESAFE_API_KEY=")


@unittest.skipUnless(hasattr(os, "mkfifo"), "the interrupt is timed with a FIFO the command blocks on (POSIX)")
class Interrupts(unittest.TestCase):
    """SIGINT while a command waits on input: the CANCELED envelope on stdout and exit 130, from each CLI."""

    def interrupt(self, argv, fifo_rel, env=None, git=False, files=None):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td).resolve()
            if git:
                subprocess.run(["git", "init", "-q", str(d)], check=True)
            for name, value in (files or {}).items():
                (d / name).write_text(json.dumps(value), encoding="utf-8")
            fifo = d / fifo_rel
            fifo.parent.mkdir(parents=True, exist_ok=True)
            os.mkfifo(str(fifo))
            argv = [str(a).replace("{FIFO}", str(fifo)) for a in argv]
            proc = subprocess.Popen([sys.executable, *argv], cwd=str(d), env=child_env(**(env or {})),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
            writer, deadline = None, time.monotonic() + 30
            while writer is None and time.monotonic() < deadline and proc.poll() is None:
                try:  # succeeds only once the command has opened the FIFO for reading, i.e. it is blocked on it
                    writer = os.open(str(fifo), os.O_WRONLY | os.O_NONBLOCK)
                except OSError:
                    time.sleep(0.02)
            try:
                if writer is None:
                    out, err = proc.communicate(timeout=30)
                    self.fail(f"{argv[0]} never opened {fifo_rel}: exit {proc.returncode} {out} {err}")
                # The FIFO is open, so the command is in or about to enter its blocking read. A signal that lands
                # between open() returning and read() starting is only noticed at the next bytecode, which a
                # blocking read never reaches; wait first, and repeat the signal if the command is still blocked.
                out = err = None
                for _ in range(3):
                    time.sleep(0.2)
                    proc.send_signal(signal.SIGINT)
                    try:
                        out, err = proc.communicate(timeout=10)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if out is None:
                    self.fail(f"{argv[0]} did not exit after SIGINT")
            finally:
                if writer is not None:
                    os.close(writer)
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
        self.assertEqual(proc.returncode, 130, out + err)
        envelope = json.loads(out)
        self.assertEqual((envelope["success"], envelope["data"]), (False, None))
        self.assertEqual((envelope["error"]["code"], envelope["error"]["recoverable"]), ("CANCELED", True))
        self.assertEqual(set(envelope["error"]), ERROR_KEYS)
        self.assertNotIn("Traceback", err)

    def test_jev_judge(self):
        # a dry-run judge blocks reading its item from the FIFO: no settings file, no PyYAML, no request is ever built
        self.interrupt([JJ, "judge", "--anchors", "anchors.json", "--gate", "plan", "--all", "--item-id", "ex-42",
                        "--item-file", "{FIFO}", "--run-dir", "runs", "--dry-run"], "item.txt", git=True,
                       files={"anchors.json": record(anchor())})

    def test_anchor_runner_contract(self):
        self.interrupt([SCRIPTS / "anchor_runner_contract.py", "validate-fence", "--kind", "request", "--file", "{FIFO}"], "f.md")

    def test_anchor_tuning_contract(self):
        self.interrupt([SCRIPTS / "anchor_tuning_contract.py", "request", "{FIFO}"], "r.json")

    @unittest.skipUnless(HAVE_YAML, "the settings file is read with PyYAML")
    def test_plan_anchor_settings(self):
        self.interrupt([SCRIPTS / "plan_anchor_settings.py", "show"], ".sc/plan-anchor/settings.yaml", git=True)

    @unittest.skipUnless(HAVE_YAML, "the settings file is read with PyYAML")
    def test_anchor_tracker(self):
        self.interrupt([SCRIPTS / "anchor_tracker.py", "resolve"], ".sc/plan-anchor/settings.yaml", git=True)

    def test_install(self):
        self.interrupt([PLUGIN / "install.py", "--dest", ".", "--status"], ".sc/plan-anchor/install-lock.json")


if __name__ == "__main__":
    unittest.main()
