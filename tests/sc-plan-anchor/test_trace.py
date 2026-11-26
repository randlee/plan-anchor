"""jev_judge.py trace and change_report.py --trace: offline, with --answers-file fixtures; no Jev call."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.dom.minidom

from jev_test_support import jj, run_cli
from jev_inputs import anchor, record, write
from layout_support import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import change_report as cr  # noqa: E402

HAS_SC_COMPOSE = shutil.which("sc-compose") is not None
QUESTIONS = ("relates", "serves", "conflicts", "exceeds")


def ans(yes: float) -> dict:
    rest = round((1 - yes) / 2, 6)
    return {"type": "choice", "choice": "yes" if yes >= 0.5 else "no", "confidence": max(yes, 1 - yes),
            "probabilities": {"yes": yes, "no": round(1 - yes - rest, 6), "unclear": rest}}


def cell(relates=0.0, serves=0.0, conflicts=0.0, exceeds=0.0) -> dict:
    return {"relates": ans(relates), "serves": ans(serves), "conflicts": ans(conflicts), "exceeds": ans(exceeds)}


RECORDS = [
    {"id": "REQ-001", "repo": "core", "text": "The tool MUST copy the legacy crates. It shall log every copy.\nIt keeps a cache."},
    {"id": "ADR-002", "repo": "core", "text": "Runtime crates must be written from scratch."},
    {"id": "NFR-003", "repo": "ui", "text": "Pages load in one second."},
]


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.anchors = write(self.tmp, "anchors.json", record(anchor("ANC-001"), anchor("ANC-002", status="proposed",
                                                                                       statement="A different proposed anchor about pages.")))
        self.records = write(self.tmp, "records.jsonl", "".join(json.dumps(r) + "\n" for r in RECORDS))

    def trace(self, answers, *extra):
        path = write(self.tmp, "answers.json", answers)
        return run_cli(["trace", "--anchors", self.anchors, "--records", self.records, "--answers-file", path,
                        "--out-dir", str(Path(self.tmp) / "out"), *extra])

    def test_classification_boundaries(self):
        cases = [
            (cell(conflicts=0.5), "conflicts"), (cell(conflicts=0.49, relates=0.59, serves=0.59), "none"),
            (cell(relates=0.6), "related"), (cell(serves=0.6), "serves"), (cell(serves=0.6, exceeds=0.6), "exceeds"),
            (cell(relates=0.6, exceeds=0.59), "related"), (cell(conflicts=0.5, serves=0.9, exceeds=0.9), "conflicts"),
            (cell(exceeds=0.9), "none"),
        ]
        for answers, expected in cases:
            p = {q: answers[q]["probabilities"]["yes"] for q in QUESTIONS}
            self.assertEqual(jj.trace_class(p, 0.5, 0.6, 0.6), expected, p)

    def test_trace_writes_cells_summary_and_only_locked_anchors(self):
        code, out = self.trace({"REQ-001/ANC-001": cell(serves=0.8), "ADR-002/ANC-001": cell(conflicts=0.7, relates=0.9),
                                "NFR-003/ANC-001": cell(relates=0.1)})
        self.assertEqual(code, 0, out)
        trace = json.loads(Path(out["data"]["trace_path"]).read_text(encoding="utf-8"))
        self.assertEqual(trace["schema"], "plan-anchoring/trace/1")
        self.assertEqual([a["id"] for a in trace["anchors"]], ["ANC-001"])
        self.assertEqual({(c["record"], c["class"]) for c in trace["cells"]},
                         {("REQ-001", "serves"), ("ADR-002", "conflicts"), ("NFR-003", "none")})
        self.assertEqual(trace["thresholds"], {"conflicts": 0.5, "relation": 0.6, "exceeds": 0.6})
        self.assertEqual(set(trace["question_digests"]), set(QUESTIONS))
        self.assertEqual(trace["summary"]["per_anchor"]["ANC-001"]["serves"], 1)
        self.assertEqual(trace["summary"]["records_with_no_relation"], ["NFR-003"])
        self.assertEqual(trace["summary"]["conflicts"], [{"record": "ADR-002", "anchor": "ANC-001"}])
        self.assertEqual(trace["answered_by"], "fixture")

    def test_thresholds_are_options(self):
        code, out = self.trace({"*": cell(relates=0.55)}, "--relation-threshold", "0.5")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["summary"]["totals"]["related"], 3)
        code, out = self.trace({"*": cell()}, "--exceeds-threshold", "1.5")
        self.assertEqual((code, out["error"]["code"]), (2, "VALIDATION.INPUT"))

    def test_must_extraction_is_labelled(self):
        self.assertEqual(jj.must_sentences(RECORDS[0]["text"]), ["The tool MUST copy the legacy crates.", "It shall log every copy."])
        code, out = self.trace({"*": cell()})
        trace = json.loads(Path(out["data"]["trace_path"]).read_text(encoding="utf-8"))
        musts = trace["records"][0]["must_statements"]
        self.assertEqual(musts["extracted_by"], "regex")
        self.assertEqual(len(musts["sentences"]), 2)

    def test_annotations_merge_only_into_yellow_and_red(self):
        notes = write(self.tmp, "notes.json", [
            {"record": "ADR-002", "anchor": "ANC-001", "clauses": ["written from scratch"], "what": "Forbids the copy.",
             "remedy": "Copy instead.", "jev_disputed": False},
            {"record": "REQ-001", "anchor": "ANC-001", "clauses": [], "what": "x", "remedy": "y", "jev_disputed": True},
            {"record": "REQ-404", "anchor": "ANC-001", "clauses": [], "what": "x", "remedy": "y", "jev_disputed": False}])
        code, out = self.trace({"ADR-002/ANC-001": cell(conflicts=0.9), "*": cell(serves=0.9)}, "--annotations", notes)
        self.assertEqual(code, 0, out)
        trace = json.loads(Path(out["data"]["trace_path"]).read_text(encoding="utf-8"))
        by = {c["record"]: c for c in trace["cells"]}
        note = by["ADR-002"]["annotation"]
        self.assertEqual(note["provenance"], "reviewer-agent")
        self.assertEqual(note["provenance_label"], "written by a reviewer agent, not Jev")
        self.assertEqual(note["remedy"], "Copy instead.")
        self.assertNotIn("annotation", by["REQ-001"])
        self.assertEqual(len(out["data"]["warnings"]), 2)

    def test_no_locked_anchor_is_a_typed_error(self):
        self.anchors = write(self.tmp, "anchors.json", record(anchor("ANC-001", status="proposed")))
        code, out = self.trace({"*": cell()})
        self.assertEqual((code, out["success"], out["error"]["code"]), (2, False, "ANCHOR.NONE_LOCKED"))

    def test_malformed_records_are_typed_errors(self):
        for text, code_ in (("{not json\n", "INPUT.MALFORMED"), (json.dumps({"id": "R1", "repo": "x", "text": ""}) + "\n", "INPUT.MALFORMED"),
                            (json.dumps({"id": "bad id", "repo": "x", "text": "t"}) + "\n", "VALIDATION.INPUT"),
                            ("".join(json.dumps({"id": "R1", "repo": "x", "text": "t"}) + "\n" for _ in range(2)), "VALIDATION.INPUT"),
                            ("\n", "INPUT.EMPTY")):
            self.records = write(self.tmp, "records.jsonl", text)
            code, out = self.trace({"*": cell()})
            self.assertEqual((code, out["error"]["code"]), (2, code_), text)

    def test_missing_fixture_entry_fails_before_writing(self):
        code, out = self.trace({"REQ-001/ANC-001": cell()})
        self.assertEqual((code, out["error"]["code"]), (2, "FIXTURE.MISSING"))
        self.assertFalse((Path(self.tmp) / "out").exists())

    def test_record_glob_and_dry_run(self):
        for r in RECORDS:
            write(self.tmp, f"recs/{r['id']}.md", r["text"])
        code, out = run_cli(["trace", "--anchors", self.anchors, "--record-glob", str(Path(self.tmp) / "recs" / "*.md"),
                             "--dry-run", "--out-dir", str(Path(self.tmp) / "out")])
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["requests"], 3)
        first = json.loads(Path(out["data"]["requests_path"]).read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(set(first["request"]["state"]), {"record", "anchor"})
        self.assertEqual(first["request"]["questions"], jj.TRACE_QUESTIONS)
        code, out = run_cli(["trace", "--anchors", self.anchors, "--records", self.records, "--record-glob", "x"])
        self.assertEqual((code, out["error"]["code"]), (2, "VALIDATION.INPUT"))

    @unittest.skipUnless(shutil.which("git"), "consent is looked up inside a git repository")
    def test_live_path_needs_remote_judge_consent(self):
        subprocess.run(["git", "init", "-q", self.tmp], check=True)
        code, out = run_cli(["trace", "--anchors", self.anchors, "--records", self.records,
                             "--repository-root", self.tmp, "--out-dir", str(Path(self.tmp) / "out")])
        self.assertEqual(code, 2)
        self.assertEqual(out["error"]["code"], "POLICY.REMOTE_JUDGE_DISABLED", out)

    @unittest.skipUnless(HAS_SC_COMPOSE, "sc-compose renders the report")
    def test_render_shows_green_and_red_panels(self):
        notes = write(self.tmp, "notes.json", [{"record": "ADR-002", "anchor": "ANC-001", "clauses": ["written from scratch"],
                                                "what": "Forbids the copy.", "remedy": "Copy instead.", "jev_disputed": True}])
        code, out = self.trace({"REQ-001/ANC-001": cell(serves=0.8), "ADR-002/ANC-001": cell(conflicts=0.7),
                                "NFR-003/ANC-001": cell()}, "--annotations", notes)
        self.assertEqual(code, 0, out)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cr.main(["--trace", out["data"]["trace_path"], "--out", str(Path(self.tmp) / "report")])
        env = json.loads(buf.getvalue())
        self.assertEqual(rc, 0, env)
        self.assertEqual(env["data"]["cells"], 2)
        panels = {Path(p).name: Path(p).read_text(encoding="utf-8") for p in env["data"]["panels"]}
        for text in panels.values():
            xml.dom.minidom.parseString(text)
        green = next(t for t in panels.values() if "REQ-001" in t)
        red = next(t for t in panels.values() if "ADR-002" in t)
        for t in (green, red):
            self.assertIn(STATEMENT_START, t)
            self.assertIn("copy the libraries from the legacy repo", t)
            self.assertIn("the runtime crates", t)
        self.assertIn("The tool MUST copy the legacy crates.", green)
        self.assertIn("0.80", green)
        self.assertNotIn("Proposed remedy", green)
        self.assertIn("c-serves", green)
        self.assertIn("c-conflicts", red)
        self.assertIn("written from scratch", red)
        self.assertIn("Forbids the copy.", red)
        self.assertIn("Copy instead.", red)
        self.assertIn("Jev disputed on reading", red)
        self.assertIn("written by a reviewer agent, not Jev", red)
        self.assertIn("Runtime crates must be written from scratch.", red)
        page = Path(env["data"]["html"]).read_text(encoding="utf-8")
        self.assertEqual(page.count('data-panel="'), 2)
        self.assertIn("c-none", page)

    def test_render_refuses_a_non_trace_file(self):
        bad = write(self.tmp, "bad.json", {"schema": "other"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cr.main(["--trace", bad, "--out", self.tmp])
        self.assertEqual((rc, json.loads(buf.getvalue())["error"]["code"]), (2, "TRACE.INVALID"))


STATEMENT_START = "The runtime crates are created by copying"

if __name__ == "__main__":
    unittest.main()
