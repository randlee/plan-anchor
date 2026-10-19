"""Prompt regressions for anchor tracker selection across shipped docs and agents."""

from pathlib import Path
import re
import unittest

from layout_support import SKILL_SRC, TRACKERS, rendered_agent, rendered_skill


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
HARNESSES = ("claude", "codex", "cursor")
TEXT_SUFFIXES = {".md", ".py", ".j2", ".json", ".yaml", ".yml", ".txt"}
NEGATION = re.compile(r"\b(never|not|no|outside)\b", re.IGNORECASE)


def shipped_text_files():
    files = [p for p in PLUGIN.rglob("*") if p.is_file() and p.suffix in TEXT_SUFFIXES]
    files += [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "CHANGELOG.md"]
    files += sorted((ROOT / "docs").rglob("*.md"))
    return [p for p in files if p.is_file()]


class TrackerPromptRegressionTests(unittest.TestCase):
    def test_no_text_recommends_bd_init(self):
        offenders = []
        for path in shipped_text_files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\bbd init\b", line) and not NEGATION.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
                if "--proxied-server" in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "bd init must never be recommended")

    def test_tracker_script_never_builds_a_bd_init_argv(self):
        source = (SKILL_SRC / "scripts" / "anchor_tracker.py.j2").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"""["']bd["']\s*,\s*["']init["']""")
        self.assertIn('argv = [cli_path, "init"]', source)
        self.assertIn('if tracker != "br":', source)

    def test_hardcoded_tracker_assignment_is_gone(self):
        paths = []
        for tracker in TRACKERS:
            skill = rendered_skill(tracker)
            paths += [skill / "SKILL.md", *sorted((skill / "references").glob("*.md"))]
            paths += [rendered_agent(tracker, h, n) for h in HARNESSES for n in ("anchor-plan-review.md", "anchor-sprint-review.md")]
        for path in paths:
            with self.subTest(path=path.relative_to(path.parents[3]).as_posix()):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"ANCHOR_TRACKER=(bd|br)\b")

    def test_planning_gate_obtains_tracker_from_resolve(self):
        for tracker in TRACKERS:
            with self.subTest(tracker=tracker):
                self._planning_gate_obtains_tracker_from_resolve(tracker)

    def _planning_gate_obtains_tracker_from_resolve(self, tracker):
        SKILL = rendered_skill(tracker)
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('python3 "$T" resolve', skill)
        self.assertIn("jq -r '.data.tracker // empty'", skill)
        self.assertIn(".sc/plan-anchor/settings.yaml", skill)
        for name in ("planning-review-workflow.md", "agent-delegation-workflow.md"):
            with self.subTest(reference=name):
                self.assertIn("anchor_tracker.py resolve", (SKILL / "references" / name).read_text(encoding="utf-8"))
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                prompt = rendered_agent(tracker, harness, "anchor-plan-review.md").read_text(encoding="utf-8")
                self.assertIn('anchor_tracker.py" resolve --repository-root "$ROOT"', prompt)

    def test_development_gate_resolves_tracker_and_takes_caller_text(self):
        """REQ-057 / ADR-014: the development gate selects the tracker like the planning gate and judges the caller's text."""
        for tracker, harness in ((t, h) for t in TRACKERS for h in HARNESSES):
            with self.subTest(tracker=tracker, harness=harness):
                prompt = rendered_agent(tracker, harness, "anchor-sprint-review.md").read_text(encoding="utf-8")
                self.assertIn('anchor_tracker.py" resolve --repository-root "$ROOT"', prompt)
                self.assertIn('when `anchor_tracker` was supplied and differs', prompt)
                self.assertIn('"$ANCHOR_TRACKER" show "$qb" --json', prompt)
                self.assertIn('--evidence "$item_file"', prompt)
                self.assertIn('--item-file "$W/item.txt"', prompt)
                self.assertNotRegex(prompt, r"\bbd (show|children)\b")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        entry = changelog.split("\n## 0.7.0 ")[1].split("\n## ")[0]  # the release that made the change
        self.assertIn("ADR-014", entry)
        self.assertIn("REQ-057", entry)

    def test_installation_doc_covers_br_and_selection(self):
        doc = (rendered_skill("br") / "references" / "installation-and-troubleshooting.md").read_text(encoding="utf-8")
        for needle in ("br init", "br sync --flush-only", "beads.db", "0.7.x", "PyYAML",
                       "python3 -m pip install pyyaml", ".sc/plan-anchor/settings.yaml",
                       "Dolt provisioning is outside this skill", "## Anchor tracker selection"):
            with self.subTest(needle=needle):
                self.assertIn(needle, doc)


if __name__ == "__main__":
    unittest.main()
