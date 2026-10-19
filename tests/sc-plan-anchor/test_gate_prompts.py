"""Both gate prompts judge the sprint text the caller already wrote (ADR-014, REQ-057).

The caller passes that text as ``item_file``; no gate rediscovers or rebuilds the
sprint, and plan_source.py is no longer shipped.
"""

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from layout_support import SCRIPTS, SKILL_SRC, TRACKERS, rendered_agent, rendered_skill


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
SCRIPT = SCRIPTS / "jev_judge.py"
EXAMPLE_ANCHORS = SKILL_SRC / "assets" / "examples" / "anchors.example.json"
HARNESSES = ("claude", "codex", "cursor")
GATES = ("anchor-plan-review.md", "anchor-sprint-review.md")
RETIRED = re.compile(r"plan_source|plan-source|descriptor|discover-|item_path|SOURCE\.DESCRIPTOR|sprint_id|bead_id")

# A sprint written the way atm-core phase-bi writes its beads: no Sprint title, no phase table.
FREE_FORM = """# bi-2 Anchor data model

## Goal

Store anchors with their exclusions in the record.

## Deliverables

- `anchors.json` schema field `exclude`
- validation for duplicate items

## Does Not Close

- CLI options (bi-3)
"""


def prompts():
    """Every gate prompt as installed, for each tracker and harness (fresh renders)."""
    for tracker in TRACKERS:
        for harness in HARNESSES:
            for name in GATES:
                yield f"{tracker}/{harness}", name, rendered_agent(tracker, harness, name).read_text(encoding="utf-8")


class GatePromptTests(unittest.TestCase):
    def test_both_gates_take_the_callers_text_as_item_file(self):
        for harness, name, prompt in prompts():
            with self.subTest(harness=harness, agent=name):
                self.assertIn("`item_file` (string, required)", prompt)
                self.assertIn("exactly as the caller wrote it", prompt)
                self.assertIn("Any headings and layout are accepted", prompt)
                self.assertIn('--evidence "$item_file"', prompt)
                self.assertIn("Return `VALIDATION.INPUT` when `item_id` or `item_file` is missing.", prompt)
                self.assertIn("--item-file", prompt)

    def test_no_gate_references_plan_source_descriptors_or_discovery(self):
        for harness, name, prompt in prompts():
            with self.subTest(harness=harness, agent=name):
                self.assertEqual(RETIRED.findall(prompt), [])
                self.assertNotIn("```python", prompt)  # no materializer

    def test_both_gates_resolve_the_tracker_for_question_beads(self):
        for harness, name, prompt in prompts():
            with self.subTest(harness=harness, agent=name):
                self.assertIn('anchor_tracker.py" resolve --repository-root "$ROOT"', prompt)
                self.assertIn('"$ANCHOR_TRACKER" show "$qb" --json', prompt)
                self.assertNotRegex(prompt, r"ANCHOR_TRACKER=(bd|br)\b")

    def test_sprint_review_passes_excluded_cells_through(self):
        for harness, name, prompt in prompts():
            if name != "anchor-sprint-review.md":
                continue
            with self.subTest(harness=harness):
                self.assertIn("An `excluded` cell (`summary.excluded`) was not judged and passes", prompt)

    def test_plan_source_is_not_shipped(self):
        self.assertFalse((SKILL_SRC / "scripts" / "plan_source.py").exists())
        self.assertFalse((SKILL_SRC / "references" / "plan-source-contract.md.j2").exists())
        shipped = []
        for tracker in TRACKERS:
            skill = rendered_skill(tracker)
            self.assertFalse((skill / "scripts" / "plan_source.py").exists())
            self.assertFalse((skill / "references" / "plan-source-contract.md").exists())
            shipped += [skill / "SKILL.md", *sorted((skill / "references").glob("*.md"))]
        for path in shipped:
            with self.subTest(path=path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"plan_source|plan-source-contract|discover-(markdown|tracker)")


class FreeFormSprintDryRunTests(unittest.TestCase):
    """judge accepts any sprint layout and sends it unchanged."""

    def test_free_form_sprint_builds_a_request_at_both_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = Path(tmp) / "item.txt"
            item.write_text(FREE_FORM, encoding="utf-8")
            for gate in ("plan", "dev"):
                with self.subTest(gate=gate):
                    proc = subprocess.run(
                        [sys.executable, str(SCRIPT), "judge", "--anchors", str(EXAMPLE_ANCHORS), "--gate", gate,
                         "--all", "--item-id", "bi-1", "--item-title", "Anchor data model",
                         "--item-file", str(item), "--run-dir", str(Path(tmp) / f"runs-{gate}"), "--dry-run"],
                        capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                    out = json.loads(proc.stdout)
                    self.assertTrue(out["success"])
                    data = out["data"]
                    self.assertEqual((data["gate"], data["dry_run"], data["item"]["truncated"]), (gate, True, False))
                    self.assertTrue(data["requests"])
                    for request in data["requests"]:
                        self.assertEqual(request["state"]["item"], {"id": "bi-1", "title": "Anchor data model", "text": FREE_FORM})
                    self.assertTrue(Path(data["run_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
