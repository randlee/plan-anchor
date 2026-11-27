"""The site's record-cleanup example builds offline from its checked-in inputs with the current scripts.

scripts/build-examples.py renders the scripts as an install does, runs `jev_judge.py trace` on the real
answers in inputs/answers.json (a fixture: no network) and renders the report with change_report.py. A
missing Jev answer fails the build (FIXTURE.MISSING), so a passing build also proves answer coverage.
"""
import json
from pathlib import Path
import re
import shutil
from child_support import run_test_child
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "site" / "examples" / "record-cleanup"


def build(out: Path, *extra: str) -> Path:
    if shutil.which("sc-compose") is None:
        raise AssertionError("the sc-compose CLI is required to build the site examples (scripts/install_sc_compose_ci.py)")
    proc = run_test_child([sys.executable, str(ROOT / "scripts" / "build-examples.py"), "--out", str(out), *extra],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if proc.returncode != 0:
        raise AssertionError(f"build-examples failed (exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    return out / "record-cleanup"


class RecordCleanupExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="site-examples-")
        cls.out = Path(cls.tmp.name)
        cls.built = build(cls.out)
        cls.page = (cls.built / "report.html").read_text(encoding="utf-8")
        cls.trace = json.loads((cls.built / "trace.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_report_has_its_three_tabs(self):
        for tab in ("tab-grid", "tab-dup", "tab-prop"):
            self.assertIn(f'data-tab="{tab}"', self.page)
            self.assertIn(f'id="{tab}"', self.page)

    def test_report_has_proposal_panels(self):
        panels = sorted((self.built / "report").glob("*prop-*.xhtml"))
        proposals = json.loads((EXAMPLE / "inputs" / "proposals.json").read_text(encoding="utf-8"))["proposals"]
        self.assertGreaterEqual(len(panels), 1)
        self.assertEqual(len(panels), len(proposals))

    def test_every_answer_is_real_and_used(self):
        answers = json.loads((EXAMPLE / "inputs" / "answers.json").read_text(encoding="utf-8"))
        self.assertNotIn("*", answers, "the example uses only the real answers, never a '*' fallback")
        self.assertNotIn("overlap", answers)
        self.assertNotIn("trace", answers)
        used = {f"{c['record']}/{c['anchor']}" for c in self.trace["cells"]} | \
               {f"{o['item']}/overlap" for o in self.trace["overlap"]}
        self.assertEqual(set(answers), used)

    def test_trace_is_the_listed_records_against_every_locked_anchor(self):
        ids = [x for x in (EXAMPLE / "inputs" / "ids.txt").read_text(encoding="utf-8").split() if x]
        anchors = json.loads((EXAMPLE / "inputs" / "anchors.json").read_text(encoding="utf-8"))["anchors"]
        locked = [a["id"] for a in anchors if a["status"] == "locked"]
        self.assertEqual(self.trace["not_served"], [])
        self.assertEqual(sorted(r["id"] for r in self.trace["records"]), sorted(ids))
        self.assertEqual(len(self.trace["cells"]), len(ids) * len(locked))

    def test_readme_names_the_page_the_examples_index_links(self):
        readme = (EXAMPLE / "README.md").read_text(encoding="utf-8")
        page = re.search(r"^\*\*Page:\*\*\s*\[[^\]]*\]\(([^)\s]+)\)", readme, re.MULTILINE)
        self.assertIsNotNone(page)
        self.assertTrue((self.built / page.group(1)).is_file())


class RecordCleanupAnnotationsTests(unittest.TestCase):
    """build-examples.py passes inputs/annotations.json to `trace --annotations` when it exists, and builds without it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="site-examples-ann-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.inputs = self.tmp / "inputs"
        shutil.copytree(EXAMPLE / "inputs", self.inputs)
        (self.inputs / "annotations.json").unlink(missing_ok=True)

    def red_and_yellow(self, built: Path) -> list:
        trace = json.loads((built / "trace.json").read_text(encoding="utf-8"))
        return [c for c in trace["cells"] if c["class"] in ("exceeds", "conflicts")]

    def test_without_annotations_every_red_and_yellow_cell_is_listed(self):
        built = build(self.tmp / "without", "--inputs", str(self.inputs))
        cells = self.red_and_yellow(built)
        self.assertGreaterEqual(len(cells), 1)
        self.assertFalse(any("annotation" in c for c in cells))
        page = (built / "report.html").read_text(encoding="utf-8")
        self.assertIn(f"<h3>Cells without a reviewer annotation ({len(cells)})</h3>", page)

    def test_with_annotations_they_are_merged_and_nothing_is_listed(self):
        cells = self.red_and_yellow(build(self.tmp / "first", "--inputs", str(self.inputs)))
        notes = [{"record": c["record"], "anchor": c["anchor"], "clauses": [], "what": f"test annotation {c['record']}/{c['anchor']}",
                  "remedy": "test remedy", "jev_disputed": False} for c in cells]
        (self.inputs / "annotations.json").write_text(json.dumps(notes), encoding="utf-8")
        built = build(self.tmp / "with", "--inputs", str(self.inputs))
        self.assertTrue(all(c["annotation"]["provenance"] == "reviewer-agent" for c in self.red_and_yellow(built)))
        page = (built / "report.html").read_text(encoding="utf-8")
        self.assertNotIn("Cells without a reviewer annotation", page)
        self.assertNotIn("No reviewer annotation yet.", page)
        c = cells[0]
        self.assertIn(f"test annotation {c['record']}/{c['anchor']}", page)


if __name__ == "__main__":
    unittest.main()
