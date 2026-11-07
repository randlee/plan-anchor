"""Triage questions are added to every planning-gate request by default and never cost a verdict.

Source order: the repository's .sc/plan-anchor/triage/plan-questions.jsonl, else the shipped default.
The Jev transport is the recording stub from test_jev_judge, so what is sent is asserted on the call log.
The file name sorts after test_anchor_tracker (see test_jev_judge_exclude for why that matters).
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_jev_judge import (  # noqa: F401 - shared helpers
    Judged, TRIAGE_IDS, Transport, answer, anchor, dev_answers, jj, plan_answers, record, run_cli, write,
)

GATE_IDS = {"relevant", "addressed", "contradicted"}
SHIPPED = jj.TRIAGE_ASSETS / "plan-questions.jsonl"


def triage_answers(choice="no", p=0.9):
    return {"model": "jev-1.13.0", "answers": {i: answer(choice, p) for i in sorted(TRIAGE_IDS)}}


class ByQuestions(Transport):
    """Answers a request by what it asks: gate answers for a gate request, triage answers for a triage-only request."""

    def __init__(self, gate_answers):
        super().__init__()
        self.gate_answers = gate_answers

    def default(self):
        return None

    def __call__(self, body, api_key, timeout):
        gate = {"model": "jev-1.13.0", "answers": json.loads(json.dumps(self.gate_answers))}  # a fresh answer per call, as on the wire
        self.script = [gate if "relevant" in body["questions"] else triage_answers()]
        return super().__call__(body, api_key, timeout)


def repo_with_triage(d, *questions):
    """A repository root whose .sc/plan-anchor holds a settings file and its own triage questions."""
    root = Path(d) / "repo"
    (root / ".sc" / "plan-anchor" / "triage").mkdir(parents=True)
    (root / ".sc" / "plan-anchor" / "settings.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    path = root / ".sc" / "plan-anchor" / "triage" / "plan-questions.jsonl"
    path.write_text("".join(json.dumps(q) + "\n" for q in questions), encoding="utf-8")
    return root, path


class TriageDefaultTests(unittest.TestCase):
    def test_shipped_defaults_are_valid_and_load(self):
        base = jj.load_question_set("plan").value
        merged, sources = jj.load_extra_questions([str(SHIPPED)], base).value
        self.assertEqual(set(sources[0]["ids"]), TRIAGE_IDS)
        self.assertEqual(merged["roles"], base["roles"])
        rules = json.loads((jj.TRIAGE_ASSETS / "rules.json").read_text(encoding="utf-8"))
        used = {c["question"] for r in rules["routes"] for c in r["when"]}
        self.assertLessEqual(used - GATE_IDS, TRIAGE_IDS)  # every rule reads a question judge asks

    def test_gate_request_never_carries_the_triage_questions(self):
        for label, base in (("passing", plan_answers()), ("failing", plan_answers(comp="no"))):
            with self.subTest(label), tempfile.TemporaryDirectory() as d:
                t = Transport({"model": "jev-1.13.0", "answers": base}, triage_answers())
                j = Judged(d, t)
                self.assertEqual(j.code, 0, j.out)
                self.assertEqual(set(t.bodies[0]["questions"]), GATE_IDS)
                self.assertEqual(j.run["extra_questions"][0]["path"], str(SHIPPED))

    def test_triage_is_asked_in_a_second_request_only_for_a_failed_cell(self):
        with tempfile.TemporaryDirectory() as d:
            t = Transport()
            j = Judged(d, t)
            self.assertEqual((len(t.bodies), j.result["verdict"]), (1, "satisfied"), j.out)
            self.assertFalse(TRIAGE_IDS & set(j.result["answers"]))
        with tempfile.TemporaryDirectory() as d:
            t = Transport({"model": "jev-1.13.0", "answers": plan_answers(comp="no")}, triage_answers())
            j = Judged(d, t)
            self.assertEqual(j.code, 0, j.out)
            self.assertEqual(len(t.bodies), 2)
            self.assertEqual(set(t.bodies[1]["questions"]), TRIAGE_IDS)
            self.assertEqual(t.bodies[1]["state"], t.bodies[0]["state"])
            self.assertEqual(j.result["verdict"], "not_addressed")
            self.assertEqual(TRIAGE_IDS, set(j.result["answers"]) & TRIAGE_IDS)

    def test_the_verdict_is_the_same_with_and_without_the_triage_questions(self):
        for base in (plan_answers(), plan_answers(comp="no"), plan_answers(conf="yes"), plan_answers(comp_p=0.5)):
            seen = []
            for extra in ([], ["--no-triage-questions"]):
                with tempfile.TemporaryDirectory() as d:
                    t = ByQuestions(base)
                    j = Judged(d, t, extra_args=extra)
                    self.assertEqual(j.code, 0, j.out)
                    seen.append((j.result["verdict"], j.result["min_confidence"], t.bodies[0]))
            self.assertEqual(seen[0], seen[1])  # the gate request, and so its verdict, is identical

    def test_a_failed_triage_request_costs_the_cell_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            bad = jj.JudgeError("JEV.HTTP", "boom", recoverable=False)
            t = Transport({"model": "jev-1.13.0", "answers": plan_answers(comp="no")}, bad)
            j = Judged(d, t)
            self.assertEqual((j.code, j.result["verdict"]), (0, "not_addressed"), j.out)
            self.assertIn("triage_error", j.result)

    def test_extra_questions_stay_in_the_gate_request(self):
        with tempfile.TemporaryDirectory() as d:
            extra = {"id": "mine", "type": "choice", "instructions": "Is it mine?", "criteria": {"yes": "y", "no": "n", "unclear": "u"}}
            path = write(d, "mine.jsonl", json.dumps(extra) + "\n")
            t = Transport()
            j = Judged(d, t, extra_args=["--extra-questions", path])
            self.assertEqual(set(t.bodies[0]["questions"]), GATE_IDS | {"mine"})

    def test_repository_triage_file_replaces_the_shipped_one(self):
        with tempfile.TemporaryDirectory() as d:
            q = {"id": "local", "type": "choice", "instructions": "Local triage question?", "criteria": {"yes": "y", "no": "n", "unclear": "u"}}
            root, path = repo_with_triage(d, q)
            t = ByQuestions(plan_answers(comp="no"))
            j = Judged(d, t, extra_args=["--repository-root", str(root)])
            self.assertEqual(j.code, 0, j.out)
            self.assertEqual(set(t.bodies[0]["questions"]), GATE_IDS)
            self.assertEqual(set(t.bodies[1]["questions"]), {"local"})
            self.assertEqual(Path(j.run["extra_questions"][0]["path"]).resolve(), path.resolve())

    def test_no_triage_questions_sends_the_gate_questions_only(self):
        with tempfile.TemporaryDirectory() as d:
            t = Transport()
            j = Judged(d, t, extra_args=["--no-triage-questions"])
            self.assertEqual(set(t.bodies[0]["questions"]), GATE_IDS)
            self.assertEqual(j.run["extra_questions"], [])

    def test_dev_gate_has_no_default_triage_questions(self):
        with tempfile.TemporaryDirectory() as d:
            t = Transport(gate="dev")
            j = Judged(d, t, gate="dev")
            self.assertEqual(j.code, 0, j.out)
            self.assertEqual(set(t.bodies[0]["questions"]), {"relevant", "implemented", "violated", "evidenced"})

    def test_unanswered_triage_questions_never_cost_a_verdict(self):
        for base, expected in ((plan_answers(), "satisfied"), (plan_answers(comp="no"), "not_addressed")):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as d:
                j = Judged(d, Transport({"model": "jev-1.13.0", "answers": base}))
                self.assertEqual(j.result["verdict"], expected, j.out)

    def test_gate_digest_is_unchanged_by_triage_questions(self):
        digests = {}
        for label, extra in (("with", []), ("without", ["--no-triage-questions"])):
            with tempfile.TemporaryDirectory() as d:
                digests[label] = Judged(d, Transport(), extra_args=extra).result
        self.assertEqual(digests["with"]["questions_sha256"], digests["without"]["questions_sha256"])
        self.assertIn("extra_questions_sha256", digests["with"])
        self.assertNotIn("extra_questions_sha256", digests["without"])

    def test_a_triage_request_over_the_size_cap_is_dropped_not_the_cell(self):
        """The gate request fits, the triage request does not: the verdict stands and the cell records what was left out."""
        with tempfile.TemporaryDirectory() as d:
            anchors_path = write(d, "anchors.json", record(anchor()))
            item = write(d, "item.txt", "Sprint 2 copies the legacy runtime crates.")
            dry = ["judge", "--anchors", anchors_path, "--gate", "plan", "--all", "--item-id", "ex-42", "--item-file", item, "--dry-run"]
            _, gate_only = run_cli(dry + ["--out", str(Path(d) / "g.json")])
            fits = gate_only["data"]["totals"]["bytes"]
            t = ByQuestions(plan_answers(comp="no"))
            j = Judged(d, t, extra_args=["--max-request-bytes", str(fits + 50)])
            self.assertEqual(j.code, 0, j.out)
            self.assertEqual(j.result["verdict"], "not_addressed")
            self.assertEqual(len(t.bodies), 2 if sum(len(json.dumps(b)) for b in t.bodies[1:]) else 1)


class TriageReportTests(unittest.TestCase):
    """`report --format md` shows a failed cell's triage answers, the answers triage/rules.json routes on."""

    def report(self, j, *extra):
        code, md = run_cli(["report", "--run", j.run["path"], "--format", "md", *extra])
        self.assertEqual(code, 0, md)
        return md

    def test_a_failed_cell_lists_its_triage_answers_in_question_order(self):
        with tempfile.TemporaryDirectory() as d:
            j = Judged(d, ByQuestions(plan_answers(comp="no")))
            self.assertEqual(j.result["verdict"], "not_addressed", j.out)
            order = [q["id"] for q in shipped_questions()]
            self.assertEqual(j.result["triage_questions"], order)
            md = self.report(j)
            line = next(x for x in md.splitlines() if x.startswith(">   Triage:"))
            self.assertEqual(line, ">   Triage: " + ", ".join(f"`{q}` no (0.90)" for q in order) + ".")

    def test_gate_answers_are_not_listed_as_triage(self):
        with tempfile.TemporaryDirectory() as d:
            md = self.report(Judged(d, ByQuestions(plan_answers(comp="no"))))
            line = next(x for x in md.splitlines() if x.startswith(">   Triage:"))
            for gate_id in GATE_IDS:
                self.assertNotIn(f"`{gate_id}`", line)

    def test_a_passing_cell_has_no_triage_line_even_with_all(self):
        with tempfile.TemporaryDirectory() as d:
            j = Judged(d, ByQuestions(plan_answers()))
            self.assertEqual(j.result["verdict"], "satisfied", j.out)
            self.assertNotIn("Triage", self.report(j, "--all"))

    def test_no_triage_questions_means_no_triage_line(self):
        with tempfile.TemporaryDirectory() as d:
            j = Judged(d, ByQuestions(plan_answers(comp="no")), extra_args=["--no-triage-questions"])
            self.assertNotIn("triage_questions", j.result)
            self.assertNotIn("Triage", self.report(j))

    def test_a_failed_triage_request_is_reported_with_its_error(self):
        with tempfile.TemporaryDirectory() as d:
            bad = jj.JudgeError("JEV.HTTP", "boom", recoverable=False)
            j = Judged(d, Transport({"model": "jev-1.13.0", "answers": plan_answers(comp="no")}, bad))
            md = self.report(j)
            self.assertIn(">   Triage error JEV.HTTP:", md)
            self.assertNotIn(">   Triage:", md)

    def test_fixture_triage_answers_are_reported(self):
        with tempfile.TemporaryDirectory() as d:
            fx = {"*": {**plan_answers(comp="no"), **{i: answer("yes", 0.8) for i in TRIAGE_IDS}}}
            path = write(d, "fx.json", json.dumps(fx))
            j = Judged(d, Transport(), extra_args=["--answers-file", path])
            self.assertEqual(j.result["verdict"], "not_addressed", j.out)
            self.assertIn("`owns` yes (0.80)", self.report(j))

    def test_a_run_file_without_triage_questions_still_reports(self):
        """Run files written by 0.9.0 carry triage answers but not which ones they are: no triage line, no error."""
        with tempfile.TemporaryDirectory() as d:
            j = Judged(d, ByQuestions(plan_answers(comp="no")))
            run = json.loads(Path(j.run["path"]).read_text(encoding="utf-8"))
            for r in run["results"]:
                r.pop("triage_questions", None)
            Path(j.run["path"]).write_text(json.dumps(run), encoding="utf-8")
            md = self.report(j)
            self.assertIn("not addressed", md)
            self.assertNotIn("Triage", md)


