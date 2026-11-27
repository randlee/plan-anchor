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


class RecordCleanupExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("sc-compose") is None:
            raise AssertionError("the sc-compose CLI is required to build the site examples (scripts/install_sc_compose_ci.py)")
        cls.tmp = tempfile.TemporaryDirectory(prefix="site-examples-")
        cls.out = Path(cls.tmp.name)
        proc = run_test_child([sys.executable, str(ROOT / "scripts" / "build-examples.py"), "--out", str(cls.out)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if proc.returncode != 0:
            raise AssertionError(f"build-examples failed (exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
        cls.built = cls.out / "record-cleanup"
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


if __name__ == "__main__":
    unittest.main()
