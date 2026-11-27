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
OVERLAP_NO = {"type": "choice", "choice": "no", "confidence": 1.0, "probabilities": {"yes": 0.0, "no": 1.0, "unclear": 0.0}}
# Real records, requests and Jev answers from the overlap prototype run against sc-agent's records (see its _source).
REAL = json.loads((Path(__file__).parent / "fixtures" / "trace_overlap.json").read_text(encoding="utf-8"))


def ans(yes: float) -> dict:
    rest = round((1 - yes) / 2, 6)
    return {"type": "choice", "choice": "yes" if yes >= 0.5 else "no", "confidence": max(yes, 1 - yes),
            "probabilities": {"yes": yes, "no": round(1 - yes - rest, 6), "unclear": rest}}


def cell(relates=0.0, serves=0.0, conflicts=0.0, exceeds=0.0) -> dict:
    return {"relates": ans(relates), "serves": ans(serves), "conflicts": ans(conflicts), "exceeds": ans(exceeds)}


def req(rid, statements, text=""):
    """A requirements-table record shaped as Raptor's import index serves it."""
    return {"id": rid, "title": f"{rid} title", "status": "Approved", "version": "0.1.0",
            "requirement_statement": {"text": text, "statements": statements}, "rationale": "Because.",
            "dependencies": {"text": "", "requires": [], "related": []}}


def adr(rid, decision):
    return {"id": rid, "title": f"{rid} title", "status": "Approved", "version": "0.1.0",
            "decision": {"text": decision, "chosen_approach": "", "key_principles": ["One owner per concern."]}}


def raptor_index(repo, requirements=(), decisions=(), issues=()):
    return {"metadata": {"repository": f"urn:raptor:repo:{repo}", "generated": "2026-11-26T00:00:00+00:00",
                         "files": 1, "records": len(requirements) + len(decisions)},
            "requirements": list(requirements), "decisions": list(decisions), "diagnostics": {"issues": list(issues)}}


CORE = raptor_index("core", requirements=[req("REQ-001", [{"modal": "Must", "text": "The tool MUST copy the legacy crates."},
                                                          {"modal": "Must", "text": "It shall log every copy."}],
                                              text="Definitions: a crate is a Rust package.")],
                    decisions=[adr("ADR-002", "Runtime crates must be written from scratch.")])