def shipped_questions():
    return [json.loads(line) for line in SHIPPED.read_text(encoding="utf-8").splitlines() if line.strip()]


def squeeze(text):
    """Help text is wrapped by argparse; compare with all whitespace removed."""
    return "".join(text.split())


class TriageDocumentedBehaviourTests(unittest.TestCase):
    """What `judge --help` and triage/README say you can do is what judge does."""

    def test_help_states_intent_default_and_how_to_change(self):
        out = subprocess.run([sys.executable, jj.__file__, "judge", "--help"], capture_output=True, text=True, check=True).stdout
        flat = squeeze(out)
        for needle in sorted(TRIAGE_IDS) + [
            "onbydefault", "neverchangeaverdict", ".sc/plan-anchor/triage/<gate>-questions.jsonl", "neveroverwritten",
            "editthatline", "addaline", "deleteitsline", "rules.json", "--extra-questions", "triage/README.md",
        ]:
            self.assertIn(needle, flat, needle)

    def test_readme_documents_each_way_to_change_the_set(self):
        text = squeeze((jj.TRIAGE_ASSETS / "README.md").read_text(encoding="utf-8"))
        for needle in ("Changeadefault", "Addaquestion", "Removeaquestion", "--extra-questions", "--no-triage-questions", "rules.json", "nevergates"):
            self.assertIn(needle, text, needle)

    def test_editing_a_default_line_changes_what_is_sent_and_keeps_the_rest(self):
        with tempfile.TemporaryDirectory() as d:
            qs = shipped_questions()
            qs[0]["instructions"] = "EDITED: " + qs[0]["instructions"]
            root, _ = repo_with_triage(d, *qs)
            t = ByQuestions(plan_answers(comp="no"))
            j = Judged(d, t, extra_args=["--repository-root", str(root)])
            self.assertEqual(j.code, 0, j.out)
            sent = t.bodies[1]["questions"]
            self.assertEqual(set(sent), TRIAGE_IDS)
            self.assertTrue(sent[qs[0]["id"]]["instructions"].startswith("EDITED: "))

    def test_adding_and_removing_a_line_adds_and_removes_that_question(self):
        extra = {"id": "mine", "type": "choice", "instructions": "Is it mine?", "criteria": {"yes": "y", "no": "n", "unclear": "u"}}
        for label, qs, expected in (
            ("add", shipped_questions() + [extra], TRIAGE_IDS | {"mine"}),
            ("remove", shipped_questions()[1:], TRIAGE_IDS - {shipped_questions()[0]["id"]}),
        ):
            with self.subTest(label), tempfile.TemporaryDirectory() as d:
                root, _ = repo_with_triage(d, *qs)
                t = ByQuestions(plan_answers(comp="no"))
                j = Judged(d, t, extra_args=["--repository-root", str(root)])
                self.assertEqual(j.code, 0, j.out)
                self.assertEqual(set(t.bodies[1]["questions"]), expected)

    def test_extra_questions_still_run_when_the_defaults_are_off(self):
        with tempfile.TemporaryDirectory() as d:
            extra = {"id": "mine", "type": "choice", "instructions": "Is it mine?", "criteria": {"yes": "y", "no": "n", "unclear": "u"}}
            path = write(d, "mine.jsonl", json.dumps(extra) + "\n")
            t = Transport()
            j = Judged(d, t, extra_args=["--no-triage-questions", "--extra-questions", path])
            self.assertEqual(j.code, 0, j.out)
            self.assertEqual(set(t.bodies[0]["questions"]), GATE_IDS | {"mine"})
