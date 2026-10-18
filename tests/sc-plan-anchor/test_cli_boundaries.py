"""CLI boundaries: usage errors and unexpected exceptions come back as JSON envelopes, exit 2.

jev_judge.py, anchor_runner_contract.py and anchor_tuning_contract.py turn argparse
usage errors into VALIDATION.INPUT (like anchor_tracker.py and install.py), and
anchor_runner_contract.py turns an unexpected exception into SCRIPT.INTERNAL.
The committed (neutral) render names no single tracker as the default.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
SKILL = PLUGIN / "skills" / "plan-anchoring"
SCRIPTS = SKILL / "scripts"
CLEAN_ENV = {k: v for k, v in os.environ.items() if k != "TYPESAFE_API_KEY"}


def run(script, *argv):
    proc = subprocess.run([sys.executable, str(SCRIPTS / script), *argv], capture_output=True, text=True,
                          encoding="utf-8", env=CLEAN_ENV)
    return proc.returncode, proc.stdout, proc.stderr


def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_boundary", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UsageErrorEnvelopeTests(unittest.TestCase):
    CASES = {
        "jev_judge.py": (["judge", "--no-such-flag"], ["frobnicate"], []),
        "anchor_runner_contract.py": (["resolve", "--harness", "codex"], ["frobnicate"], []),
        "anchor_tuning_contract.py": (["request"], ["sideways", "x.json"], []),
    }

    def test_usage_errors_are_validation_input_on_stdout(self):
        for script, cases in self.CASES.items():
            for argv in cases:
                with self.subTest(script=script, argv=argv):
                    code, out, err = run(script, *argv)
                    self.assertEqual((code, err), (2, ""))
                    envelope = json.loads(out)
                    self.assertEqual((envelope["success"], envelope["data"], envelope["error"]["code"]),
                                     (False, None, "VALIDATION.INPUT"))
                    self.assertTrue(envelope["error"]["message"].startswith(script), envelope["error"]["message"])
                    self.assertIn("--help", envelope["error"]["suggested_action"])

    def test_help_still_prints_text_and_exits_zero(self):
        for script in self.CASES:
            with self.subTest(script=script):
                code, out, _ = run(script, "--help")
                self.assertEqual(code, 0)
                self.assertIn("usage:", out)


class RunnerInternalBoundaryTests(unittest.TestCase):
    def test_unexpected_exception_is_script_internal(self):
        contract = load("anchor_runner_contract")
        buf = io.StringIO()
        with mock.patch.object(contract, "resolve_agent", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stdout(buf):
            code = contract.main(["resolve", "--plugin-root", str(PLUGIN), "--harness", "codex",
                                  "--agent", next(iter(contract.AGENT_MODELS))])
        envelope = json.loads(buf.getvalue())
        self.assertEqual((code, envelope["success"], envelope["error"]["code"]), (2, False, "SCRIPT.INTERNAL"))
        self.assertEqual(envelope["error"]["message"], "RuntimeError: boom")

    def test_unreadable_file_is_still_script_io(self):
        code, out, _ = run("anchor_runner_contract.py", "validate-fence", "--kind", "request",
                           "--file", str(ROOT / "no-such-file.json"))
        self.assertEqual((code, json.loads(out)["error"]["code"]), (2, "SCRIPT.IO"))


class NeutralRenderTests(unittest.TestCase):
    """The committed tree is the tracker-neutral render; the br and bd renders are checked by test_install."""

    def test_neutral_skill_has_no_bd_default(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("Tracker command examples use `bd`", text)
        self.assertIn('Tracker commands below are written for the selected tracker, `"$ANCHOR_TRACKER"`', text)

    def test_neutral_review_workflow_names_both_trackers(self):
        text = (SKILL / "references" / "development-review-workflow.md").read_text(encoding="utf-8")
        self.assertIn("br comments add <id> --file <report.md>", text)
        self.assertIn("bd comment <id> --file <report.md>", text)


if __name__ == "__main__":
    unittest.main()
