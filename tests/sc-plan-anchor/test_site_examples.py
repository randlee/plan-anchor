"""The site's record-cleanup example builds offline from its checked-in inputs with the current scripts.

scripts/build-examples.py renders the scripts as an install does, runs `jev_judge.py trace` on the real
answers in inputs/answers.json (a fixture: no network) and renders the report with change_report.py. A
missing Jev answer fails the build (FIXTURE.MISSING), so a passing build also proves answer coverage.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
from child_support import run_test_child
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "site" / "examples" / "record-cleanup"


def build(out: Path, *extra: str) -> Path:
    if shutil.which("sc-compose") is None:
        raise AssertionError("the sc-compose CLI is required to build the site examples (scripts/install_sc_compose_ci.py)")
    if "--records-checkout" not in extra:
        extra = ("--no-provenance", *extra)  # offline: no clone of the records' repository
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

    def test_no_build_machine_path_and_the_guidance_link_resolves(self):
        text = (self.built / "trace.json").read_text(encoding="utf-8") + self.page
        for root in {str(ROOT), str(Path(tempfile.gettempdir()).resolve()), tempfile.gettempdir(), "file://"}:
            self.assertNotIn(root, text)
        self.assertEqual({r["index"] for r in self.trace["records"]}, {"inputs/raptor-sc-agent.json"})
        self.assertIn('href="record-trace.md#correcting-duplicates"', self.page)
        self.assertIn("## Correcting duplicates", (self.built / "record-trace.md").read_text(encoding="utf-8"))

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

    def red_yellow_and_duplicates(self, built: Path) -> tuple:
        trace = json.loads((built / "trace.json").read_text(encoding="utf-8"))
        return ([c for c in trace["cells"] if c["class"] in ("exceeds", "conflicts")],
                [o for o in trace["overlap"] if o["class"] == "duplicate"])

    def test_without_annotations_every_red_and_yellow_cell_and_duplicate_is_listed(self):
        built = build(self.tmp / "without", "--inputs", str(self.inputs))
        cells, dups = self.red_yellow_and_duplicates(built)
        self.assertGreaterEqual(len(cells), 1)
        self.assertFalse(any("annotation" in c for c in cells + dups))
        page = (built / "report.html").read_text(encoding="utf-8")
        self.assertIn(f"<h3>Cells and duplicates without an annotation with git history ({len(cells) + len(dups)})</h3>", page)

    def test_with_annotations_they_are_merged_and_nothing_is_listed(self):
        cells, dups = self.red_yellow_and_duplicates(build(self.tmp / "first", "--inputs", str(self.inputs)))
        common = {"clauses": [], "remedy": "test remedy", "jev_disputed": False, "no_provenance": "test: no history"}
        notes = [dict(common, record=c["record"], anchor=c["anchor"], what=f"test annotation {c['record']}/{c['anchor']}") for c in cells]
        notes += [dict(common, duplicate=f"{o['item']}/{o['partner']}/{o['statement_index']}", what="test duplicate") for o in dups]
        (self.inputs / "annotations.json").write_text(json.dumps(notes), encoding="utf-8")
        built = build(self.tmp / "with", "--inputs", str(self.inputs))
        self.assertTrue((built / "report" / "sources" / "annotations.json").is_file(), "change_report.py merged and saved them")
        page = (built / "report.html").read_text(encoding="utf-8")
        self.assertNotIn("without an annotation with git history", page)
        self.assertNotIn("No reviewer annotation yet.", page)
        c = cells[0]
        self.assertIn(f"test annotation {c['record']}/{c['anchor']}", page)
        self.assertIn("test: no history", page)


@unittest.skipUnless(shutil.which("git"), "provenance is read from git")
class RecordCleanupProvenanceTests(unittest.TestCase):
    """With a records checkout, the trace carries real git provenance, and an index that does not match the files at
    inputs/source.json's commit fails the build."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="site-examples-prov-", ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.inputs = self.tmp / "inputs"
        shutil.copytree(EXAMPLE / "inputs", self.inputs)
        (self.inputs / "annotations.json").unlink(missing_ok=True)
        trace = json.loads((build(self.tmp / "offline", "--inputs", str(self.inputs)) / "trace.json").read_text(encoding="utf-8"))
        self.statements = [x["text"] for r in trace["records"] for x in (r["obligations"]["statements"] or [])]

    def repo(self, statements):
        repo = self.tmp / "records"
        run = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a],
                                        check=True, capture_output=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "records.md").write_text("".join(f"- {t}\n" for t in statements), encoding="utf-8")
        run("add", "-A")
        run("commit", "-q", "-m", "Add the records")
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        (self.inputs / "source.json").write_text(json.dumps({"repository": str(repo), "commit": sha}), encoding="utf-8")
        return repo

    def test_real_provenance_from_the_records_checkout(self):
        repo = self.repo(self.statements)
        built = build(self.tmp / "prov", "--inputs", str(self.inputs), "--records-checkout", str(repo))
        rows = [x for r in json.loads((built / "trace.json").read_text(encoding="utf-8"))["records"] for x in r.get("provenance") or []]
        self.assertGreaterEqual(len(rows), 1)
        self.assertTrue(all(x["provenance"]["summary"] == "Add the records" for x in rows), rows[:2])

    def test_an_index_that_does_not_match_the_commit_fails(self):
        repo = self.repo(self.statements[1:])
        proc = run_test_child([sys.executable, str(ROOT / "scripts" / "build-examples.py"), "--out", str(self.tmp / "bad"),
                               "--inputs", str(self.inputs), "--records-checkout", str(repo)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("the Raptor index does not match", proc.stderr)


if __name__ == "__main__":
    unittest.main()
