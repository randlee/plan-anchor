"""TYPESAFE_API_KEY is the plugin's only configuration variable (ANC-005, REQ-018).

The six retired PLAN_ANCHOR_* variables (JEV_MODEL, JEV_URL, CONFIDENCE_THRESHOLD,
MAX_ITEM_CHARS, MAX_CODE_LINES, CONFIRM_NEAR) are planted with wild values and
must change nothing: not the dry-run output, not the live request, not the URL.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
SCRIPTS = PLUGIN / "skills" / "plan-anchoring" / "scripts"
JUDGE_SCRIPT = SCRIPTS / "jev_judge.py"

# Each would change behaviour, or fail at import, if it were still read.
WILD = {
    "PLAN_ANCHOR_JEV_MODEL": "jev-wild-0.0.0",
    "PLAN_ANCHOR_JEV_URL": "http://127.0.0.1:9/never",
    "PLAN_ANCHOR_CONFIDENCE_THRESHOLD": "0.01",
    "PLAN_ANCHOR_MAX_ITEM_CHARS": "5",
    "PLAN_ANCHOR_MAX_CODE_LINES": "lots",
    "PLAN_ANCHOR_CONFIRM_NEAR": "0",
}
ANCHOR = {
    "id": "ANC-001", "source_type": "ANC", "source_ref": None, "statement": "The CLI must add no new dependency.",
    "quote": "no new dependency", "stated_by": "the user", "stated_at": "2026-10-09", "context": "planning session",
    "summary": "no new dependency", "scope": "the CLI", "deterministic_check": "", "fixtures": {"pass": [], "fail": []},
    "question_overrides": {}, "version": 1, "status": "locked", "promoted_to": None,
    "beads": {"anchor": None, "plan_questions": None, "dev_questions": None}, "history": [],
}
RECORD = {"schema": "plan-anchoring/anchors/1", "plan": "phase-current", "intent_ref": "intent.md", "anchors": [ANCHOR]}
ITEM = "Sprint 2 adds a CLI command and no new dependency.\n"
JUDGE = ["judge", "--anchors", "anchors.json", "--gate", "plan", "--all", "--item-id", "ex-42", "--item-file", "item.txt",
         "--run-dir", "runs"]
VOLATILE = {"run_id", "created_at", "path", "run_path"}  # per-run timestamps


def clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("PLAN_ANCHOR_") and k != "TYPESAFE_API_KEY"}


def scrub(value):
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def workspace(d):
    (Path(d) / "anchors.json").write_text(json.dumps(RECORD), encoding="utf-8")
    (Path(d) / "item.txt").write_text(ITEM, encoding="utf-8")


def load_judge(name, environment):
    """A fresh copy of jev_judge imported under ``environment``: module-level defaults are read now."""
    with mock.patch.dict(os.environ, environment, clear=True):
        spec = importlib.util.spec_from_file_location(name, JUDGE_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, raw):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=-1):
        return self.raw[:n] if n >= 0 else self.raw


def choice(value, p):
    rest = round((1 - p) / 2, 4)
    return {"type": "choice", "choice": value, "confidence": p,
            "probabilities": {o: (p if o == value else rest) for o in ("yes", "no", "unclear")}}


class RetiredVariablesHaveNoEffect(unittest.TestCase):
    def dry_run(self, environment):
        with tempfile.TemporaryDirectory() as d:
            workspace(d)
            proc = subprocess.run([sys.executable, str(JUDGE_SCRIPT), *JUDGE, "--dry-run"], cwd=d, env=environment,
                                  capture_output=True, text=True, encoding="utf-8")
            runs = {p.name.split("-ex-")[-1]: json.loads(p.read_text(encoding="utf-8"))
                    for p in sorted((Path(d) / "runs").glob("*.json"))}
        return proc.returncode, scrub(json.loads(proc.stdout)), scrub(runs), proc.stderr

    def test_dry_run_output_and_requests_are_unchanged(self):
        baseline = self.dry_run(clean_env())
        planted = self.dry_run(dict(clean_env(), **WILD))
        self.assertEqual(baseline[0], 0, baseline)
        self.assertEqual(planted, baseline)
        data = planted[1]["data"]
        self.assertEqual((data["model_requested"], data["threshold"]), ("jev-latest", 0.6))
        self.assertIsNone(data["results"][0]["verdict"])
        self.assertTrue(planted[2], "dry run wrote no run file")

    def live(self, module, environment):
        answers = {"relevant": choice("yes", 0.9), "addressed": choice("yes", 0.65), "contradicted": choice("no", 0.9)}
        reply = json.dumps({"model": "jev-1.13.0", "answers": answers}).encode("utf-8")
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            workspace(d)
            cwd = os.getcwd()
            os.chdir(d)
            try:
                with mock.patch.dict(os.environ, dict(environment, TYPESAFE_API_KEY="sk-test-0001"), clear=True), \
                        mock.patch.object(module.urllib.request, "urlopen", side_effect=lambda *a, **k: FakeResponse(reply)) as opened, \
                        mock.patch.object(module, "remote_judge_consent", return_value=module.Ok(None)), \
                        mock.patch.object(module, "_sleep", lambda _s: None), contextlib.redirect_stdout(buf):
                    code = module.main(list(JUDGE))
            finally:
                os.chdir(cwd)
        requests = [(call.args[0].full_url, json.loads(call.args[0].data)) for call in opened.call_args_list]
        return code, scrub(json.loads(buf.getvalue())), requests

    def test_live_request_url_and_behaviour_are_unchanged(self):
        baseline = self.live(load_judge("jev_judge_clean", clean_env()), clean_env())
        wild_env = dict(clean_env(), **WILD)
        planted = self.live(load_judge("jev_judge_wild", wild_env), wild_env)
        self.assertEqual(planted, baseline)
        code, out, requests = planted
        self.assertEqual(code, 0, out)
        self.assertEqual({url for url, _ in requests}, {"https://api.typesafe.ai/v1/systemone"})
        self.assertEqual({body["model"] for _, body in requests}, {"jev-latest"})
        result = out["data"]["results"][0]
        # 0.65 is within 0.10 of the default 0.6: confirmation stays on (CONFIRM_NEAR=0 ignored), the item
        # is sent (MAX_ITEM_CHARS=5 ignored) and the verdict uses 0.6 (THRESHOLD=0.01 ignored).
        self.assertEqual((len(requests), result["attempts"], result["verdict"]), (2, 2, "satisfied"))
        self.assertEqual(out["data"]["threshold"], 0.6)


class ShippedTreeNamesNoRetiredVariable(unittest.TestCase):
    SHIPPED = (PLUGIN, ROOT / ".claude-plugin", ROOT / ".cursor-plugin", ROOT / ".agents", ROOT / "README.md")

    def shipped_files(self):
        for top in self.SHIPPED:
            if top.is_file():
                yield top
            else:
                yield from (p for p in sorted(top.rglob("*")) if p.is_file() and "__pycache__" not in p.parts)

    def test_no_plan_anchor_prefix_in_shipped_files(self):
        hits = [p.relative_to(ROOT).as_posix() for p in self.shipped_files() if b"PLAN_ANCHOR_" in p.read_bytes()]
        self.assertEqual(hits, [])

    def test_only_typesafe_key_is_read_from_the_environment(self):
        # USER is the operating system's login name (the --stated-by default), not plugin configuration.
        allowed = {"TYPESAFE_API_KEY", "USER"}
        read = re.compile(r"""(?:environ\.get|environ\[|getenv)\(?\s*["']([^"']+)["']""")
        found = {}
        for path in sorted(PLUGIN.rglob("*.py")):
            for name in read.findall(path.read_text(encoding="utf-8")):
                found.setdefault(name, []).append(path.relative_to(PLUGIN).as_posix())
        self.assertEqual(sorted(set(found) - allowed), [], found)
        self.assertIn("TYPESAFE_API_KEY", found)


if __name__ == "__main__":
    unittest.main()
