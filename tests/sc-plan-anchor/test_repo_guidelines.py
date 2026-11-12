"""The optional repository guidelines file, .sc/plan-anchor/plan-anchor-repo-guidelines.md.

The repository owns it; the installer never writes it (test_install.py). ``find_guidelines``
finds the nearest one, ``plan_anchor_settings.py show`` reports it, and the skill, the
workflows, triage, the drift review and the tuner read it. Absent, nothing changes.
"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

from test_jev_judge import run_cli  # noqa: F401 - puts scripts/ on sys.path
import plan_anchor_paths as paths  # noqa: E402
import plan_anchor_settings as settings_mod  # noqa: E402
from layout_support import TARGETS, TRACKERS, rendered_agent, rendered_skill  # noqa: E402

HAS_YAML = importlib.util.find_spec("yaml") is not None
NO_YAML = "PyYAML is not installed (python3 -m pip install pyyaml); show needs it"
REL = ".sc/plan-anchor/plan-anchor-repo-guidelines.md"
DEFINITION = "## Repository guidelines (optional)"


def show(root):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = settings_mod.main(["show", "--repository-root", str(root)])
    return code, json.loads(buf.getvalue())


class Tree:
    def __init__(self, test):
        td = tempfile.TemporaryDirectory()
        test.addCleanup(td.cleanup)
        self.root = Path(td.name).resolve() / "parent"
        self.repo = self.root / "repo"
        self.child = self.repo / "src"
        self.child.mkdir(parents=True)
        (self.repo / ".git").mkdir()

    def write(self, base, text="# notes\n"):
        path = base.joinpath(*REL.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class FindGuidelinesTests(unittest.TestCase):
    def test_absent_is_none(self):
        tree = Tree(self)
        self.assertEqual(paths.GUIDELINES_RELPATH, REL)
        self.assertIsNone(paths.find_guidelines(tree.child, home=tree.root.parent))

    def test_the_nearest_file_wins(self):
        tree = Tree(self)
        outer = tree.write(tree.root)
        self.assertEqual(paths.find_guidelines(tree.child, home=tree.root.parent), outer)
        inner = tree.write(tree.repo)
        self.assertEqual(paths.find_guidelines(tree.child, home=tree.root.parent), inner)

    def test_a_directory_at_the_path_is_not_a_file(self):
        tree = Tree(self)
        tree.repo.joinpath(*REL.split("/")).mkdir(parents=True)
        self.assertIsNone(paths.find_guidelines(tree.child, home=tree.root.parent))

    def test_the_walk_stops_before_home(self):
        tree = Tree(self)
        tree.write(tree.root)
        self.assertIsNone(paths.find_guidelines(tree.child, home=tree.root))


@unittest.skipUnless(HAS_YAML, NO_YAML)
class ShowTests(unittest.TestCase):
    def test_show_reports_the_path_or_null(self):
        tree = Tree(self)
        code, out = show(tree.repo)
        self.assertEqual((code, out["data"]["repo_guidelines_path"]), (0, None))
        path = tree.write(tree.repo)
        code, out = show(tree.repo)
        self.assertEqual((code, out["data"]["repo_guidelines_path"]), (0, str(path)))


class ShippedTextTests(unittest.TestCase):
    READERS = (
        "references/capture-and-maintenance-workflow.md",
        "references/question-tuning-workflow.md",
        "references/planning-review-workflow.md",
        "references/development-review-workflow.md",
        "references/triage-and-iteration.md",
    )

    def test_the_rule_is_defined_once_and_cited_by_each_reader(self):
        for tracker in TRACKERS:
            skill = rendered_skill(tracker)
            texts = {p.relative_to(skill).as_posix(): p.read_text(encoding="utf-8")
                     for p in skill.rglob("*.md")}
            with self.subTest(tracker=tracker):
                self.assertEqual([k for k, t in texts.items() if DEFINITION in t], ["references/anchor-document.md"])
                self.assertIn(REL, texts["references/anchor-document.md"])
                self.assertIn("repo_guidelines_path", texts["SKILL.md"])
                for rel in self.READERS:
                    self.assertIn("repository guidelines", texts[rel], rel)
                    self.assertIn("anchor-document.md", texts[rel], rel)
                self.assertIn("never sent to Jev whole", texts["references/jev-api.md"])
                drift = texts["references/triage-and-iteration.md"].split("**Drift review", 1)[1].split("\n", 1)[0]
                self.assertIn("the repository guidelines when present", drift)
                self.assertIn("plan-anchor-repo-guidelines.example.md", texts["references/anchor-document.md"])
                self.assertTrue((skill / "assets" / "examples" / "plan-anchor-repo-guidelines.example.md").is_file())

    def test_the_tuner_reads_it_before_freezing_its_oracle(self):
        for tracker in TRACKERS:
            for target in TARGETS:
                text = rendered_agent(tracker, target, "anchor-tuning.md").read_text(encoding="utf-8")
                with self.subTest(tracker=tracker, target=target):
                    self.assertIn("read any repository guidelines", text)
                    self.assertIn("`anchor-document.md`", text)
                    self.assertLess(text.index("read any repository guidelines"), text.index("freeze and hash an oracle"))


if __name__ == "__main__":
    unittest.main()
