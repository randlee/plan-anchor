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
                                "NFR-003/ANC-001": cell(relates=0.1)})
        self.assertEqual(code, 0, out)
        trace = json.loads(Path(out["data"]["trace_path"]).read_text(encoding="utf-8"))
        self.assertEqual(trace["schema"], "plan-anchoring/trace/2")
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
                             "--out-dir", str(Path(self.tmp) / "out")])
        self.assertEqual(code, 0, out)
        trace = json.loads(Path(out["data"]["trace_path"]).read_text(encoding="utf-8"))
        self.assertEqual([r["id"] for r in trace["records"]], ["REQ-001", "ADR-002"])
        self.assertEqual(trace["raptor"]["root"], root)

    def test_raptor_import_with_diagnostics_is_read_and_a_crash_is_an_error(self):
        root, repo = self.fake_raptor(UI, exit_code=1)  # Raptor exits 1 when it imported with diagnostics
        code, out = run_cli(["trace", "--anchors", self.anchors, "--source", repo, "--raptor", root, "--dry-run",
                             "--out-dir", str(Path(self.tmp) / "out")])
        self.assertEqual((code, out["data"]["requests"]), (0, 1), out)
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
        self.assertEqual(out["data"]["requests"], 3)
        first = json.loads(Path(out["data"]["requests_path"]).read_text(encoding="utf-8").splitlines()[0])
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
                                "NFR-003/ANC-001": cell()}, "--annotations", notes)
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
        self.assertIn("Jev disputed on reading", red)
        self.assertIn("written by a reviewer agent, not Jev", red)
        self.assertIn("No obligation statements.", red)
        record_panels = [t for n, t in panels.items() if "-rec-" in n]
        anchor_panels = [t for n, t in panels.items() if "-anc-" in n]
        self.assertEqual((len(record_panels), len(anchor_panels)), (3, 1))
        adr_panel = next(t for t in record_panels if "ADR-002" in t)
        self.assertIn("Runtime crates must be written from scratch.", adr_panel)
        self.assertIn("decision.key_principles[1]", adr_panel)
        req_panel = next(t for t in record_panels if "REQ-001" in t)
        self.assertIn("It shall log every copy.", req_panel)
        self.assertIn("Definitions: a crate is a Rust package.", req_panel)
        self.assertIn(STATEMENT_START, anchor_panels[0])
        self.assertIn("copy the libraries from the legacy repo", anchor_panels[0])
        self.assertIn("stated_by", anchor_panels[0])
        page = Path(env["data"]["html"]).read_text(encoding="utf-8")
        self.assertEqual(page.count('data-panel="'), 2 + 3 + 1)
        self.assertEqual(page.count('class="rec hdr" data-panel="rec-'), 3)
        self.assertEqual(page.count('class="anc hdr" data-panel="anc-'), 1)
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
