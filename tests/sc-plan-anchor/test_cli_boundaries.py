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

from layout_support import SCRIPTS, rendered_skill
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
SKILL = PLUGIN / "install" / "templates" / "skills" / "plan-anchoring"
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
            code = contract.main(["resolve", "--install-root", str(PLUGIN), "--harness", "codex",
                                  "--agent", next(iter(contract.AGENT_MODELS))])
        envelope = json.loads(buf.getvalue())
        self.assertEqual((code, envelope["success"], envelope["error"]["code"]), (2, False, "SCRIPT.INTERNAL"))
        self.assertEqual(envelope["error"]["message"], "RuntimeError: boom")

    def test_unreadable_file_is_still_script_io(self):
        code, out, _ = run("anchor_runner_contract.py", "validate-fence", "--kind", "request",
                           "--file", str(ROOT / "no-such-file.json"))
        self.assertEqual((code, json.loads(out)["error"]["code"]), (2, "SCRIPT.IO"))


class RenderedTrackerTextTests(unittest.TestCase):
    """Each render names its own tracker's commands (formerly checked on the committed neutral render)."""

    def test_skill_has_no_other_tracker_default(self):
        for tracker, other in (("br", "bd"), ("bd", "br")):
            with self.subTest(tracker=tracker):
                text = (rendered_skill(tracker) / "SKILL.md").read_text(encoding="utf-8")
                self.assertNotIn(f"Tracker command examples use `{other}`", text)

    def test_review_workflow_names_the_rendered_tracker(self):
        forms = {"br": "br comments add <id> --file <report.md>", "bd": "bd comment <id> --file <report.md>"}
        for tracker, other in (("br", "bd"), ("bd", "br")):
            with self.subTest(tracker=tracker):
                text = (rendered_skill(tracker) / "references" / "development-review-workflow.md").read_text(encoding="utf-8")
                self.assertIn(forms[tracker], text)
                self.assertNotIn(forms[other], text)


if __name__ == "__main__":
    unittest.main()
