"""The exit-code convention, end to end through each real CLI process.

A tool failure returns an error in the exit code; a call which ran properly and
returned a negative result still ran properly. So: exit 0 with the outcome in
``data`` (negative outcomes included), exit 2 with the typed error envelope when
the command could not do its job, and no exit 1 anywhere. Every case runs the
script as a subprocess, offline, with no TypeSafe key in the environment.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from test_jev_judge import QUOTE, STATEMENT, anchor, plan_answers, record, rubric_answers

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
SCRIPTS = PLUGIN / "install" / "templates" / "skills" / "plan-anchoring" / "scripts"
JJ = SCRIPTS / "jev_judge.py"
ERROR_KEYS = {"code", "message", "recoverable", "suggested_action"}
ITEM = "The runtime crates are not mentioned anywhere in this sprint; it only adds a status command and its tests.\n" * 3


def clean_env():
    keep = ("PATH", "HOME", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "PYTHONPATH")
    return {k: os.environ[k] for k in keep if k in os.environ}


class ConventionCase(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name).resolve()
        self.addCleanup(self.td.cleanup)

    def put(self, name, value):
        path = self.d / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        return str(path)

    def run_script(self, script, *argv):
        proc = subprocess.run([sys.executable, str(script), *argv], cwd=str(self.d), env=clean_env(),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(proc.returncode, 1, f"{script.name} {argv} exited 1: {proc.stdout}{proc.stderr}")
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            self.fail(f"{script.name} {argv} printed no JSON envelope: {proc.stdout!r} {proc.stderr!r}")
        return proc.returncode, out

    def ran(self, script, *argv):
        """Exit 0 and success true: the command ran; returns data for the outcome assertions."""
        code, out = self.run_script(script, *argv)
        self.assertEqual((code, out["success"], out["error"]), (0, True, None), out)
        return out["data"]

    def failed(self, script, *argv, code=None, data_none=True):
        """Exit 2 and the typed error envelope: the command could not do its job."""
        rc, out = self.run_script(script, *argv)
        self.assertEqual((rc, out["success"]), (2, False), out)
        self.assertEqual(set(out["error"]), ERROR_KEYS)
        if data_none:
            self.assertIsNone(out["data"])
        if code is not None:
            self.assertEqual(out["error"]["code"], code)
        return out["error"]


class JevJudgeNegativeOutcomes(ConventionCase):
    """Each subcommand with an outcome: a negative answer is exit 0 with the outcome field set."""

    def anchors(self, *items):
        return self.put("anchors.json", record(*items))

    def test_validate(self):
        data = self.ran(JJ, "validate", "--anchors", self.anchors(anchor(status="nope")))
        self.assertIs(data["valid"], False)
        self.assertTrue(data["problems"])
        self.assertIs(self.ran(JJ, "validate", "--anchors", self.anchors(anchor()))["valid"], True)

    def test_lint(self):
        data = self.ran(JJ, "lint", "--anchors", self.anchors(anchor(statement="We should keep things clean.")))
        self.assertEqual((data["clean"] is False, data["warning_count"] > 0), (True, True))
        self.assertIs(self.ran(JJ, "lint", "--anchors", self.anchors(anchor()))["clean"], True)

    def test_dedupe(self):
        data = self.ran(JJ, "dedupe", "--anchors", self.anchors(anchor(), anchor("ANC-002")))
        self.assertTrue(data["likely_duplicates"])

    def test_rubric(self):
        answers = self.put("a.json", {"candidate": rubric_answers(observable=("no", 0.9))})
        data = self.ran(JJ, "rubric", "--statement", STATEMENT, "--quote", QUOTE, "--answers-file", answers)
        self.assertIs(data["pass"], False)

    def test_add_refusals(self):
        path = self.anchors(anchor())
        cases = (
            (["--statement", STATEMENT, "--quote", "other words"], "ANCHOR.DUPLICATE_CANDIDATE"),
            (["--statement", "We should keep things clean.", "--quote", "x y z", "--strict"], "ANCHOR.LINT"),
            (["--statement", "Every command must emit JSON.", "--quote", "json", "--rubric",
              "--answers-file", self.put("r.json", {"*": rubric_answers(observable=("no", 0.9))})], "ANCHOR.NOT_TESTABLE"),
        )
        before = Path(path).read_text(encoding="utf-8")
        for extra, code in cases:
            with self.subTest(code):
                data = self.ran(JJ, "add", "--anchors", path, *extra)
                self.assertEqual((data["added"], data["refused"]["code"]), (False, code))
                self.assertEqual(Path(path).read_text(encoding="utf-8"), before)

    def test_update_strict_refusal(self):
        path = self.anchors(anchor())
        data = self.ran(JJ, "update", "--anchors", path, "--id", "ANC-001", "--strict",
                        "--statement", "The crates are probably copied from the legacy repo.")
        self.assertEqual((data["updated"], data["refused"]["code"]), (False, "ANCHOR.LINT"))

    def judge(self, answers, out):
        return self.ran(JJ, "judge", "--anchors", self.anchors(anchor()), "--gate", "plan", "--all", "--item-id", "bd-1",
                        "--item-file", self.put("item.txt", ITEM), "--answers-file", self.put("answers.json", {"*": answers}),
                        "--out", str(self.d / out))

    def test_judge_report_coverage_diff(self):
        passing = self.judge(plan_answers(), "runs/pass.json")
        self.assertIs(passing["summary"]["pass"], True)
        failing = self.judge(plan_answers(comp="no"), "next/fail.json")
        self.assertIs(failing["summary"]["pass"], False)
        self.assertIs(self.ran(JJ, "report", "--run", str(self.d / "next/fail.json"))["pass"], False)
        self.assertEqual(self.ran(JJ, "coverage", "--runs", str(self.d / "next"))["uncovered_anchors"], ["ANC-001"])
        data = self.ran(JJ, "diff", "--prev", str(self.d / "runs/pass.json"), "--next", str(self.d / "next/fail.json"))
        self.assertIs(data["pass_after"], False)
        self.assertTrue(data["pass_to_fail"])

    def test_check_fixtures(self):
        path = self.anchors(anchor(fixtures={"pass": ["We copy the legacy runtime crates."],
                                             "fail": ["We write the runtime crates from scratch."]}))
        data = self.ran(JJ, "check-fixtures", "--anchors", path, "--gate", "plan", "--all",
                        "--answers-file", self.put("a.json", {"*": plan_answers()}), "--run-dir", str(self.d / "runs"))
        self.assertEqual((data["pass"], data["mismatches"]), (False, ["ANC-001:fail:1"]))


class JevJudgeErrors(ConventionCase):
    """Every subcommand's could-not-run path: exit 2, success false, the four error keys."""

    def test_each_subcommand(self):
        path = self.put("anchors.json", record(anchor()))
        missing = str(self.d / "missing.json")
        cases = {
            "add": (["add", "--anchors", path, "--statement", STATEMENT, "--kind", "nope"], "VALIDATION.INPUT"),
            "update": (["update", "--anchors", path, "--id", "ANC-999", "--summary", "x"], None),
            "retire": (["retire", "--anchors", path, "--id", "ANC-999"], None),
            "exclude": (["exclude", "--anchors", path, "--id", "ANC-999", "--item", "bd-1", "--reason", "x"], None),
            "validate": (["validate", "--anchors", missing], None),
            "lint": (["lint", "--anchors", missing], None),
            "dedupe": (["dedupe", "--anchors", missing], None),
            "rubric": (["rubric", "--dry-run"], "VALIDATION.INPUT"),
            "render": (["render", "--anchors", missing], None),
            "set-beads": (["set-beads", "--anchors", path, "--id", "ANC-999", "--anchor-bead", "bd-1"], None),
            "promote": (["promote", "--anchors", path, "--id", "ANC-999", "--adr", "ADR-001"], None),
            "compose-item": (["compose-item", "--show-json", missing], None),
            "agent-preflight": (["agent-preflight", "--workspace-root", str(self.d / "nowhere"), "--script", str(JJ),
                                 "--anchors", path], None),
            "shape": (["shape", "--show-json", missing], None),
            "judge": (["judge", "--anchors", path, "--gate", "plan", "--all", "--item-id", "bd-1",
                       "--item-file", self.put("item.txt", ITEM)], None),
            "check-fixtures": (["check-fixtures", "--anchors", path, "--gate", "plan", "--all", "--dry-run"], "FIXTURE.NONE"),
            "report": (["report", "--run", missing], None),
            "coverage": (["coverage", "--runs", str(self.d / "empty")], None),
            "diff": (["diff", "--prev", missing, "--next", missing], None),
        }
        (self.d / "empty").mkdir()
        listed = re.search(r"\{([a-z,-]+)\}", subprocess.run([sys.executable, str(JJ), "-h"], capture_output=True,
                                                            text=True, encoding="utf-8").stdout).group(1).split(",")
        self.assertEqual(sorted(cases), sorted(listed), "every subcommand needs an error-path case")
        for name, (argv, code) in cases.items():
            with self.subTest(name):
                self.failed(JJ, *argv, code=code)


