"""change_report.py: the owner's HTML report of a planning round's anchor and plan-item changes.

The end-to-end cases build a real git repository (anchors.json at a baseline commit and now, gate runs,
a committed item file) and render with the sc-compose CLI, as an install does. The tracker CLI is the
one boundary faked: ``<tracker> show`` and, for bd, ``bd history`` answer from fixtures; br history is a
real committed ``.beads/issues.jsonl``. No Jev call is made.
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.dom.minidom

from layout_support import PLUGIN, SCRIPTS, SKILL_SRC, TEST_TRACKER  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import change_report as cr  # noqa: E402

HAS_YAML = importlib.util.find_spec("yaml") is not None
HAS_JSONSCHEMA = importlib.util.find_spec("jsonschema") is not None
HAS_SC_COMPOSE = shutil.which("sc-compose") is not None
HAS_GIT = shutil.which("git") is not None
SCHEMA = SKILL_SRC / "assets" / "schemas" / "drift-review.schema.json"


def drift_doc():
    return {
        "schema": "plan-anchoring/drift-review/1",
        "reviewed_at": "2026-10-11",
        "compared": "anchors.json base -> HEAD; items ex-1, ex-2",
        "findings": [
            {"id": "M1", "severity": "material", "location": "ex-1 design", "what_changed": "Dropped the copy step.",
             "authority": {"ref": "ANC-001", "quote": "copy the libraries from the legacy repo"},
             "suggested_fix": "Restore the copy step.", "status": "fixed", "fix_note": "Restored; gate re-run passes."},
            {"id": "m2", "severity": "minor", "location": "ANC-001 scope", "what_changed": "Scope <narrowed>.",
             "authority": {"ref": "ANC-001", "quote": "the runtime crates"},
             "suggested_fix": "Widen it again.", "status": "open", "fix_note": ""},
        ],
        "acceptable_choices": [{"location": "ex-2", "note": "Names the crate legacy-core."}],
        "confirmations": [{"area": "Anchors", "note": "No quote changed."}],
    }


class DiffTests(unittest.TestCase):
    def test_word_diff_escapes_text_and_marks_changes(self):
        out = cr.word_diff("keep <b>old</b> tail", "keep <b>new</b> tail & more")
        self.assertNotIn("<b>", out)
        self.assertIn("<del>&lt;b&gt;old&lt;/b&gt;</del>", out)
        self.assertIn("<ins>&lt;b&gt;new&lt;/b&gt;</ins>", out)
        self.assertIn("&amp;", out)

    def test_line_diff_rows(self):
        out = cr.line_diff("a\nb\nc", "a\nB\nc\nd <x>")
        self.assertIn('<div class="eq">a</div>', out)
        self.assertIn('<div class="ch"><del>b</del><ins>B</ins></div>', out)
        self.assertIn('<div class="ad">+ d &lt;x&gt;</div>', out)
        self.assertNotIn("<x>", out)

    def test_issue_url_is_empty_without_a_template(self):
        self.assertEqual(cr.issue_url(None, "ex-1"), "")
        self.assertEqual(cr.issue_url("https://t.example/i/{id}", ""), "")
        self.assertEqual(cr.issue_url("https://t.example/i/{id}", "ex 1/a"), "https://t.example/i/ex%201%2Fa")

    def test_when_reads_tracker_and_run_times(self):
        self.assertEqual(cr.when("2026-11-10T02:34:58.132Z"), cr.when("2026-11-10T02:34:58.132000+00:00"))
        self.assertLess(cr.when("2026-11-09T23:19:34+00:00"), cr.when("2026-11-10T00:00:00.123456789Z"))
        self.assertIsNone(cr.when("yesterday"))


class DriftSchemaTests(unittest.TestCase):
    def test_valid_review_has_no_problems(self):
        self.assertEqual(cr.drift_problems(drift_doc()), [])

    def test_each_rule(self):
        cases = {
            "severity": lambda d: d["findings"][0].update(severity="medium"),
            "status": lambda d: d["findings"][0].update(status="done"),
            "fix_note must say": lambda d: d["findings"][0].update(fix_note=""),
            "unknown key": lambda d: d["findings"][0].update(extra=1),
            "authority": lambda d: d["findings"][0].update(authority={"ref": "ANC-001"}),
            "not unique": lambda d: d["findings"][1].update(id="M1"),
            "schema must be": lambda d: d.update(schema="drift/0"),
            "confirmations must be an array": lambda d: d.pop("confirmations"),
            "note must be": lambda d: d["acceptable_choices"][0].update(note=" "),
        }
        for needle, mutate in cases.items():
            with self.subTest(needle=needle):
                doc = drift_doc()
                mutate(doc)
                problems = cr.drift_problems(doc)
                self.assertTrue(any(needle in p for p in problems), problems)

    @unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema is not installed")
    def test_schema_file_agrees_with_the_script(self):
        import jsonschema

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        validator.validate(drift_doc())
        for mutate in (lambda d: d["findings"][0].update(severity="medium"),
                       lambda d: d["findings"][0].update(fix_note=""),
                       lambda d: d["findings"][0].update(extra=1),
                       lambda d: d.pop("confirmations")):
            doc = drift_doc()
            mutate(doc)
            self.assertTrue(cr.drift_problems(doc))
            self.assertFalse(validator.is_valid(doc))
        self.assertEqual(schema["properties"]["findings"]["items"]["properties"]["status"]["enum"],
                         list(cr.FINDING_STATUSES))
        self.assertEqual(schema["properties"]["findings"]["items"]["properties"]["severity"]["enum"],
                         list(cr.SEVERITIES))


def anchor(aid, status="locked", statement="The runtime crates are copied from the legacy repo.", **extra):
    rec = {"id": aid, "source_type": "ANC", "statement": statement, "quote": "copy the libraries from the legacy repo",
           "scope": "the runtime crates", "kind": "directive", "deterministic_check": "",
           "fixtures": {"pass": ["Copies the crates."], "fail": ["Writes the crates from scratch."]},
           "version": 1, "status": status, "beads": {"anchor": f"bead-{aid.lower()}"}, "history": [{"at": "t0", "event": "created"}]}
    rec.update(extra)
    return rec


def run_record(item, created, passed, counts, failing=(), excluded=(), source=""):
    return {"schema": "plan-anchoring/run/1", "run_id": f"plan-{created}-{item}", "gate": "plan",
            "created_at": created, "item": {"id": item, "title": f"Title {item}", "source": source},
            "dry_run": False, "fixture": False, "results": [],
            "summary": {"counts": counts, "failing": list(failing), "pass": passed,
                        "excluded": [{"anchor_id": a, "reason": r} for a, r in excluded]}}


ITEM_BEFORE = {"id": "ex-1", "title": "Sprint 1: copy", "description": "Copy <crates>.",
               "acceptance_criteria": "- builds\n- old line", "design": "same"}
ITEM_NOW = {"id": "ex-1", "title": "Sprint 1: copy", "description": "Copy <crates>.",
            "acceptance_criteria": "- builds\n- new line\n- <script>alert(1)</script>", "design": "same"}


class Project:
    """A git repository with a baseline anchors.json, a changed one, runs for two items, and a tracker fake."""

    def __init__(self, test, settings=None):
        td = tempfile.TemporaryDirectory()
        test.addCleanup(td.cleanup)
        self.root = Path(td.name).resolve() / "repo"
        self.plan = self.root / "docs" / "plans" / "phase-a"
        (self.plan / "anchor-runs").mkdir(parents=True)
        self.out = Path(td.name).resolve() / "out"
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.anchors = self.plan / "anchors.json"
        old = {"schema": "plan-anchoring/anchors/1", "plan": "phase-a",
               "anchors": [anchor("ANC-001"), anchor("ANC-002", status="proposed"), anchor("ANC-003", status="proposed")]}
        self.anchors.write_text(json.dumps(old), encoding="utf-8")
        item_file = self.plan / "sprint-2.md"
        item_file.write_text("## Sprint 2\nWrite the parser.\n", encoding="utf-8")
        if TEST_TRACKER == "br":
            beads = self.root / ".beads"
            beads.mkdir()
            (beads / "issues.jsonl").write_text(json.dumps(ITEM_BEFORE) + "\n", encoding="utf-8")
        if settings is not None:
            path = self.root / ".sc" / "plan-anchor" / "settings.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(settings, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "baseline", env_date="2026-10-09T00:00:00Z")
        self.baseline = self.git("rev-parse", "HEAD").strip()
        new = copy.deepcopy(old)
        a1 = new["anchors"][0]
        a1.update(statement="The runtime crates are copied from the legacy repo, then trimmed.", version=2,
                  exclude=[{"item": "ex-2", "reason": "Sprint 2 writes no runtime crate."}])
        a1["history"].append({"at": "t1", "event": "excluded", "item": "ex-2", "reason": "Sprint 2 writes no runtime crate."})
        new["anchors"][1].update(status="retired", version=2)
        new["anchors"][1]["history"].append({"at": "t1", "event": "retired", "reason": "covered by <ANC-001>"})
        new["anchors"].append(anchor("ANC-004", statement="New."))
        self.anchors.write_text(json.dumps(new), encoding="utf-8")
        item_file.write_text("## Sprint 2\nWrite the parser and its tests.\n", encoding="utf-8")
        if TEST_TRACKER == "br":
            (self.root / ".beads" / "issues.jsonl").write_text(json.dumps(ITEM_NOW) + "\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "round", env_date="2026-10-12T00:00:00Z")
        runs = [run_record("ex-1", "2026-10-10T00:00:00+00:00", False, {"satisfied": 1, "underspecified": 1}, ["ANC-001"]),
                run_record("ex-1", "2026-10-11T00:00:00+00:00", True, {"satisfied": 2}),
                run_record("ex-2", "2026-10-10T00:00:01+00:00", False, {"contradicted": 1, "not_applicable": 1},
                           ["ANC-001"], source=str(item_file)),
                run_record("ex-2", "2026-10-11T00:00:01+00:00", True, {"not_applicable": 1, "excluded": 1},
                           excluded=[("ANC-001", "Sprint 2 writes no runtime crate.")], source=str(item_file))]
        for n, run in enumerate(runs):
            (self.plan / "anchor-runs" / f"plan-2026101{n}T000000Z-{run['item']['id']}.json").write_text(json.dumps(run))
        dry = run_record("ex-1", "2026-10-12T00:00:00+00:00", False, {"satisfied": 0})
        dry["dry_run"] = True
        (self.plan / "anchor-runs" / "plan-20261012T000000Z-ex-1.json").write_text(json.dumps(dry))
        self.calls = []

    def git(self, *argv, env_date=None):
        env = dict(os.environ)
        if env_date:
            env.update(GIT_AUTHOR_DATE=env_date, GIT_COMMITTER_DATE=env_date)
        return subprocess.run(["git", *argv], cwd=self.root, capture_output=True, text=True, check=True, env=env).stdout

    def runner(self, argv, cwd):
        self.calls.append(argv)
        if argv[0] == cr.TRACKER and argv[1] == "show":
            if argv[2] == "ex-1":
                return 0, json.dumps([ITEM_NOW]), ""
            return 1, "", f"issue {argv[2]} not found"
        if argv[0] == "bd" and argv[1] == "history" and argv[2] == "ex-1":
            return 0, json.dumps([
                {"CommitDate": "2026-10-09T12:00:00Z", "Issue": ITEM_BEFORE},
                {"CommitDate": "2026-10-10T12:00:00.123Z", "Issue": ITEM_NOW},
            ]), ""
        return cr.run_command(argv, cwd)

    def tuning(self):
        folder = self.plan / "tune" / "ANC-001" / "t1"
        folder.mkdir(parents=True)
        (folder / "oracle.frozen.json").write_text(json.dumps({"anchor_id": "ANC-001"}))
        table = [{"baseline_exact": n < 6} for n in range(9)]
        (folder / "result_vars.json").write_text(json.dumps({"data": {
            "accepted": True, "acceptance_table": table, "semantic_score": {"stable_cases": 9}}}))
        return folder / "result_vars.json"

    def fixture_check(self, name, ok):
        path = self.plan / f"{name}.json"
        path.write_text(json.dumps({"success": True, "data": {"checks": [
            {"anchor_id": "ANC-001", "expected_ok": ok}, {"anchor_id": "ANC-001", "expected_ok": True}]}}))
        return path

    def main(self, *extra):
        argv = ["--anchors", str(self.anchors), "--baseline-rev", self.baseline, "--out", str(self.out),
                "--repository-root", str(self.root), *extra]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cr.main(argv, run=self.runner)
        return code, json.loads(buf.getvalue())


@unittest.skipUnless(HAS_GIT and HAS_SC_COMPOSE and HAS_YAML, "needs git, the sc-compose CLI and PyYAML")
class EndToEndTests(unittest.TestCase):
    def render(self, settings=None, drift=True):
        project = Project(self, settings)
        extra = ["--tuning-result", str(project.tuning()),
                 "--fixture-checks", str(project.fixture_check("before", False)),
                 "--fixture-checks", str(project.fixture_check("after", True))]
        if drift:
            path = project.plan / "drift.json"
            path.write_text(json.dumps(drift_doc()), encoding="utf-8")
            extra += ["--drift-file", str(path)]
        code, out = project.main(*extra)
        self.assertEqual(code, 0, out)
        return project, out["data"]

    def test_report_package_and_scores(self):
        project, data = self.render()
        page = Path(data["html"]).read_text(encoding="utf-8")
        model = json.loads(Path(data["sidecar"]).read_text(encoding="utf-8"))
        self.assertEqual(Path(data["html"]).parent, project.out)
        self.assertEqual(Path(data["sidecar"]), project.out / "change-report.json")
        self.assertEqual((data["items"], data["anchors"], data["status"]), (2, 3, "DRIFT"))
        self.assertEqual(data["drift"], {"findings": 2, "open": 1})
        for panel in data["panels"]:
            xml.dom.minidom.parse(panel)  # each panel is well-formed XHTML
            self.assertIn(Path(panel).read_text(encoding="utf-8"), page)
        items = {i["id"]: i for i in model["items"]}
        ex1, ex2 = items["ex-1"], items["ex-2"]
        self.assertEqual((ex1["first"]["score"], ex1["last"]["score"], ex1["runs"]), ("1/2", "2/2", 2))  # dry run skipped
        self.assertEqual((ex1["first"]["status"], ex1["last"]["status"]), ("fail", "pass"))
        self.assertEqual(ex1["text_source"], cr.TRACKER)
        self.assertEqual([c["field"] for c in ex1["changes"]], ["acceptance_criteria"])
        self.assertEqual(ex1["changes"][0]["before"], ITEM_BEFORE["acceptance_criteria"])
        self.assertEqual((ex2["first"]["score"], ex2["last"]["score"]), ("0/1", "0/0"))
        self.assertEqual(ex2["exclusions"], [{"anchor_id": "ANC-001", "reason": "Sprint 2 writes no runtime crate.", "added": True}])
        self.assertEqual([c["field"] for c in ex2["changes"]], ["item text"])  # not a tracker issue: the committed item file
        self.assertIn("Write the parser.", ex2["changes"][0]["before"])
        anchors = {a["id"]: a for a in model["anchors"]}
        self.assertEqual(sorted(anchors), ["ANC-001", "ANC-002", "ANC-004"])  # ANC-003: proposed and unchanged
        a1 = anchors["ANC-001"]
        self.assertEqual([c["field"] for c in a1["changes"]], ["statement"])
        self.assertEqual((a1["fixtures_before"], a1["fixtures_after"]), ("1/2", "2/2"))
        self.assertEqual((a1["questions_default"], a1["questions_tuned"]), ("6/9", "9/9"))
        self.assertEqual(a1["exclusions"][0]["item"], "ex-2")
        self.assertEqual([h["event"] for h in a1["history"]], ["excluded"])
        self.assertEqual((anchors["ANC-002"]["status_before"], anchors["ANC-002"]["status"]), ("proposed", "retired"))
        self.assertEqual(anchors["ANC-004"]["status_before"], "absent")
        self.assertIn("<del>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<script>alert(1)", page)
        self.assertIn("Restored; gate re-run passes.", page)
        self.assertIn("Scope &lt;narrowed&gt;.", page)
        self.assertNotIn('href="http', page)  # no issue_url_template: ids are plain text
        if TEST_TRACKER == "bd":
            self.assertIn(["bd", "history", "ex-1", "--json"], project.calls)
        else:
            self.assertTrue(any(c[:2] == ["git", "show"] and c[2].endswith(":.beads/issues.jsonl") for c in project.calls))

    def test_issue_url_template_links_every_id(self):
        _, data = self.render(settings="schema_version: 1\nissue_url_template: \"https://tracker.example/i/{id}\"\n",
                              drift=False)
        page = Path(data["html"]).read_text(encoding="utf-8")
        for ident in ("ex-1", "ex-2", "bead-anc-001"):
            self.assertIn(f'href="https://tracker.example/i/{ident}"', page)
        self.assertNotIn("drift-review", page.split("<nav")[0])

    def test_invalid_drift_file_is_typed(self):
        project = Project(self)
        bad = drift_doc()
        bad["findings"][0]["status"] = "done"
        path = project.plan / "drift.json"
        path.write_text(json.dumps(bad))
        code, out = project.main("--drift-file", str(path))
        self.assertEqual((code, out["error"]["code"]), (2, "DRIFT.INVALID"))
        self.assertTrue(out["data"]["problems"])
        self.assertFalse(project.out.exists())

    def test_unknown_baseline_is_typed(self):
        project = Project(self)
        project.baseline = "no-such-rev"
        code, out = project.main()
        self.assertEqual((code, out["error"]["code"]), (2, "GIT.BASELINE"))

    def test_item_filter_and_missing_item_warning(self):
        project = Project(self)
        code, out = project.main("--item", "ex-2", "--item", "ex-9")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["items"], 1)
        self.assertIn("no plan run found for item ex-9", out["data"]["warnings"])


class InputErrorTests(unittest.TestCase):
    def test_missing_anchors_file_is_script_io(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cr.main(["--anchors", "/no/such/anchors.json", "--baseline-rev", "HEAD", "--out", "/tmp/x"])
        self.assertEqual((code, json.loads(buf.getvalue())["error"]["code"]), (2, "SCRIPT.IO"))

    def test_bad_name_is_validation_input(self):
        with tempfile.TemporaryDirectory() as td:
            anchors = Path(td) / "anchors.json"
            anchors.write_text("{}")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cr.main(["--anchors", str(anchors), "--baseline-rev", "HEAD", "--out", td, "--name", "../x"])
        self.assertEqual((code, json.loads(buf.getvalue())["error"]["code"]), (2, "VALIDATION.INPUT"))


@unittest.skipUnless(HAS_YAML, "PyYAML is not installed")
class IssueUrlSettingTests(unittest.TestCase):
    def setUp(self):
        import plan_anchor_settings

        self.s = plan_anchor_settings
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name).resolve()
        (self.root / ".git").mkdir()

    def cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = self.s.main([*argv, "--repository-root", str(self.root)])
        return code, json.loads(buf.getvalue())

    def test_set_show_and_keep_other_keys(self):
        code, out = self.cli("set", "allow_remote_judge", "true")
        self.assertEqual(code, 0, out)
        code, out = self.cli("set", "issue_url_template", "https://tracker.example/issues/{id}")
        self.assertEqual((code, out["data"]["previous"]), (0, None))
        code, out = self.cli("show")
        self.assertEqual((out["data"]["issue_url_template"], out["data"]["allow_remote_judge"]),
                         ("https://tracker.example/issues/{id}", True))
        text = (self.root / ".sc" / "plan-anchor" / "settings.yaml").read_text(encoding="utf-8")
        self.assertIn('issue_url_template: "https://tracker.example/issues/{id}"', text)

    def test_default_is_unset(self):
        code, out = self.cli("show")
        self.assertEqual((code, out["data"]["issue_url_template"]), (0, None))

    def test_bad_values_are_refused(self):
        for value in ("tracker.example/{id}", "https://tracker.example/issues", "https://t.example/{id}/{id}",
                      "https://t.example/ {id}"):
            with self.subTest(value=value):
                code, out = self.cli("set", "issue_url_template", value)
                self.assertEqual((code, out["error"]["code"]), (2, "VALIDATION.INPUT"))
        path = self.root / ".sc" / "plan-anchor" / "settings.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("schema_version: 1\nissue_url_template: 5\n", encoding="utf-8")
        code, out = self.cli("show")
        self.assertEqual((code, out["error"]["code"]), (2, "SETTINGS.INVALID_ISSUE_URL"))

    def test_installer_reads_and_keeps_it(self):
        spec = importlib.util.spec_from_file_location("sc_plan_anchor_install_cr", PLUGIN / "install.py")
        inst = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = inst
        spec.loader.exec_module(inst)
        import yaml

        text = "schema_version: 1\nanchor_tracker: br\nissue_url_template: \"https://t.example/{id}\"\n"
        parsed = inst.parse_settings(text, yaml)
        self.assertEqual(parsed.value.issue_url_template, "https://t.example/{id}")
        rendered = inst.render_settings(parsed.value)
        self.assertEqual(inst.parse_settings(rendered, yaml).value, parsed.value)
        installed = self.s.parse_settings(rendered.replace("anchor_tracker: br\n", ""), yaml)
        self.assertEqual(installed.value.issue_url_template, "https://t.example/{id}")
        self.assertEqual(inst.parse_settings(text.replace("https://", "ftp://"), yaml).error.code,
                         "SETTINGS.INVALID_ISSUE_URL")


if __name__ == "__main__":
    unittest.main()
