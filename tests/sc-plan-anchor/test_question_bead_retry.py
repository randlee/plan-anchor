"""The planning gate's question-override loop retries a failed tracker `show` up to 3 attempts.

The loop is extracted from the rendered agent prompt and run as written, against a fake tracker that fails a
fixed number of times (a counter file, no timing) and a no-op `sleep` on PATH, so the test is deterministic.
"""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from layout_support import TRACKERS, rendered_agent

BASH = shutil.which("bash")
JQ = shutil.which("jq")
OVERRIDE = {"questions": {"addressed": {"type": "choice", "instructions": "from bead", "criteria": {"yes": "", "no": "", "unclear": ""}}}}


def override_loop(tracker: str) -> str:
    prompt = rendered_agent(tracker, "claude", "anchor-plan-review.md").read_text(encoding="utf-8")
    step = prompt[prompt.index("3. Resolve question overrides."):]
    block = re.search(r"```bash\n(.*?)\n\s*```", step, re.S).group(1)
    return "\n".join(line[3:] if line.startswith("   ") else line for line in block.splitlines())


def executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@unittest.skipIf(sys.platform == "win32" or not BASH or not JQ, "runs the prompt's bash loop; needs bash and jq")
class QuestionBeadRetryTests(unittest.TestCase):
    def run_loop(self, tracker: str, failures: int):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        bin_dir, work = d / "bin", d / "w"
        bin_dir.mkdir()
        work.mkdir()
        description = "Questions\n```json\n" + json.dumps(OVERRIDE) + "\n```\n"
        (d / "show.json").write_text(json.dumps([{"id": "q-1", "description": description}]), encoding="utf-8")
        # fake tracker: fail `failures` times (counted in a file), then print the bead
        executable(bin_dir / "fake-tracker", f"""#!{BASH}
n=$(cat "{d}/calls" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "{d}/calls"
[ "$n" -gt {failures} ] || {{ echo "database timeout (attempt $n)" >&2; exit 1; }}
cat "{d}/show.json"
""")
        executable(bin_dir / "sleep", f"#!{BASH}\necho \"$1\" >> \"{d}/sleeps\"\n")
        executable(d / "preflight.py", "import sys\nprint('{}')\n")
        anchors = {"anchors": [{"id": "ANC-001", "status": "locked", "beads": {"plan_questions": "q-1"}}]}
        (d / "anchors.json").write_text(json.dumps(anchors), encoding="utf-8")
        env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", W=str(work), ROOT=str(d), SCRIPT=str(d / "preflight.py"),
                   ANCHORS=str(d / "anchors.json"), RUN_DIR=str(d / "runs"), ANCHOR_TRACKER="fake-tracker")
        proc = subprocess.run([BASH, "-c", override_loop(tracker)], env=env, capture_output=True, text=True, timeout=60)
        calls = int((d / "calls").read_text()) if (d / "calls").exists() else 0
        sleeps = (d / "sleeps").read_text().split() if (d / "sleeps").exists() else []
        overrides = json.loads((work / "overrides.json").read_text()) if (work / "overrides.json").exists() else None
        return proc, calls, sleeps, overrides

    def test_succeeds_within_three_attempts(self):
        for tracker in TRACKERS:
            for failures in (0, 1, 2):
                with self.subTest(tracker=tracker, failures=failures):
                    proc, calls, sleeps, overrides = self.run_loop(tracker, failures)
                    self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                    self.assertEqual(calls, failures + 1)
                    self.assertEqual(sleeps, [str(n) for n in range(1, failures + 1)])  # 1 s, then 2 s
                    self.assertEqual(overrides, {"ANC-001": OVERRIDE})

    def test_fails_after_three_attempts_with_the_last_error(self):
        for tracker in TRACKERS:
            with self.subTest(tracker=tracker):
                proc, calls, sleeps, overrides = self.run_loop(tracker, 3)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertEqual((calls, sleeps), (3, ["1", "2"]))  # no fourth call, no sleep after the last
                err = json.loads(proc.stdout)["error"]
                self.assertEqual(err["code"], "TRACKER.SHOW_FAILED")
                self.assertIn("failed after 3 attempts", err["message"])
                self.assertIn("database timeout (attempt 3)", err["message"])
                self.assertEqual(overrides, {})  # never a silent fallback with a partial override set


if __name__ == "__main__":
    unittest.main()
