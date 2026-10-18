"""Anchor exclusions: `exclude: [{item, reason}]` on an anchor skips that (anchor, item) cell.

The Jev transport is the same recording stub test_jev_judge uses, so "no Jev call" is asserted on the call log,
not inferred from the verdict. The file name sorts after test_anchor_tracker, which reloads result.py under
the same module name; importing jev_judge earlier would leave it holding a stale Ok/Err.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_jev_judge import (  # noqa: F401 - shared helpers
    Judged, Transport, anchor, env, jj, live, plan_answers, record, run_cli, write,
)

REASON = "Data-only sprint; the skill CLI options belong to bi-3."
CLI_STATEMENT = "Every skill CLI option is documented in the skill's SKILL.md options table."
CLI_QUOTE = "document the skill CLI options"
FAILING = {"model": "jev-1.13.0", "answers": plan_answers(comp="no")}  # relevant yes, addressed no -> not_addressed


def cli_anchor(aid="ANC-011", **extra):
    return anchor(aid, statement=CLI_STATEMENT, quote=CLI_QUOTE, scope="any sprint that adds or changes a skill CLI option", **extra)


def excluded(item="ex-42", reason=REASON):
    return [{"item": item, "reason": reason}]


def sent_anchor_ids(transport):
    return [b["state"]["anchor"]["id"] for b in transport.bodies]


class JudgeExclusionTests(unittest.TestCase):
    def test_excluded_cell_makes_no_transport_call_and_passes(self):
        with tempfile.TemporaryDirectory() as d:
            # The excluded anchor would fail if asked: every call answers not_addressed.
            t = Transport(*([FAILING] * 5))
            j = Judged(d, t, anchors=[cli_anchor(exclude=excluded())])
            self.assertEqual(t.bodies, [])
            self.assertEqual(j.code, 0, j.out)
            r = j.result
            self.assertEqual((r["anchor_id"], r["verdict"], r["answers"], r["attempts"]), ("ANC-011", "excluded", None, 0))
            self.assertEqual(r["exclusion"], {"item": "ex-42", "reason": REASON})
            self.assertIn(REASON, r["explanation"])
            s = j.run["summary"]
            self.assertEqual((s["counts"], s["failing"], s["excluded"], s["pass"]),
                             ({"excluded": 1}, [], [{"anchor_id": "ANC-011", "reason": REASON}], True))
            # the run file on disk carries the same reason
            saved = json.loads(Path(j.run["run_path"]).read_text())
            self.assertEqual(saved["results"][0]["exclusion"]["reason"], REASON)

    def test_only_the_excluded_cell_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            t = Transport()
            j = Judged(d, t, anchors=[anchor("ANC-001"), cli_anchor(exclude=excluded())])
            self.assertEqual(sent_anchor_ids(t), ["ANC-001"])
            self.assertEqual({r["anchor_id"]: r["verdict"] for r in j.run["results"]}, {"ANC-001": "satisfied", "ANC-011": "excluded"})

    def test_non_excluded_cells_are_unaffected(self):
        """The same record with and without ANC-011's exclusion: ANC-001's request and result are identical."""
        rows, bodies = {}, {}
        for label, extra in (("plain", {}), ("excluded", {"exclude": excluded()})):
            with tempfile.TemporaryDirectory() as d:
                t = Transport(FAILING, {"model": "jev-1.13.0", "answers": plan_answers()})
                j = Judged(d, t, anchors=[anchor("ANC-001"), cli_anchor(**extra)])
                rows[label] = next(r for r in j.run["results"] if r["anchor_id"] == "ANC-001")
                bodies[label] = [b for b in t.bodies if b["state"]["anchor"]["id"] == "ANC-001"]
        self.assertEqual(rows["plain"], rows["excluded"])
        self.assertEqual(bodies["plain"], bodies["excluded"])
        self.assertEqual(rows["plain"]["verdict"], "not_addressed")

    def test_planted_negative_other_item_or_near_miss_is_judged(self):
        """An exclusion for another item, or one differing only in case or whitespace, never applies."""
        for item in ("ex-41", "BD-42", " ex-42", "ex-42 "):
            with self.subTest(item=item), tempfile.TemporaryDirectory() as d:
                t = Transport(FAILING)
                j = Judged(d, t, anchors=[cli_anchor(exclude=excluded(item=item))])
                self.assertEqual(sent_anchor_ids(t), ["ANC-011"])
                self.assertEqual((j.code, j.run["summary"]["pass"], j.result["verdict"], j.run["summary"]["excluded"]), (0, False, "not_addressed", []))

    def test_excluding_one_anchor_does_not_pass_a_failing_one(self):
        with tempfile.TemporaryDirectory() as d:
            t = Transport(FAILING)
            j = Judged(d, t, anchors=[anchor("ANC-001"), cli_anchor(exclude=excluded())])
            self.assertEqual((j.code, j.run["summary"]["failing"], j.run["summary"]["pass"]), (0, ["ANC-001"], False))

    def test_all_excluded_needs_no_key_or_opt_in(self):
        with tempfile.TemporaryDirectory() as d:
            t = Transport()
            j = Judged(d, t, anchors=[cli_anchor(exclude=excluded())], env_values={})
            self.assertEqual((j.code, j.result["verdict"], t.bodies), (0, "excluded", []))
            # with one anchor left to judge, the key and opt-in are required as before
            t = Transport()
            j = Judged(d, t, anchors=[anchor("ANC-001"), cli_anchor(exclude=excluded())], env_values={})
            self.assertEqual((j.code, j.out["error"]["code"], t.bodies), (2, "AUTH.CREDENTIALS", []))

    def test_dry_run_writes_no_request_for_an_excluded_cell(self):
        with tempfile.TemporaryDirectory() as d:
            t = Transport()
            j = Judged(d, t, anchors=[anchor("ANC-001"), cli_anchor(exclude=excluded())], extra_args=["--dry-run"])
            self.assertEqual([b["state"]["anchor"]["id"] for b in j.run["requests"]], ["ANC-001"])
            self.assertEqual(t.bodies, [])
            self.assertEqual({r["anchor_id"]: r["verdict"] for r in j.run["results"]}, {"ANC-001": None, "ANC-011": "excluded"})

    def test_explicit_anchor_and_dev_gate_respect_the_exclusion(self):
        with tempfile.TemporaryDirectory() as d:
            t = Transport(gate="dev")
            j = Judged(d, t, anchors=[cli_anchor(exclude=excluded())], gate="dev")
            self.assertEqual((j.code, j.result["verdict"], t.bodies), (0, "excluded", []))
            self.assertIn("this work", j.result["explanation"])
            anchors_path = write(d, "a2.json", record(cli_anchor(exclude=excluded())))
            item = write(d, "i.txt", "Sprint bi-2 migrates the data tables.")
            t = Transport(FAILING)
            with live(), \
                    mock.patch.object(jj, "call_jev", t):
                code, out = run_cli(["judge", "--anchors", anchors_path, "--gate", "plan", "--anchor", "ANC-011", "--item-id", "ex-42",
                                     "--item-file", item, "--run-dir", str(Path(d) / "runs")])
            self.assertEqual((code, out["data"]["results"][0]["verdict"], t.bodies), (0, "excluded", []))


class OutputTests(unittest.TestCase):
    def two_runs(self, d):
        """ex-42 judged before and after ANC-011 is excluded from it."""
        runs = Path(d) / "runs"
        before = Judged(d, Transport({"model": "m", "answers": plan_answers(rel_p=0.55)}), anchors=[cli_anchor()],
                        extra_args=["--no-confirm", "--out", str(runs / "before.json")])
        after = Judged(d, Transport(), anchors=[cli_anchor(exclude=excluded())], extra_args=["--out", str(runs / "after.json")])
        self.assertEqual(before.result["verdict"], "underspecified")
        self.assertEqual(after.result["verdict"], "excluded")
        return runs, before, after

    def test_report_always_shows_the_exclusion_reason(self):
        with tempfile.TemporaryDirectory() as d:
            runs, _, after = self.two_runs(d)
            code, md = run_cli(["report", "--run", after.run["run_path"], "--format", "md"])
            self.assertEqual(code, 0)
            self.assertIn("> **ex-42 · ANC-011 · excluded** Anchor: " + CLI_STATEMENT, md)
            self.assertIn("Not judged: " + REASON, md)
            self.assertIn("Counts: excluded 1.", md)
            self.assertIn("All judged anchors are satisfied or not applicable.", md)
            code, out = run_cli(["report", "--run", after.run["run_path"]])
            self.assertEqual((out["data"]["pass"], out["data"]["failing"]), (True, []))
            self.assertIn(REASON, out["data"]["markdown"])

    def test_coverage_lists_excluded_cells_with_reasons(self):
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d) / "runs"
            Judged(d, Transport(), anchors=[cli_anchor(exclude=excluded())], extra_args=["--out", str(runs / "a.json")])
            item = write(d, "item43.txt", "Sprint bi-3 adds the --format option.")
            path = write(d, "anchors.json", record(cli_anchor(exclude=excluded())))
            t = Transport()
            with live(), \
                    mock.patch.object(jj, "call_jev", t):
                code, _ = run_cli(["judge", "--anchors", path, "--gate", "plan", "--all", "--item-id", "ex-43",
                                   "--item-file", item, "--out", str(runs / "b.json")])
            self.assertEqual((code, sent_anchor_ids(t)), (0, ["ANC-011"]))
            code, out = run_cli(["coverage", "--runs", str(runs), "--gate", "plan"])
            data = out["data"]
            self.assertEqual(data["matrix"], {"ANC-011": {"ex-42": "excluded", "ex-43": "satisfied"}})
            self.assertEqual(data["excluded"], {"ANC-011": {"ex-42": REASON}})
            self.assertEqual(data["uncovered_anchors"], [])
            code, md = run_cli(["coverage", "--runs", str(runs), "--gate", "plan", "--format", "md"])
            self.assertIn("| ANC-011 | excluded | satisfied | yes |", md)
            self.assertIn(f"- ANC-011 x ex-42: {REASON}", md)

    def test_excluded_everywhere_is_still_uncovered(self):
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d) / "runs"
            Judged(d, Transport(), anchors=[cli_anchor(exclude=excluded())], extra_args=["--out", str(runs / "a.json")])
            code, out = run_cli(["coverage", "--runs", str(runs), "--gate", "plan"])
            self.assertEqual(out["data"]["uncovered_anchors"], ["ANC-011"])

    def test_diff_carries_the_exclusion(self):
        with tempfile.TemporaryDirectory() as d:
            runs, before, after = self.two_runs(d)
            code, out = run_cli(["diff", "--prev", before.run["run_path"], "--next", after.run["run_path"]])
            data = out["data"]
            self.assertEqual(data["changed"], [{"anchor_id": "ANC-011", "from": "underspecified", "to": "excluded", "improved": True}])
            self.assertEqual((data["fail_to_pass"], data["pass_to_fail"], data["pass_before"], data["pass_after"]), (["ANC-011"], [], False, True))
            self.assertEqual(data["excluded"], [{"anchor_id": "ANC-011", "reason": REASON}])
            code, out = run_cli(["diff", "--prev", after.run["run_path"], "--next", before.run["run_path"]])
            self.assertEqual((out["data"]["pass_to_fail"], out["data"]["excluded"]), (["ANC-011"], []))

    def test_render_lists_exclusions_under_the_anchor(self):
        with tempfile.TemporaryDirectory() as d:
            path = write(d, "anchors.json", record(anchor("ANC-001"), cli_anchor(exclude=excluded("atm-bi-2"))))
            out_md = str(Path(d) / "anchors.md")
            code, _ = run_cli(["render", "--anchors", path, "--out", out_md])
            md = Path(out_md).read_text()
            self.assertEqual(code, 0)
            section = md[md.index("## ANC-011"):]
            self.assertIn(f"- `atm-bi-2`: {REASON}", section)
            self.assertNotIn("Excluded from", md[md.index("## ANC-001"):md.index("## ANC-011")])


class SchemaTests(unittest.TestCase):
    def problems(self, exclude):
        return jj.validate_record(record(cli_anchor(exclude=exclude)))

    def test_valid_exclusions_pass(self):
        self.assertEqual(self.problems(excluded()), [])
        self.assertEqual(self.problems([]), [])
        self.assertEqual(jj.validate_record(record(cli_anchor())), [])

    def test_empty_reason_is_rejected(self):
        for reason in ("", "   ", None, 7):
            with self.subTest(reason=reason):
                problems = self.problems([{"item": "ex-42", "reason": reason}])
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("exclude[0].reason is empty", problems[0])
        self.assertTrue(any("reason is empty" in p for p in self.problems([{"item": "ex-42"}])))

    def test_malformed_exclusions_are_rejected(self):
        cases = {
            "not a list": ({"item": "ex-42", "reason": REASON}, "exclude must be a list"),
            "not an object": (["ex-42"], "must be an object"),
            "empty item": ([{"item": " ", "reason": REASON}], "item must be a non-empty"),
            "unknown key": ([{"item": "ex-42", "reason": REASON, "approved_by": "x"}], "unknown keys"),
            "duplicate item": (excluded() + excluded(reason="again"), "duplicate exclusion"),
        }
        for label, (exclude, expected) in cases.items():
            with self.subTest(label):
                problems = self.problems(exclude)
                self.assertTrue(any(expected in p for p in problems), problems)

    def test_judge_refuses_a_record_with_an_empty_reason(self):
        with tempfile.TemporaryDirectory() as d:
            t = Transport()
            j = Judged(d, t, anchors=[cli_anchor(exclude=[{"item": "ex-42", "reason": " "}])])
            self.assertEqual((j.code, j.out["error"]["code"], t.bodies), (2, "VALIDATION.ANCHORS", []))
            code, out = run_cli(["validate", "--anchors", j.anchors_path])
            self.assertEqual((code, out["success"], out["data"]["valid"]), (0, True, False))
            self.assertTrue(any("reason is empty" in p for p in out["data"]["problems"]))


class ExcludeCommandTests(unittest.TestCase):
    def test_exclude_on_a_locked_anchor_keeps_version_and_records_history(self):
        with tempfile.TemporaryDirectory() as d:
            path = write(d, "anchors.json", record(cli_anchor(status="locked", version=3)))
            code, out = run_cli(["exclude", "--anchors", path, "--id", "ANC-011", "--item", "atm-bi-2", "--reason", f"  {REASON} "])
            self.assertEqual(code, 0, out)
            a = json.loads(Path(path).read_text())["anchors"][0]
            self.assertEqual((a["version"], a["status"], a["exclude"]), (3, "locked", [{"item": "atm-bi-2", "reason": REASON}]))
            self.assertEqual((a["history"][-1]["event"], a["history"][-1]["item"]), ("excluded", "atm-bi-2"))
            self.assertEqual(jj.validate_record(json.loads(Path(path).read_text())), [])
            # same item again replaces the reason, never duplicates it
            code, out = run_cli(["exclude", "--anchors", path, "--id", "ANC-011", "--item", "atm-bi-2", "--reason", "Second reason."])
            a = json.loads(Path(path).read_text())["anchors"][0]
            self.assertEqual((a["version"], a["exclude"]), (3, [{"item": "atm-bi-2", "reason": "Second reason."}]))
            code, out = run_cli(["exclude", "--anchors", path, "--id", "ANC-011", "--item", "atm-bi-2", "--remove"])
            a = json.loads(Path(path).read_text())["anchors"][0]
            self.assertEqual((code, a["version"], "exclude" in a, a["history"][-1]["event"]), (0, 3, False, "exclusion_removed"))

    def test_exclude_refuses_bad_input(self):
        with tempfile.TemporaryDirectory() as d:
            path = write(d, "anchors.json", record(cli_anchor()))
            before = Path(path).read_text()
            for argv, code_expected in (
                (["--id", "ANC-011", "--item", "ex-42", "--reason", "   "], "VALIDATION.INPUT"),
                (["--id", "ANC-011", "--item", "ex-42"], "VALIDATION.INPUT"),
                (["--id", "ANC-011", "--item", " ", "--reason", REASON], "VALIDATION.INPUT"),
                (["--id", "ANC-099", "--item", "ex-42", "--reason", REASON], "ANCHOR.UNKNOWN"),
                (["--id", "ANC-011", "--item", "ex-42", "--remove"], "VALIDATION.INPUT"),
            ):
                with self.subTest(argv=argv):
                    code, out = run_cli(["exclude", "--anchors", path, *argv])
                    self.assertEqual((code, out["success"], out["error"]["code"]), (2, False, code_expected))
            self.assertEqual(Path(path).read_text(), before)


class LintTests(unittest.TestCase):
    def lint(self, d, *extra, exclude=None):
        path = write(d, "anchors.json", record(cli_anchor(exclude=exclude if exclude is not None else excluded("atm-bi-9"))))
        return run_cli(["lint", "--anchors", path, *extra])

    def test_unknown_item_warns_without_failing_lint(self):
        with tempfile.TemporaryDirectory() as d:
            shown = write(d, "shown.json", [{"id": "atm-bi-2", "title": "bi-2"}, {"id": "atm-bi-3", "title": "bi-3"}])
            code, out = self.lint(d, "--plan-items", shown)
            data = out["data"]
            self.assertEqual((code, data["warning_count"], data["exclusions_checked"], data["exclusions"]), (0, 0, True, 1))
            self.assertEqual([(w["id"], w["item"]) for w in data["exclusion_warnings"]], [("ANC-011", "atm-bi-9")])
            self.assertIn("not in the plan", data["exclusion_warnings"][0]["warning"])

    def test_known_item_and_other_item_sources(self):
        with tempfile.TemporaryDirectory() as d:
            ids = write(d, "ids.json", ["atm-bi-2"])
            beads = write(d, "beads.json", [{"id": "atm-bi-2", "title": "bi-2"}])
            for extra in (["--plan-items", ids], ["--plan-items", beads], ["--plan-item", "atm-bi-2"]):
                with self.subTest(extra=extra):
                    code, out = self.lint(d, *extra, exclude=excluded("atm-bi-2"))
                    self.assertEqual((code, out["data"]["exclusion_warnings"]), (0, []))
            code, out = self.lint(d, "--plan-item", "atm-bi-3", exclude=excluded("atm-bi-2"))
            self.assertEqual([w["item"] for w in out["data"]["exclusion_warnings"]], ["atm-bi-2"])

    def test_without_plan_items_nothing_is_checked(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = self.lint(d)
            self.assertEqual((code, out["data"]["exclusions_checked"], out["data"]["exclusion_warnings"]), (0, False, []))

    def test_malformed_plan_items_file_is_a_typed_error(self):
        with tempfile.TemporaryDirectory() as d:
            bad = write(d, "bad.json", {"sprints": [{"title": "no id"}]})
            code, out = self.lint(d, "--plan-items", bad)
            self.assertEqual((code, out["success"], out["error"]["code"]), (2, False, "INPUT.MALFORMED"))
            # ADR-014: plan_source discover output is no longer an accepted form.
            discover = write(d, "discover.json", {"success": True, "data": {"sprints": [{"id": "atm-bi-2"}]}, "error": None})
            code, out = self.lint(d, "--plan-items", discover)
            self.assertEqual((code, out["success"], out["error"]["code"]), (2, False, "INPUT.MALFORMED"))
            code, out = self.lint(d, "--plan-items", str(Path(d) / "missing.json"))
            self.assertEqual((code, out["success"]), (2, False))


class ExampleTests(unittest.TestCase):
    def test_shipped_example_exclusion_is_valid_and_applies(self):
        example = json.loads((jj.HERE.parent / "assets" / "examples" / "anchors.example.json").read_text())
        self.assertEqual(jj.validate_record(copy.deepcopy(example)), [])
        req = jj.find_anchor(example, "REQ-014").value
        self.assertEqual(jj.exclusion_for(req, "ex-41")["item"], "ex-41")
        self.assertIsNone(jj.exclusion_for(req, "smoke"))


if __name__ == "__main__":
    unittest.main()
