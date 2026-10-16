import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from test_plan_source import load_source, sprint


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"


class PlanReviewPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_source()
        cls.prompt = (PLUGIN / ".codex/agents/anchor-plan-review.md").read_text(encoding="utf-8")
        block = re.search(r"   ```python\n(.*?)   ```", cls.prompt, re.DOTALL)
        cls.materializer = "\n".join(line[3:] for line in block.group(1).splitlines())

    def materialize(self, item, item_id="A1"):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "materialize.py"
            descriptor = root / "item.json"
            output = root / "item.txt"
            script.write_text(self.materializer, encoding="utf-8")
            descriptor.write_text(json.dumps(item), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(script), str(descriptor), item_id, str(output)],
                capture_output=True, text=True,
            )
            return result, output.read_bytes() if output.exists() else None

    def descriptor(self, source_kind="markdown"):
        text = self.source.normalized_text(sprint("A1", "Keep all details: café.\n"))
        return {
            "id": "A1", "title": "Work", "text": text,
            "source_kind": source_kind,
            "normalized_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }

    def test_all_source_kinds_preserve_identical_complete_text(self):
        outputs = []
        for source_kind in ("markdown", "bd", "br"):
            with self.subTest(source_kind=source_kind):
                item = self.descriptor(source_kind)
                result, output = self.materialize(item)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output, item["text"].encode("utf-8"))
                outputs.append(output)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])

    def test_real_tracker_descriptors_ignore_ancillary_fields(self):
        for tracker in ("bd", "br"):
            plan = self.source.discover_tracker([{
                "id": "project.1", "description": sprint("A1"),
                "title": "Not the sprint title", "acceptance_criteria": "Do not append",
                "design": "Do not append", "notes": "Do not append",
            }], phase="phase-a", tracker=tracker, epic="project")
            item = plan["sprints"][0]
            result, output = self.materialize(item)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output, self.source.normalized_text(sprint("A1")).encode("utf-8"))

    def test_invalid_descriptors_never_write_judge_input(self):
        changes = (
            {"id": "A2"},
            {"source_kind": "shell"},
            {"title": 123},
            {"normalized_sha256": "0" * 64},
            {"text": "Changed after discovery"},
            {"text": None},
        )
        for change in changes:
            with self.subTest(change=change):
                item = self.descriptor()
                item.update(change)
                result, output = self.materialize(item)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(output)

    def test_non_normalized_text_rejected_even_with_normalized_digest(self):
        item = self.descriptor()
        item["text"] = item["text"].replace("\n", "\r\n")
        result, output = self.materialize(item)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(output)

    def test_markdown_with_br_does_not_require_bd_or_a_planning_bead(self):
        self.assertIn('`anchor_tracker` (string, required for descriptor mode', self.prompt)
        self.assertIn('bd` or `br`, selected for anchor/question storage independently', self.prompt)
        self.assertIn('"$ANCHOR_TRACKER" show "$qb"', self.prompt)
        self.assertNotIn('bd show', self.prompt)
        self.assertNotIn('bd --version', self.prompt)
        self.assertNotIn('`bead_id` (string, required)', self.prompt)
        self.assertIn('--evidence "$item_path"', self.prompt)
        self.assertIn('never shorten planning items', self.prompt)
        self.assertIn('Never set `PLAN_ANCHOR_ALLOW_REMOTE_JUDGE`', self.prompt)

    def test_legacy_fields_remain_without_descriptor_fallback(self):
        self.assertIn('`bead_id` (string, optional legacy input)', self.prompt)
        self.assertIn('"bead_id": null', self.prompt)
        self.assertIn('Never fall back from a failed descriptor to legacy mode.', self.prompt)
        self.assertIn('"$ANCHOR_TRACKER" show "$bead_id"', self.prompt)
        self.assertIn('compose-item --show-json "$W/bead.json" --for plan', self.prompt)


if __name__ == "__main__":
    unittest.main()