UI = raptor_index("ui", requirements=[req("NFR-003", [], text="Pages MUST load in one second.")],
                  issues=[{"file": "docs/NFR-004.md", "line": 4, "rule": "BAD_VALUE", "id": "NFR-004", "message": "InvalidVersion"}])


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.anchors = write(self.tmp, "anchors.json", record(anchor("ANC-001"), anchor("ANC-002", status="proposed",
                                                                                       statement="A different proposed anchor about pages.")))
        self.core = write(self.tmp, "core.json", CORE)
        self.ui = write(self.tmp, "ui.json", UI)

    def trace(self, answers, *extra):
        path = write(self.tmp, "answers.json", answers)
        return run_cli(["trace", "--anchors", self.anchors, "--index", self.core, "--index", self.ui, "--answers-file", path,
                        "--out-dir", str(Path(self.tmp) / "out"), *extra])

    def fake_raptor(self, index, exit_code=0):
        """A Raptor checkout whose importer writes ``index``: the stub sits at Raptor's CLI boundary, as judge-jev's does."""
        root = Path(self.tmp) / "raptor"
        (root / ".venv" / "bin").mkdir(parents=True)
        (root / ".venv" / "bin" / "python").symlink_to(sys.executable)
        write(root, "fixture.json", index)
        write(root, "scripts/extract.py", "import argparse, json, shutil, pathlib\n"
              "p = argparse.ArgumentParser(); p.add_argument('--project-root'); p.add_argument('--output')\n"
              "a = p.parse_args()\n"
              "assert pathlib.Path(a.project_root, '.raptor').is_dir()\n"
              f"shutil.copy({str(root / 'fixture.json')!r}, a.output)\n"
              f"issues = {len(index['diagnostics']['issues'])}\n"
              "print(json.dumps({'index': a.output, 'records': 0, 'issues': issues}))\n"
              f"raise SystemExit({exit_code})\n")
        repo = Path(self.tmp) / "repo"
        (repo / ".raptor").mkdir(parents=True)
        return str(root), str(repo)

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
                                "NFR-003/ANC-001": cell(relates=0.1)}, "--no-overlap")
        self.assertEqual(code, 0, out)
        trace = json.loads(Path(out["data"]["trace_path"]).read_text(encoding="utf-8"))
        self.assertEqual(trace["schema"], "plan-anchoring/trace/2")
        self.assertEqual([a["id"] for a in trace["anchors"]], ["ANC-001"])
        self.assertEqual({(c["record"], c["class"]) for c in trace["cells"]},
                         {("REQ-001", "serves"), ("ADR-002", "conflicts"), ("NFR-003", "none")})
        self.assertEqual(trace["thresholds"], {"conflicts": 0.5, "relation": 0.6, "exceeds": 0.6, "duplicate": 0.6, "possible": 0.4})
        self.assertIsNone(trace["overlap"])
        self.assertEqual(set(trace["question_digests"]), set(QUESTIONS))
        self.assertEqual(trace["summary"]["per_anchor"]["ANC-001"]["serves"], 1)
        self.assertEqual(trace["summary"]["records_with_no_relation"], ["NFR-003"])
        self.assertEqual(trace["summary"]["conflicts"], [{"record": "ADR-002", "anchor": "ANC-001"}])
        self.assertEqual(trace["answered_by"], "fixture")

    def test_thresholds_are_options(self):
        code, out = self.trace({"*": cell(relates=0.55)}, "--relation-threshold", "0.5", "--no-overlap")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["summary"]["totals"]["related"], 3)
        code, out = self.trace({"*": cell()}, "--exceeds-threshold", "1.5")
        self.assertEqual((code, out["error"]["code"]), (2, "VALIDATION.INPUT"))
        code, out = self.trace({"*": cell()}, "--duplicate-threshold", "-0.1")
        self.assertEqual((code, out["error"]["code"]), (2, "VALIDATION.INPUT"))

    def test_obligations_come_only_from_raptor(self):
        code, out = self.trace({"*": cell()})
        self.assertEqual(code, 0, out)
        trace = json.loads(Path(out["data"]["trace_path"]).read_text(encoding="utf-8"))
        recs = {r["id"]: r for r in trace["records"]}
        self.assertEqual(recs["REQ-001"]["obligations"], {"source": "raptor", "field": "requirement_statement.statements", "note": None,
                                                          "statements": CORE["requirements"][0]["requirement_statement"]["statements"]})
        self.assertEqual((recs["REQ-001"]["kind"], recs["ADR-002"]["kind"], recs["NFR-003"]["kind"]), ("REQ", "ADR", "NFR"))
        self.assertEqual(recs["REQ-001"]["repository"], "urn:raptor:repo:core")
        self.assertEqual(recs["REQ-001"]["raptor"], CORE["requirements"][0])
        # Raptor serves no statements: none are synthesized, though the text says MUST / must.
        for rid in ("NFR-003", "ADR-002"):
            self.assertIsNone(recs[rid]["obligations"]["statements"], rid)
            self.assertEqual(recs[rid]["obligations"]["note"], jj.RAPTOR_NO_OBLIGATIONS)

    def test_no_code_path_extracts_obligations_from_text(self):
        source = Path(jj.__file__).read_text(encoding="utf-8")
        for banned in ("must_sentences", "MUST_RE", "SENTENCE_SPLIT_RE", "record_glob", "record-glob", "extracted_by"):
            self.assertNotIn(banned, source)
        self.assertNotRegex(source, r"re\.compile\([^)]*(?i:must|shall)")
        self.assertFalse(hasattr(jj, "must_sentences"))
        code, out = run_cli(["trace", "--anchors", self.anchors, "--records", "x.jsonl"])
        self.assertEqual((code, out["error"]["code"]), (2, "VALIDATION.INPUT"))

    def test_ids_restrict_and_unserved_ids_are_listed(self):
        ids = write(self.tmp, "ids.txt", "REQ-001\nNFR-004\nREQ-404\n")
        code, out = self.trace({"*": cell()}, "--ids", ids)
        self.assertEqual(code, 0, out)
        trace = json.loads(Path(out["data"]["trace_path"]).read_text(encoding="utf-8"))
        self.assertEqual([r["id"] for r in trace["records"]], ["REQ-001"])
        self.assertEqual([(x["id"], x["reason"].split(":")[0]) for x in trace["not_served"]],
                         [("NFR-004", "Raptor did not import it"), ("REQ-404", "not in any Raptor index given")])

    def test_source_reads_through_the_raptor_checkout(self):
        root, repo = self.fake_raptor(CORE)
        answers = write(self.tmp, "answers.json", {"*": cell(serves=0.9)})
        code, out = run_cli(["trace", "--anchors", self.anchors, "--source", repo, "--raptor", root, "--answers-file", answers,
                             "--out-dir", str(Path(self.tmp) / "out"), "--no-overlap"])
        self.assertEqual(code, 0, out)
        trace = json.loads(Path(out["data"]["trace_path"]).read_text(encoding="utf-8"))
        self.assertEqual([r["id"] for r in trace["records"]], ["REQ-001", "ADR-002"])
        self.assertEqual(trace["raptor"]["root"], root)

    def test_raptor_import_with_diagnostics_is_read_and_a_crash_is_an_error(self):
        root, repo = self.fake_raptor(UI, exit_code=1)  # Raptor exits 1 when it imported with diagnostics
        code, out = run_cli(["trace", "--anchors", self.anchors, "--source", repo, "--raptor", root, "--dry-run",
                             "--out-dir", str(Path(self.tmp) / "out")])
        self.assertEqual((code, len(out["data"]["requests"])), (0, 1), out)
        shutil.rmtree(Path(self.tmp) / "raptor"); shutil.rmtree(repo)
        root, repo = self.fake_raptor(CORE, exit_code=3)
        code, out = run_cli(["trace", "--anchors", self.anchors, "--source", repo, "--raptor", root, "--dry-run",
                             "--out-dir", str(Path(self.tmp) / "out")])
        self.assertEqual((code, out["error"]["code"]), (2, "RAPTOR.IMPORT_FAILED"))

    def test_missing_raptor_is_a_typed_error_with_install_action(self):
        repo = Path(self.tmp) / "repo"
        (repo / ".raptor").mkdir(parents=True)
        for extra in ([], ["--raptor", str(Path(self.tmp) / "no-raptor")]):
            code, out = run_cli(["trace", "--anchors", self.anchors, "--source", str(repo), "--dry-run",
                                 "--out-dir", str(Path(self.tmp) / "out"), *extra])
            self.assertEqual((code, out["error"]["code"]), (2, "DEPENDENCY.RAPTOR"), extra)
            self.assertIn("git clone https://github.com/randlee/raptor", out["error"]["suggested_action"])

    def test_repository_without_raptor_inventory_is_a_typed_error(self):
        root, _ = self.fake_raptor(CORE)
        bare = Path(self.tmp) / "bare"
        bare.mkdir()
        code, out = run_cli(["trace", "--anchors", self.anchors, "--source", str(bare), "--raptor", root, "--dry-run",
                             "--out-dir", str(Path(self.tmp) / "out")])
        self.assertEqual((code, out["error"]["code"]), (2, "RAPTOR.NO_INVENTORY"))

    def test_non_record_subcommands_run_without_raptor(self):
        # No --raptor and no Raptor checkout anywhere: commands that read no REQ/NFR/ADR record still run.
        for argv in (["validate", "--anchors", self.anchors], ["lint", "--anchors", self.anchors],
                     ["trace", "--anchors", self.anchors, "--index", self.core, "--dry-run", "--out-dir", str(Path(self.tmp) / "o")]):
            code, out = run_cli(argv)
            self.assertEqual(code, 0, (argv, out))
            self.assertTrue(out["success"], argv)

    def test_annotations_merge_only_into_yellow_and_red(self):
        notes = write(self.tmp, "notes.json", [
            {"record": "ADR-002", "anchor": "ANC-001", "clauses": ["written from scratch"], "what": "Forbids the copy.",
             "remedy": "Copy instead.", "jev_disputed": False},
            {"record": "REQ-001", "anchor": "ANC-001", "clauses": [], "what": "x", "remedy": "y", "jev_disputed": True},
            {"record": "REQ-404", "anchor": "ANC-001", "clauses": [], "what": "x", "remedy": "y", "jev_disputed": False}])
        code, out = self.trace({"ADR-002/ANC-001": cell(conflicts=0.9), "*": cell(serves=0.9)}, "--annotations", notes, "--no-overlap")
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

    def test_malformed_indexes_are_typed_errors(self):
        dup = raptor_index("dup", requirements=[req("REQ-001", [])])
        for value, code_ in (("{not json", "INPUT.MALFORMED"), ({"requirements": []}, "INPUT.MALFORMED"),
                             (raptor_index("x", requirements=[req("bad id", [])]), "VALIDATION.INPUT"),
                             (dup, "VALIDATION.INPUT")):
            self.ui = write(self.tmp, "ui.json", value)
            code, out = self.trace({"*": cell()})
            self.assertEqual((code, out["error"]["code"]), (2, code_), value)
        code, out = run_cli(["trace", "--anchors", self.anchors, "--answers-file", write(self.tmp, "a.json", {"*": cell()})])
        self.assertEqual((code, out["error"]["code"]), (2, "VALIDATION.INPUT"))

    def test_missing_fixture_entry_fails_before_writing(self):
        code, out = self.trace({"REQ-001/ANC-001": cell()})
        self.assertEqual((code, out["error"]["code"]), (2, "FIXTURE.MISSING"))
        self.assertFalse((Path(self.tmp) / "out").exists())

    def test_dry_run_sends_the_record_as_raptor_serves_it(self):
        code, out = run_cli(["trace", "--anchors", self.anchors, "--index", self.core, "--index", self.ui,
                             "--dry-run", "--out-dir", str(Path(self.tmp) / "out")])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(out["data"]["requests"]), 3)
        self.assertFalse((Path(self.tmp) / "out").exists(), "a dry run writes nothing")
        first = out["data"]["requests"][0]
        self.assertEqual(set(first["request"]["state"]), {"record", "anchor"})
        self.assertEqual(first["request"]["state"]["record"], {"id": "REQ-001", "kind": "REQ", "repository": "urn:raptor:repo:core",
                                                               "raptor": CORE["requirements"][0]})
        self.assertEqual(first["request"]["questions"], jj.TRACE_QUESTIONS)

    @unittest.skipUnless(shutil.which("git"), "consent is looked up inside a git repository")
    def test_live_path_needs_remote_judge_consent(self):
        subprocess.run(["git", "init", "-q", self.tmp], check=True)
        code, out = run_cli(["trace", "--anchors", self.anchors, "--index", self.core,
                             "--repository-root", self.tmp, "--out-dir", str(Path(self.tmp) / "out")])
        self.assertEqual(code, 2)
        self.assertEqual(out["error"]["code"], "POLICY.REMOTE_JUDGE_DISABLED", out)

    @unittest.skipUnless(HAS_SC_COMPOSE, "sc-compose renders the report")
    def test_render_shows_green_and_red_panels(self):
        notes = write(self.tmp, "notes.json", [{"record": "ADR-002", "anchor": "ANC-001", "clauses": ["written from scratch"],
                                                "what": "Forbids the copy.", "remedy": "Copy instead.", "jev_disputed": True}])
        code, out = self.trace({"REQ-001/ANC-001": cell(serves=0.8), "ADR-002/ANC-001": cell(conflicts=0.7),
                                "NFR-003/ANC-001": cell(), "overlap": {"REQ_001_s0": OVERLAP_NO, "REQ_001_s1": OVERLAP_NO}},
                               "--annotations", notes)
        self.assertEqual(code, 0, out)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cr.main(["--trace", out["data"]["trace_path"], "--out", str(Path(self.tmp) / "report")])
        env = json.loads(buf.getvalue())
        self.assertEqual(rc, 0, env)
        self.assertEqual(env["data"]["cells"], 2)
        self.assertEqual(len(env["data"]["panels"]), 2 + 3 + 1)
        panels = {Path(p).name: Path(p).read_text(encoding="utf-8") for p in env["data"]["panels"]}
        for text in panels.values():
            xml.dom.minidom.parseString(text)
        cells_ = {n: t for n, t in panels.items() if "-cell-" in n}
        green = next(t for t in cells_.values() if "REQ-001" in t)
        red = next(t for t in cells_.values() if "ADR-002" in t)
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
        self.assertIn("Reviewer disputes Jev: Forbids the copy.", red)
        self.assertIn("reviewer text, not Jev", red)
        self.assertNotIn("reviewer text, not Jev", green)
        for heading in ("What conflicts", "Proposed remedy", "Anchor", "Record statements"):
            self.assertIn(f"<h3>{heading}</h3>", red)
        self.assertLess(red.index("What conflicts"), red.index("Proposed remedy"))
        self.assertLess(red.index("Proposed remedy"), red.index("<h3>Anchor</h3>"))
        self.assertIn("ADR-002 × ANC-001 — conflicts", red)
        self.assertIn("No obligation statements.", red)
        record_panels = [t for n, t in panels.items() if "-rec-" in n]
        anchor_panels = [t for n, t in panels.items() if "-anc-" in n]
        self.assertEqual((len(record_panels), len(anchor_panels)), (3, 1))
        adr_panel = next(t for t in record_panels if "ADR-002" in t)
        self.assertIn("Runtime crates must be written from scratch.", adr_panel)
        self.assertIn("<h3>Key principles</h3>", adr_panel)
        req_panel = next(t for t in record_panels if "REQ-001" in t)
        self.assertIn("It shall log every copy.", req_panel)
        self.assertIn("Definitions: a crate is a Rust package.", req_panel)
        self.assertIn(STATEMENT_START, anchor_panels[0])
        self.assertIn("copy the libraries from the legacy repo", anchor_panels[0])
        self.assertIn("<h3>Owner said</h3>", anchor_panels[0])
        for text in record_panels + anchor_panels:
            self.assertNotRegex(text, r">[a-z]+_[a-z_]+<|\[\d+\]|<table", "no snake_case keys, index paths or key/value tables")
        page = Path(env["data"]["html"]).read_text(encoding="utf-8")
        self.assertEqual(page.count('data-panel="'), 2 + 3 + 1)
        self.assertEqual(page.count('class="rec hdr" data-panel="rec-'), 3)
        self.assertEqual(page.count('class="anc hdr" data-panel="anc-'), 1)
        self.assertIn("c-none", page)
        grid = page[page.index('id="tab-grid"'):page.index('id="tab-dup"')]
        self.assertIn("<h3>Not covered by any anchor</h3>", grid)
        self.assertIn("<li>NFR-003</li>", grid)
        self.assertNotIn("NFR-003", page[page.index('id="tab-dup"'):page.index('id="side"')], "not a deletion candidate")
        with contextlib.redirect_stdout(io.StringIO()):
            cr.main(["--trace", out["data"]["trace_path"], "--out", str(Path(self.tmp) / "report"), "--name", "only", "--fields", "statements"])
        only = (Path(self.tmp) / "report" / "only" / "only-rec-REQ-001.xhtml").read_text(encoding="utf-8")
        self.assertIn("<h3>Statements</h3>", only)
        self.assertNotIn("<h3>Requirement</h3>", only)

    def test_render_refuses_a_non_trace_file(self):
        bad = write(self.tmp, "bad.json", {"schema": "other"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cr.main(["--trace", bad, "--out", self.tmp])
        self.assertEqual((rc, json.loads(buf.getvalue())["error"]["code"]), (2, "TRACE.INVALID"))


class TraceOverlapTests(unittest.TestCase):
    """Overlap on real data: ANC-001's column holds ADR-SAG-0021, REQ-SAG-0003 and REQ-SAG-0008; ANC-002's holds ADR-SAG-0004
    and REQ-SAG-0010. The cell answers are made up; the overlap requests and answers are the prototype's real ones."""
    COLUMNS = {"ANC-001": ("ADR-SAG-0021", "REQ-SAG-0003", "REQ-SAG-0008"), "ANC-002": ("ADR-SAG-0004", "REQ-SAG-0010")}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.anchors = write(self.tmp, "anchors.json", record(anchor("ANC-001"), anchor("ANC-002", statement="A second locked anchor.")))
        self.index = write(self.tmp, "index.json", REAL["index"])
        self.out = Path(self.tmp) / "out"

    def answers(self, overlap=True):
        ids = [r["id"] for t in ("requirements", "decisions") for r in REAL["index"][t]]
        got = {f"{rid}/{aid}": cell(serves=0.9) if rid in members else cell() for aid, members in self.COLUMNS.items() for rid in ids}
        if overlap:
            got.update({f"{item}/overlap": a["answers"] for item, a in REAL["answers"].items()})
        return write(self.tmp, "answers.json", got)

    def run_trace(self, *extra):
        return run_cli(["trace", "--anchors", self.anchors, "--index", self.index, "--out-dir", str(self.out), *extra])

    def test_candidate_pairs_come_from_the_cell_table(self):
        cells = [{"record": r, "anchor": "A1", "class": c} for r, c in (("R-3", "serves"), ("R-1", "related"), ("R-2", "conflicts"),
                                                                        ("R-9", "none"), ("R-8", "error"))]
        cells += [{"record": r, "anchor": "A2", "class": c} for r, c in (("R-2", "exceeds"), ("R-1", "serves"), ("R-4", "related"))]
        self.assertEqual(jj.overlap_partners(cells), {"R-1": ["R-2", "R-3", "R-4"], "R-2": ["R-3", "R-4"]})
        self.assertEqual(jj.overlap_partners([{"record": "R-1", "anchor": "A1", "class": "serves"}]), {})

    def test_one_request_per_item_with_the_real_question_ids_and_text(self):
        records = {}
        for path in (self.index,):
            records.update({r["id"]: r for r in jj.raptor_index_records(path).value["records"]})
        partners = {"ADR-SAG-0004": ["REQ-SAG-0010"], "ADR-SAG-0021": ["REQ-SAG-0003", "REQ-SAG-0008"], "REQ-SAG-0003": ["REQ-SAG-0008"]}
        jobs, asked = jj.overlap_jobs("jev", partners, records)
        self.assertEqual([j.item_id for j in jobs], list(partners))
        for job in jobs:
            self.assertEqual(job.body["state"], REAL["requests"][job.item_id]["state"], job.item_id)
            self.assertEqual(job.body["questions"], REAL["requests"][job.item_id]["questions"], job.item_id)
        self.assertEqual(asked[("ADR-SAG-0021", "REQ_SAG_0003_s1")][:2], ("REQ-SAG-0003", 1))
        adr = jj.record_statements(records["ADR-SAG-0004"])
        self.assertEqual(adr, [REAL["index"]["decisions"][1]["decision"]["text"]], "an ADR's decision is one block, never split")

    def test_real_answers_are_classified_and_summarised(self):
        code, out = self.run_trace("--answers-file", self.answers())
        self.assertEqual(code, 0, out)
        trace = json.loads(Path(out["data"]["trace_path"]).read_text(encoding="utf-8"))
        by = {(o["item"], o["partner"], o["statement_index"]): o for o in trace["overlap"]}
        self.assertEqual(len(by), 12 + 3 + 1)
        first = by[("ADR-SAG-0021", "REQ-SAG-0003", 1)]
        self.assertEqual((first["choice"], first["confidence"], first["class"]), ("yes", 0.98, "duplicate"))
        self.assertIn("<CLI>_LOG_ROOT", first["statement"])
        self.assertEqual(by[("ADR-SAG-0021", "REQ-SAG-0003", 5)]["class"], "possible")   # yes at 0.52
        self.assertEqual(by[("ADR-SAG-0021", "REQ-SAG-0003", 8)]["class"], "none")       # yes at 0.18
        self.assertEqual(by[("ADR-SAG-0021", "REQ-SAG-0003", 6)]["class"], "none")       # no at 0.68
        self.assertEqual([o["class"] for k, o in by.items() if k[0] == "ADR-SAG-0004"], ["none"])
        self.assertEqual([o["class"] for k, o in by.items() if k[0] == "REQ-SAG-0003"], ["none"] * 3)
        per = trace["summary"]["per_record"]
        self.assertEqual(per["REQ-SAG-0003"], {"statements_restated": 4, "statements_total": 9})
        self.assertEqual(per["REQ-SAG-0008"], {"statements_restated": 3, "statements_total": 3})
        self.assertEqual(per["REQ-SAG-0010"], {"statements_restated": 0, "statements_total": 1})
        self.assertEqual(trace["summary"]["fully_restated"], ["REQ-SAG-0008"])
        self.assertEqual(trace["summary"]["records_with_no_relation"], [])
        self.assertEqual((out["data"]["duplicates_pass"], out["data"]["duplicates_to_correct"]), (False, 7))
        self.assertEqual(out["data"]["message"], "7 duplicate statements must be corrected: keep each obligation in one record and "
                                                 "delete the other copy. See Correcting duplicates in references/record-trace.md.")
        self.assertEqual({o.get("action") for o in trace["overlap"] if o["class"] == "duplicate"}, {"correct"})
        self.assertNotIn("action", by[("ADR-SAG-0021", "REQ-SAG-0003", 5)], "a possible duplicate is not an action")
        code, out = self.run_trace("--answers-file", self.answers(), "--duplicate-threshold", "0.99")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["summary"]["fully_restated"], [], "REQ-SAG-0008 statements 0 and 1 are below 0.99")

    def test_no_overlap_sends_no_overlap_requests(self):
        code, out = self.run_trace("--answers-file", self.answers(overlap=False), "--no-overlap")
        self.assertEqual(code, 0, out)
        trace = json.loads(Path(out["data"]["trace_path"]).read_text(encoding="utf-8"))
        self.assertIsNone(trace["overlap"])
        self.assertNotIn("fully_restated", trace["summary"])
        self.assertIsNone(out["data"]["duplicates_pass"])
        code, out = self.run_trace("--answers-file", self.answers(overlap=False))
        self.assertEqual((code, out["error"]["code"]), (2, "FIXTURE.MISSING"), "with overlap on, the overlap requests are sent")
        self.assertIn("/overlap", out["error"]["message"])

    def test_dry_run_shows_requests_and_writes_nothing(self):
        code, out = self.run_trace("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(out["data"]["requests"]), 5 * 2)
        self.assertEqual({r["request"]["questions"]["serves"]["type"] for r in out["data"]["requests"]}, {"choice"})
        self.assertIn("not formed", out["data"]["overlap"])
        self.assertFalse(self.out.exists())

    def render(self, *extra, answers=None):
        code, out = self.run_trace("--answers-file", answers or self.answers(), *extra)
        self.assertEqual(code, 0, out)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cr.main(["--trace", out["data"]["trace_path"], "--out", str(Path(self.tmp) / "report")])
        env = json.loads(buf.getvalue())
        self.assertEqual(rc, 0, env)
        return env, Path(env["data"]["html"]).read_text(encoding="utf-8")

    @unittest.skipUnless(HAS_SC_COMPOSE, "sc-compose renders the report")
    def test_duplicates_tab_shows_a_badge_with_the_count(self):
        env, page = self.render()
        self.assertIn('data-tab="tab-dup">Duplicates <span class="badge">(!)</span> 7</button>', page)
        self.assertIn('class="tab active" role="tab" data-tab="tab-grid">Anchors × Records</button>', page)
        self.assertIn('id="tab-dup" hidden', page)
        self.assertEqual(env["data"]["duplicates"], 7)
        self.assertEqual(page.count('<tr class="hdr" data-panel="dup-'), 7)
        self.assertIn('<td>ADR-SAG-0021 restates REQ-SAG-0003</td><td>When `&lt;CLI&gt;_LOG_ROOT` is set and non-empty', page)
        self.assertIn("<td>0.98</td>", page)
        self.assertIn("7 duplicate statements must be corrected", page)
        self.assertEqual(page.count('#correcting-duplicates">correct: Correcting duplicates</a>'), 7)
        self.assertIn("Fully restated: delete this record unless it holds an obligation no other record states.", page)
        self.assertNotIn("Serves no anchor", page)
        self.assertIn("<h2>Fully restated records (deletion candidates)</h2>", page)
        self.assertIn("<li>REQ-SAG-0008</li>", page)
        self.assertNotIn("Records serving no anchor", page)
        self.assertEqual(len(env["data"]["pair_panels"]), 2)
        pair = next(Path(x).read_text(encoding="utf-8") for x in env["data"]["pair_panels"] if "REQ-SAG-0008" in x)
        xml.dom.minidom.parseString(pair)
        self.assertIn("ADR-SAG-0021 restates REQ-SAG-0008", pair)
        self.assertIn("The wheel MUST NOT depend on the `sc-observability` Python package.", pair)
        self.assertIn("<h3>Decision</h3>", pair, "the ADR side shows its decision")
        self.assertIn('id="dup-ADR-SAG-0021-REQ-SAG-0008"', page, "the row's panel is in the shared side panel")

    @unittest.skipUnless(HAS_SC_COMPOSE, "sc-compose renders the report")
    def test_duplicates_tab_without_duplicates_has_no_badge(self):
        no = json.loads(Path(self.answers()).read_text(encoding="utf-8"))
        for item, a in REAL["answers"].items():
            no[f"{item}/overlap"] = {q: OVERLAP_NO for q in a["answers"]}
        code, out = self.run_trace("--answers-file", write(self.tmp, "no.json", no))
        self.assertEqual((out["data"]["duplicates_pass"], out["data"]["duplicates_to_correct"], out["data"]["message"]), (True, 0, None))
        _, page = self.render(answers=write(self.tmp, "no.json", no))
        self.assertIn('data-tab="tab-dup">Duplicates 0</button>', page)
        self.assertNotIn('class="badge"', page)
        self.assertIn("No duplicated statements.", page)
        self.assertNotIn("must be corrected", page)
        _, page = self.render("--no-overlap", answers=self.answers(overlap=False))
        self.assertIn('data-tab="tab-dup">Duplicates</button>', page)
        self.assertNotIn('class="badge"', page)
        self.assertIn("Duplicates: not run", page)


STATEMENT_START = "The runtime crates are created by copying"

if __name__ == "__main__":
    unittest.main()
