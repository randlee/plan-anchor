"""Consumer questions: `--extra-questions FILE.jsonl` adds questions that are asked and recorded but never gate.

The Jev transport is the recording stub from test_jev_judge, so what is sent is asserted on the call log.
The file name sorts after test_anchor_tracker, which reloads result.py under the same module name;
importing jev_judge earlier would leave it holding a stale Ok/Err.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from test_jev_judge import (  # noqa: F401 - shared helpers
    Judged, Transport, anchor, answer, failure, jj, ok, plan_answers, record, run_cli, write,
)

CRITERIA = {"yes": "The item delivers it itself.", "no": "Another item delivers it.", "unclear": "Cannot tell."}


def question(qid, text="Is this item responsible for delivering the requirement?"):
    return {"id": qid, "type": "choice", "instructions": text, "criteria": CRITERIA}


def jsonl(d, name, *lines):
    return write(d, name, "\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines) + "\n")


def with_extra(answers, **extra):
    return {"model": "jev-1.13.0", "answers": dict(answers, **{k: answer(c, p) for k, (c, p) in extra.items()})}


def judged_with(d, transport, *paths, anchors=None):
    args = []
    for p in paths:
        args += ["--extra-questions", p]
    return Judged(d, transport, anchors=anchors, extra_args=args)


class ExtraQuestionTests(unittest.TestCase):
    def test_extra_questions_are_sent_and_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            path = jsonl(d, "extra.jsonl", question("owns"), "", question("specific", "Could a developer deliver it from the item alone?"))
            t = Transport(with_extra(plan_answers(), owns=("yes", 0.9), specific=("no", 0.8)))
            j = judged_with(d, t, path)
            self.assertEqual(j.code, 0, j.out)
            sent = t.bodies[0]["questions"]
            self.assertEqual(sorted(sent), ["addressed", "contradicted", "owns", "relevant", "specific"])
            self.assertNotIn("id", sent["owns"])
            self.assertEqual(sent["specific"]["instructions"], "Could a developer deliver it from the item alone?")
            self.assertEqual(j.result["answers"]["specific"]["choice"], "no")
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            self.assertEqual(j.run["extra_questions"], [{"path": path, "sha256": digest, "ids": ["owns", "specific"]}])
            saved = json.loads(Path(j.run["run_path"]).read_text())
            self.assertEqual(saved["extra_questions"][0]["ids"], ["owns", "specific"])

    def test_without_the_flag_the_run_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            t = Transport()
            j = Judged(d, t)
            self.assertEqual(j.run["extra_questions"], [])
            self.assertEqual(sorted(t.bodies[0]["questions"]), ["addressed", "contradicted", "relevant"])

    def test_extra_answers_never_change_the_verdict(self):
        """Confident extra answers either way leave the verdict decided by the three gate roles alone."""
        cases = (("satisfied", plan_answers()), ("not_addressed", plan_answers(comp="no")), ("contradicted", plan_answers(conf="yes")))
        for expected, base in cases:
            for choice in ("yes", "no", "unclear"):
                with self.subTest(expected=expected, extra=choice), tempfile.TemporaryDirectory() as d:
                    path = jsonl(d, "extra.jsonl", question("owns"))
                    j = judged_with(d, Transport(with_extra(base, owns=(choice, 0.99))), path)
                    self.assertEqual(j.result["verdict"], expected, j.out)
                    plain = Judged(d, Transport({"model": "jev-1.13.0", "answers": base}))
                    self.assertEqual(plain.result["verdict"], expected)

    def test_files_are_repeatable_in_order(self):
        with tempfile.TemporaryDirectory() as d:
            a = jsonl(d, "a.jsonl", question("owns"))
            b = jsonl(d, "b.jsonl", question("partial"), question("paraphrase"))
            t = Transport(with_extra(plan_answers(), owns=("yes", 0.9), partial=("no", 0.9), paraphrase=("yes", 0.9)))
            j = judged_with(d, t, a, b)
            self.assertEqual(j.code, 0, j.out)
            self.assertEqual([s["ids"] for s in j.run["extra_questions"]], [["owns"], ["partial", "paraphrase"]])

    def test_dry_run_shows_extra_questions_in_the_request(self):
        with tempfile.TemporaryDirectory() as d:
            path = jsonl(d, "extra.jsonl", question("owns"))
            anchors_path = write(d, "anchors.json", record(anchor()))
            item = write(d, "item.txt", "Sprint 2 copies the legacy crates.")
            code, out = run_cli(["judge", "--anchors", anchors_path, "--gate", "plan", "--all", "--item-id", "ex-42", "--item-file", item,
                                 "--extra-questions", path, "--dry-run", "--out", str(Path(d) / "r.json")])
            self.assertEqual(code, 0, out)
            self.assertIn("owns", out["data"]["requests"][0]["questions"])

    def test_answers_fixture_must_answer_extra_questions(self):
        with tempfile.TemporaryDirectory() as d:
            path = jsonl(d, "extra.jsonl", question("owns"))
            anchors_path = write(d, "anchors.json", record(anchor()))
            item = write(d, "item.txt", "Sprint 2 copies the legacy crates.")
            common = ["judge", "--anchors", anchors_path, "--gate", "plan", "--all", "--item-id", "ex-42", "--item-file", item,
                      "--extra-questions", path, "--out", str(Path(d) / "r.json")]
            code, out = run_cli(common + ["--answers-file", write(d, "a1.json", {"*": plan_answers()})])
            self.assertNotEqual(code, 0)
            self.assertEqual(out["error"]["code"], "JEV.RESPONSE_INVALID")
            code, out = run_cli(common + ["--answers-file", write(d, "a2.json", {"*": dict(plan_answers(), owns=answer("no"))})])
            self.assertEqual(code, 0, out)
            self.assertEqual(out["data"]["results"][0]["verdict"], "satisfied")


class ExtraQuestionRefusalTests(unittest.TestCase):
    def refused(self, d, *paths, anchors=None):
        t = Transport()
        j = judged_with(d, t, *paths, anchors=anchors)
        self.assertNotEqual(j.code, 0, j.out)
        self.assertEqual(t.bodies, [], "a refused question file must send nothing")
        return j.out["error"]

    def test_id_already_in_the_set_is_refused(self):
        for qid in ("relevant", "addressed", "contradicted"):
            with self.subTest(qid=qid), tempfile.TemporaryDirectory() as d:
                err = self.refused(d, jsonl(d, "x.jsonl", question(qid)))
                self.assertEqual(err["code"], "INPUT.MALFORMED")
                self.assertIn(f"'{qid}' is already in the question set", err["message"])

    def test_duplicate_across_files_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            err = self.refused(d, jsonl(d, "a.jsonl", question("owns")), jsonl(d, "b.jsonl", question("owns")))
            self.assertEqual(err["code"], "INPUT.MALFORMED")
            self.assertIn("b.jsonl:1", err["message"])

    def test_malformed_lines_name_the_file_and_line(self):
        bad_lines = ("{not json", "[1, 2]", json.dumps({"type": "choice", "instructions": "x"}), json.dumps({"id": "", "type": "choice", "instructions": "x"}),
                     json.dumps({"id": "owns", "instructions": "x"}), json.dumps({"id": "owns", "type": "choice"}))
        for bad in bad_lines:
            with self.subTest(line=bad), tempfile.TemporaryDirectory() as d:
                err = self.refused(d, jsonl(d, "x.jsonl", question("first"), bad))
                self.assertEqual(err["code"], "INPUT.MALFORMED")
                self.assertIn("x.jsonl:2", err["message"])

    def test_missing_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            err = self.refused(d, str(Path(d) / "absent.jsonl"))
            self.assertEqual(err["code"], "INPUT.MISSING")

    def test_override_cannot_make_an_extra_question_gate(self):
        with tempfile.TemporaryDirectory() as d:
            overrides = write(d, "overrides.json", {"ANC-001": {"roles": {"compliance": "owns"}}})
            t = Transport()
            j = Judged(d, t, extra_args=["--extra-questions", jsonl(d, "x.jsonl", question("owns")), "--overrides-file", overrides])
            self.assertNotEqual(j.code, 0, j.out)
            self.assertEqual(t.bodies, [])
            err = j.out["error"]
            self.assertEqual(err["code"], "QUESTIONS.ROLES")
            self.assertIn("extra questions never gate", err["message"])

    def test_loader_leaves_the_base_set_untouched(self):
        base = ok(jj.load_question_set("plan"))
        before = json.dumps(base, sort_keys=True)
        with tempfile.TemporaryDirectory() as d:
            merged, sources = ok(jj.load_extra_questions([jsonl(d, "x.jsonl", question("owns"))], base))
        self.assertEqual(json.dumps(base, sort_keys=True), before)
        self.assertIn("owns", merged["questions"])
        self.assertEqual(merged["roles"], base["roles"])
        self.assertEqual(sources[0]["ids"], ["owns"])
        self.assertEqual(failure(jj.load_extra_questions(["/nonexistent/x.jsonl"], base)).code, "INPUT.MISSING")


if __name__ == "__main__":
    unittest.main()