class OtherScripts(ConventionCase):
    def test_runner_contract(self):
        script = SCRIPTS / "anchor_runner_contract.py"
        fence = self.put("f.md", "```json\n{\n```\n")
        data = self.ran(script, "validate-fence", "--kind", "request", "--file", fence)
        self.assertIs(data["valid"], False)
        self.assertTrue(data["violation"]["code"].startswith("ENVELOPE."))
        self.failed(script, "validate-fence", "--kind", "request", "--file", str(self.d / "missing.md"), code="SCRIPT.IO")
        self.failed(script, "validate-fence", "--kind", "result", "--file", fence, code="ENVELOPE.CORRELATION")

    def test_tuning_contract(self):
        script = SCRIPTS / "anchor_tuning_contract.py"
        data = self.ran(script, "request", self.put("r.json", {"runtime": {}}))
        self.assertEqual((data["valid"], data["violation"]["code"]), (False, "VALIDATION.MISSING_FIELD"))
        self.failed(script, "request", str(self.d / "missing.json"), code="SCRIPT.IO")

    def test_settings(self):
        script = SCRIPTS / "plan_anchor_settings.py"
        subprocess.run(["git", "init", "-q", str(self.d)], check=True)
        try:
            import yaml  # noqa: F401
        except ImportError:  # the settings script needs PyYAML; its absence is a could-not-run error
            self.failed(script, "show", code="DEPENDENCY.PYYAML")
            return
        self.assertIsNone(self.ran(script, "show")["allow_remote_judge"])  # never asked: a negative answer, exit 0
        self.failed(script, "set", "allow_remote_judge", "maybe")

    def test_tracker(self):
        self.failed(SCRIPTS / "anchor_tracker.py", "bogus", code="VALIDATION.INPUT")

    def test_installer(self):
        self.failed(PLUGIN / "install.py", "--dest", str(self.d), "--tracker", "zz", code="VALIDATION.INPUT")


SHIPPED_TEXT = ("*.md", "*.j2", "*.yaml", "*.json")
EXIT_ONE = re.compile(r"\bexit(?:s|ed|ing)?\s+(?:code\s+|status\s+)?1\b|\bexit\s+\$\?", re.IGNORECASE)


class NoExitOneInShippedText(unittest.TestCase):
    def test_no_prompt_or_reference_says_exit_1(self):
        files = [ROOT / "README.md"]
        for pattern in SHIPPED_TEXT:
            files.extend(p for p in PLUGIN.rglob(pattern) if p.is_file())
        self.assertGreater(len(files), 40)
        hits = [f"{p.relative_to(ROOT)}:{n}: {line.strip()}"
                for p in files for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                if EXIT_ONE.search(line)]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
