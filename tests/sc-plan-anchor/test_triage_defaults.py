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

    def test_plan_gate_adds_the_shipped_triage_questions(self):
        with tempfile.TemporaryDirectory() as d:
            t = Transport()
            j = Judged(d, t)
            self.assertEqual(j.code, 0, j.out)
            self.assertEqual(set(t.bodies[0]["questions"]), GATE_IDS | TRIAGE_IDS)
            self.assertEqual(j.run["extra_questions"][0]["path"], str(SHIPPED))

    def test_repository_triage_file_replaces_the_shipped_one(self):
        with tempfile.TemporaryDirectory() as d:
            q = {"id": "local", "type": "choice", "instructions": "Local triage question?", "criteria": {"yes": "y", "no": "n", "unclear": "u"}}
            root, path = repo_with_triage(d, q)
            t = Transport()
            j = Judged(d, t, extra_args=["--repository-root", str(root)])
            self.assertEqual(j.code, 0, j.out)
            self.assertEqual(set(t.bodies[0]["questions"]), GATE_IDS | {"local"})
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

    def test_over_the_size_cap_extras_are_dropped_not_the_item(self):
        """A bead that fits with the gate questions is judged, without the extras, instead of refused as too large."""
        with tempfile.TemporaryDirectory() as d:
            anchors_path = write(d, "anchors.json", record(anchor()))
            item = write(d, "item.txt", "Sprint 2 copies the legacy runtime crates.")
            dry = ["judge", "--anchors", anchors_path, "--gate", "plan", "--all", "--item-id", "ex-42", "--item-file", item, "--dry-run"]
            _, gate_only = run_cli(dry + ["--no-triage-questions", "--out", str(Path(d) / "g.json")])
            _, with_extra = run_cli(dry + ["--out", str(Path(d) / "e.json")])
            small = gate_only["data"]["totals"]["bytes"]
            self.assertGreater(with_extra["data"]["totals"]["bytes"], small + 200)
            t = Transport()
            j = Judged(d, t, extra_args=["--max-request-bytes", str(small + 100)])
            self.assertEqual(j.code, 0, j.out)
            self.assertEqual(set(t.bodies[0]["questions"]), GATE_IDS)
            self.assertEqual(set(j.result["extra_questions_dropped"]), TRIAGE_IDS)
            self.assertEqual(j.result["verdict"], "satisfied")
            # planted negative: below the gate questions' own size, the bead is still refused
            t2 = Transport()
            j2 = Judged(d, t2, extra_args=["--max-request-bytes", str(small - 50)])
            self.assertNotEqual(j2.code, 0)
            self.assertEqual(t2.bodies, [])


if __name__ == "__main__":
    unittest.main()


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
            t = Transport()
            j = Judged(d, t, extra_args=["--repository-root", str(root)])
            self.assertEqual(j.code, 0, j.out)
            sent = t.bodies[0]["questions"]
            self.assertEqual(set(sent), GATE_IDS | TRIAGE_IDS)
            self.assertTrue(sent[qs[0]["id"]]["instructions"].startswith("EDITED: "))

    def test_adding_and_removing_a_line_adds_and_removes_that_question(self):
        extra = {"id": "mine", "type": "choice", "instructions": "Is it mine?", "criteria": {"yes": "y", "no": "n", "unclear": "u"}}
        for label, qs, expected in (
            ("add", shipped_questions() + [extra], GATE_IDS | TRIAGE_IDS | {"mine"}),
            ("remove", shipped_questions()[1:], GATE_IDS | (TRIAGE_IDS - {shipped_questions()[0]["id"]})),
        ):
            with self.subTest(label), tempfile.TemporaryDirectory() as d:
                root, _ = repo_with_triage(d, *qs)
                t = Transport()
                j = Judged(d, t, extra_args=["--repository-root", str(root)])
                self.assertEqual(j.code, 0, j.out)
                self.assertEqual(set(t.bodies[0]["questions"]), expected)

    def test_extra_questions_still_run_when_the_defaults_are_off(self):
        with tempfile.TemporaryDirectory() as d:
            extra = {"id": "mine", "type": "choice", "instructions": "Is it mine?", "criteria": {"yes": "y", "no": "n", "unclear": "u"}}
            path = write(d, "mine.jsonl", json.dumps(extra) + "\n")
            t = Transport()
            j = Judged(d, t, extra_args=["--no-triage-questions", "--extra-questions", path])
            self.assertEqual(j.code, 0, j.out)
            self.assertEqual(set(t.bodies[0]["questions"]), GATE_IDS | {"mine"})
