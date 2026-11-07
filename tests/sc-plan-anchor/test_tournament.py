"""`batch` (the low-layer Jev runner), `bead-batch` (its tracker adapter) and `tournament` (a consumer).

Every test runs offline with --answers-file; the answers are a function of (item, candidate, repeat), so results
never depend on thread scheduling. The streaming test drives completion order with events, never with time; the
stream-order test proves the consumer keys lines by id: a reversed stream scores identically.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from layout_support import SCRIPTS, TEST_TRACKER
sys.path.insert(0, str(SCRIPTS))
import jev_judge as jj  # noqa: E402
import anchor_tuning_contract as contract  # noqa: E402

from test_jev_judge import QUOTE, STATEMENT, anchor, answer, plan_answers, record, run_cli, write  # noqa: E402

SKILL = SCRIPTS.parent
PLAN_QS = json.loads((SKILL / "assets" / "questions" / "plan.json").read_text(encoding="utf-8"))
ROLES = ("addressed", "contradicted", "relevant")
CORRELATION = "phase-z:ANC-001:planning"


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def tune_request(**changes):
    """A v2 tune request whose authority digests hold (planning gate, two repeats)."""
    intent = "Keep the runtime crates as copies of the legacy repo's crates."
    rec = {"id": "ANC-001", "version": 1, "state": "locked", "statement": STATEMENT, "quote": QUOTE, "kind": "directive",
           "scope": "the runtime crates", "check": "the plan copies the legacy crates",
           "fixtures": {"pass": ["We copy the legacy runtime crates."], "fail": ["We write the runtime crates from scratch."]}}
    request = {
        "schema_version": "2.0.0", "operation": "tune",
        "template": {"id": "anchor-tuning-tune-request", "version": "0.4.1", "sha256": "a" * 64},
        "correlation_id": CORRELATION,
        "runtime": {"workspace": "/w", "script": "/w/jev_judge.py", "version": "0.9.3", "sha256": "f" * 64,
                    "contract_script": "/w/anchor_tuning_contract.py", "contract_sha256": "e" * 64,
                    "agent": "anchor-tuning", "harness": "claude", "model": "opus"},
        "authority": {"intent": {"id": "phase-z-intent", "version": 1, "sha256": hashlib.sha256(intent.encode()).hexdigest(), "content": intent},
                      "anchors": {"records": [rec], "sha256": sha([rec])}},
        "gate": "planning", "current_questions": copy.deepcopy(PLAN_QS), "candidate_minimum": 3, "repeat_count": 2,
        "tournament_protocol_version": "plan-anchor/question-tournament/2.0.0",
        "production_confidence_threshold": 0.6, "confidence_reference_threshold": 0.8,
        "tuning_history": {"schema": "plan-anchor/tuning-history/2", "history_id": "phase-z:ANC-001:planning", "events": []},
        "diagnostic_plan": None,
    }
    request.update(changes)
    return request


def roles(rel, comp, conf):
    return {"relevant": rel, "addressed": comp, "contradicted": conf}


CASES = (
    ("FX-PASS", "fixture_pass", "We copy the legacy runtime crates.", roles("yes", "yes", "no"), "satisfied"),
    ("FX-FAIL", "fixture_fail", "We write the runtime crates from scratch.", roles("yes", "no", "yes"), "contradicted"),
    ("P-COMPLIANT", "compliant", "Start the runtime crates from copies of the legacy crates, then delete legacy modules.", roles("yes", "yes", "no"), "satisfied"),
    ("P-SILENT", "silent", "Size the runtime crates sprint by its deliverable count.", roles("yes", "no", "no"), "not_addressed"),
    ("P-TOPICAL", "topical_only", "Add a heading 'Runtime crate origin'; the body comes later.", roles("yes", "no", "no"), "not_addressed"),
    ("P-CONFLICT", "conflicting", "Write every runtime crate from scratch.", roles("yes", "no", "yes"), "contradicted"),
    ("P-IRRELEVANT", "irrelevant", "Add a --json flag to the status command.", roles("no", "no", "no"), "not_applicable"),
    ("P-BOUNDARY", "boundary", "Copy the legacy CLI crate; the runtime crates are planned elsewhere.", roles("yes", "no", "no"), "not_addressed"),
    ("P-EXCEPTION", "exception", "Copy the legacy runtime crates, except write the scheduler crate from scratch.", roles("yes", "yes", "yes"), "contradicted"),
)


def oracle(**changes):
    o = {"schema": "plan-anchor/tune-oracle/1", "gate": "planning", "anchor_id": "ANC-001",
         "authority_citations": ["ANC-001 v1 statement", "ANC-001 v1 fixtures.pass / fixtures.fail"],
         "cases": [{"case_id": cid, "probe": probe, "item": {"title": "Sprint deliverable", "text": text},
                    "expected_roles": dict(exp), "expected_verdict": verdict, "rationale": f"ANC-001 v1: {probe} probe."}
                   for cid, probe, text, exp, verdict in CASES]}
    o.update(changes)
    return o


def question(role, n):
    return {"type": "choice", "instructions": f"Variant {n}: does `item.text` meet the {role} judgment for `anchor.statement`?",
            "criteria": {"yes": f"{role} holds ({n})", "no": f"{role} does not hold ({n})", "unclear": f"cannot tell ({n})"}}


def candidates(**changes):
    c = {"schema": "plan-anchor/tune-candidates/1", "gate": "planning", "anchor_id": "ANC-001",
         "candidates": {role: {f"{role[0].upper()}{n}": question(role, n) for n in range(3)} for role in ROLES},
         "bundles": [{"bundle_id": f"S{n}", "roles": {role: f"{role[0].upper()}{n}" for role in ROLES}} for n in range(3)]}
    c.update(changes)
    return c


def fixture_for(conf=None, wrong=None, flips=None, failures=None):
    """Answers keyed '<case>/<bundle>/r<n>' for every case x bundle (baseline, S0..S2) x repeat.

    conf: {bundle: confidence}; wrong: {(case, bundle): {role: choice}} on every repeat;
    flips: {(case, bundle): {role: choice}} on repeat 2 only; failures: {key: [attempt entries]}.
    """
    conf, wrong, flips, failures = conf or {}, wrong or {}, flips or {}, failures or {}
    out = {}
    for cid, _probe, _text, exp, _verdict in CASES:
        for bundle in ("baseline", "S0", "S1", "S2"):
            for r in (1, 2):
                choices = dict(exp)
                choices.update(wrong.get((cid, bundle), {}))
                if r == 2:
                    choices.update(flips.get((cid, bundle), {}))
                p = conf.get(bundle, 0.9)
                out[f"{cid}/{bundle}/r{r}"] = {role: answer(choices[role], p) for role in ROLES}
    out.update(failures)
    return out


class TournamentCase(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)
        self.addCleanup(self.td.cleanup)

    def put(self, name, value):
        return write(self.d, name, value)

    def tournament(self, fixture, request=None, oracle_value=None, candidates_value=None, out="t", extra=()):
        argv = ["tournament", "--request", self.put("request.json", request or tune_request()),
                "--oracle", self.put("oracle.json", oracle_value or oracle()),
                "--candidates", self.put("candidates.json", candidates_value or candidates()),
                "--out", str(self.d / out), *extra]
        if fixture is not None:
            argv += ["--answers-file", self.put("answers.json", fixture)]
        return run_cli(argv)

    def ran(self, *args, **kwargs):
        code, out = self.tournament(*args, **kwargs)
        self.assertEqual((code, out["success"]), (0, True), out)
        return out["data"]

    def refused(self, code_expected, *args, **kwargs):
        code, out = self.tournament(*args, **kwargs)
        self.assertEqual((code, out["success"], out["error"]["code"]), (2, False, code_expected), out)
        return out

    def result_vars(self, out="t"):
        return json.loads((self.d / out / "result_vars.json").read_text(encoding="utf-8"))

    def assert_contract_valid(self, variables):
        envelope = dict(variables, schema_version="1.0.0")
        self.assertEqual(contract.validate_result(envelope), contract.Ok(None))
        try:
            import jsonschema
        except ImportError:  # pragma: no cover - CI installs it
            return
        schema = json.loads((SKILL / "assets" / "schemas" / "anchor-tuning-result.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(envelope)

    def rankings(self, variables):
        return {r["bundle_id"]: r for r in variables["data"]["candidate_rankings"]}


class TournamentTests(TournamentCase):
    def test_request_fixture_is_schema_valid(self):
        try:
            import jsonschema
        except ImportError:  # pragma: no cover
            self.skipTest("jsonschema not installed")
        schema = json.loads((SKILL / "assets" / "schemas" / "anchor-tuning-request.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(tune_request())
        self.assertEqual(contract.validate_request(tune_request()), contract.Ok(None))
        for name in ("tune-oracle", "tune-candidates"):
            schema = json.loads((SKILL / "assets" / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(oracle() if name == "tune-oracle" else candidates())

    def test_accepted_bundle_is_sealed_and_ranked(self):
        # the baseline misses P-TOPICAL; S0..S2 are exact; S0 is the most confident
        fixture = fixture_for(conf={"S0": 0.95, "S1": 0.7}, wrong={("P-TOPICAL", "baseline"): {"addressed": "unclear"}})
        data = self.ran(fixture)
        self.assertEqual((data["accepted"], data["selected_bundle"], data["calls"], data["retries"]), (True, "S0", 72, 0))
        self.assertEqual(data["decision"]["status"], "sealed")
        variables = self.result_vars()
        self.assert_contract_valid(variables)
        d = variables["data"]
        self.assertEqual(d["semantic_score"], {"exact_role_cells": 54, "total_role_cells": 54, "exact_semantic_verdicts": 18,
                                               "total_semantic_verdicts": 18, "stable_cases": 9, "total_cases": 9, "regressions": 0})
        expected_questions = {role: question(role, 0) for role in ROLES}
        self.assertEqual(d["sealed_question_set"], {"digest": sha({"questions": expected_questions}), "questions": expected_questions})
        self.assertEqual([r["bundle_id"] for r in d["candidate_rankings"]], ["S0", "S2", "S1", "baseline"])
        ranks = self.rankings(variables)
        self.assertFalse(ranks["baseline"]["semantic_accepted"])
        self.assertIn("P-TOPICAL: addressed unclear, expected no", ranks["baseline"]["mismatches"])
        self.assertTrue(ranks["S1"]["semantic_accepted"])
        self.assertEqual(ranks["S1"]["confidence"]["cells_at_or_above_threshold"], 0)
        self.assertEqual(len(d["acceptance_table"]), 9)
        self.assertTrue(all(row["accepted"] and row["stable"] for row in d["acceptance_table"]))
        event = d["tuning_history_after"]["events"][-1]
        self.assertEqual((event["event_index"], event["event"], event["candidate"]["candidate_id"]), (1, "question_set_sealed", "S0"))
        self.assertEqual(event["oracle"]["sha256"], sha(oracle()))
        self.assertEqual(len(event["evidence"]["run_ids"]), 18)
        self.assertEqual(variables["metadata"]["correlation_id"], CORRELATION)
        lines = [json.loads(x) for x in (self.d / "t" / "results.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lines), 72)
        by_id = {x["request_id"]: x for x in lines}
        line = by_id[f"{CORRELATION}/P-SILENT/ANC-001/S0/r2"]
        self.assertEqual(line["run_id"], hashlib.sha256(line["request_id"].encode()).hexdigest()[:16])
        self.assertEqual(line["request_sha256"], hashlib.sha256(jj.encode_body(line["request"])).hexdigest())
        self.assertEqual(line["request"]["state"]["anchor"]["statement"], STATEMENT)
        self.assertEqual(line["answers"], line["raw_response"]["answers"])
        self.assertEqual(json.loads((self.d / "t" / "oracle.frozen.json").read_text(encoding="utf-8")), oracle())

    def test_unstable_repeats_are_not_accepted(self):
        flips = {("P-SILENT", b): {"addressed": "yes"} for b in ("baseline", "S0", "S1", "S2")}
        data = self.ran(fixture_for(flips=flips))
        self.assertEqual((data["accepted"], data["selected_bundle"], data["decision"]["status"]), (False, None, "unstable"))
        self.assertEqual(data["decision"]["reason_code"], "TOURNAMENT.UNSTABLE")
        variables = self.result_vars()
        self.assert_contract_valid(variables)
        d = variables["data"]
        self.assertIsNone(d["sealed_question_set"])
        self.assertEqual(d["semantic_score"]["stable_cases"], 8)
        row = next(r for r in d["acceptance_table"] if r["case_id"] == "P-SILENT")
        self.assertEqual((row["stable"], row["accepted"], row["semantic_verdicts"]), (False, False, ["not_addressed", "satisfied"]))
        self.assertTrue(all("P-SILENT: unstable across repeats" in r["mismatches"] for r in d["candidate_rankings"]))

    def test_regression_against_the_baseline_rejects_a_bundle(self):
        # baseline exact everywhere; S0 calls the conflict probe compliant on both repeats (stable but wrong);
        # S1 and S2 tie with the baseline on every score, so the smallest set wins (S1: shortest, then lowest id)
        data = self.ran(fixture_for(wrong={("P-CONFLICT", "S0"): {"contradicted": "no"}}))
        self.assertEqual((data["accepted"], data["selected_bundle"]), (True, "S1"))
        variables = self.result_vars()
        self.assert_contract_valid(variables)
        s0 = self.rankings(variables)["S0"]
        self.assertEqual((s0["semantic_accepted"], s0["regressions"], s0["stable_cases"]), (False, 1, 9))
        self.assertIn("regression", s0["reason"])

    def test_retry_is_recorded_and_an_unanswered_call_is_incomplete_evidence(self):
        ok = {role: answer(choice, 0.9) for role, choice in CASES[0][3].items()}
        fixture = fixture_for(failures={
            "FX-PASS/S0/r1": [{"__error__": "JEV.OVERLOADED"}, ok],
            "FX-PASS/S1/r1": [{"__error__": "JEV.OVERLOADED"}, {"__error__": "JEV.OVERLOADED"}],
        })
        data = self.ran(fixture)
        self.assertEqual((data["accepted"], data["retries"], data["failed_calls"]), (True, 2, [f"{CORRELATION}/FX-PASS/ANC-001/S1/r1"]))
        variables = self.result_vars()
        self.assertEqual(variables["metadata"]["retry_count"], 2)
        ranks = self.rankings(variables)
        self.assertEqual((ranks["S1"]["complete"], ranks["S1"]["semantic_accepted"]), (False, False))
        self.assertTrue(ranks["S0"]["semantic_accepted"])
        lines = {json.loads(x)["request_id"]: json.loads(x) for x in (self.d / "t" / "results.jsonl").read_text(encoding="utf-8").splitlines()}
        retried = lines[f"{CORRELATION}/FX-PASS/ANC-001/S0/r1"]
        self.assertEqual((retried["ok"], retried["retry_count"], [a["ok"] for a in retried["attempts"]]), (True, 1, [False, True]))

    def test_stream_order_does_not_change_the_score(self):
        self.ran(fixture_for(conf={"S2": 0.95}, wrong={("P-EXCEPTION", "S1"): {"contradicted": "no"}}))
        first = self.result_vars()
        lines = (self.d / "t" / "results.jsonl").read_text(encoding="utf-8").splitlines()
        reordered = self.put("reordered.jsonl", "\n".join(reversed(lines)) + "\n")
        data = self.ran(None, extra=("--results", reordered))
        self.assertEqual(data["selected_bundle"], "S2")
        second = self.result_vars()
        for variables in (first, second):
            variables["metadata"].pop("duration_ms")
            variables["data"]["evidence"].pop("results_path")
        self.assertEqual(first, second)

    def test_oracle_changed_after_first_response_is_refused(self):
        fixture = fixture_for()
        self.ran(fixture)
        tampered = oracle()
        tampered["cases"][3]["rationale"] = "relabelled after seeing an answer"
        self.refused("TOURNAMENT.ORACLE_CHANGED", None, oracle_value=tampered,
                     extra=("--results", str(self.d / "t" / "results.jsonl")))
        # the tuning history also pins the oracle: a later tournament in a fresh folder must reuse it
        history = self.result_vars()["data"]["tuning_history_after"]
        self.refused("TOURNAMENT.ORACLE_CHANGED", fixture, request=tune_request(tuning_history=history), oracle_value=tampered, out="t2")
        data = self.ran(fixture, request=tune_request(tuning_history=history), out="t3")
        self.assertTrue(data["accepted"])
        variables = self.result_vars("t3")
        self.assert_contract_valid(variables)
        event = variables["data"]["tuning_history_after"]["events"][-1]
        self.assertEqual((event["event_index"], event["previous_event_sha256"]), (2, sha(history["events"][0])))

    def test_stream_for_other_candidates_is_refused(self):
        self.ran(fixture_for())
        changed = candidates()
        changed["candidates"]["relevant"]["R0"] = question("relevant", 9)
        self.refused("TOURNAMENT.EVIDENCE_MISMATCH", None, candidates_value=changed,
                     extra=("--results", str(self.d / "t" / "results.jsonl")))

    def test_existing_stream_is_never_overwritten(self):
        self.ran(fixture_for())
        self.refused("TOURNAMENT.OUT_EXISTS", fixture_for())

    def test_contract_invalid_request_is_refused_before_any_call(self):
        bad_model = tune_request()
        bad_model["runtime"]["model"] = "sol"
        out = self.refused("TOURNAMENT.REQUEST_INVALID", fixture_for(), request=bad_model)
        self.assertEqual(out["data"]["violation"]["code"], "VALIDATION.MODEL")
        out = self.refused("TOURNAMENT.REQUEST_INVALID", fixture_for(), request=tune_request(acceptance_threshold=0.8))
        self.assertEqual(out["data"]["violation"]["code"], "VALIDATION.DEPRECATED")
        digest = tune_request()
        digest["authority"]["anchors"]["sha256"] = "c" * 64
        self.refused("TOURNAMENT.AUTHORITY_DIGEST", fixture_for(), request=digest)
        self.refused("TOURNAMENT.GATE_UNSUPPORTED", fixture_for(), request=tune_request(operation="testability", gate="testability"))
        self.assertFalse((self.d / "t" / "results.jsonl").exists())

    def test_oracle_and_candidate_checks(self):
        inconsistent = oracle()
        inconsistent["cases"][3]["expected_verdict"] = "satisfied"
        self.refused("TOURNAMENT.ORACLE_INCONSISTENT", fixture_for(), oracle_value=inconsistent)
        sparse = oracle(cases=oracle()["cases"][:3])
        out = self.refused("TOURNAMENT.ORACLE_COVERAGE", fixture_for(), oracle_value=sparse)
        self.assertIn("silent", out["error"]["message"])
        few = candidates()
        del few["candidates"]["addressed"]["A2"]
        few["bundles"] = few["bundles"][:2]
        self.refused("TOURNAMENT.CANDIDATES_INVALID", fixture_for(), candidates_value=few)
        meta = candidates()
        meta["candidates"]["addressed"]["A1"]["instructions"] += " Answer with confidence at least 0.8."
        self.refused("TOURNAMENT.QUESTION_META", fixture_for(), candidates_value=meta)

    def test_dry_run_writes_requests_and_scores_nothing(self):
        data = self.ran(None, extra=("--dry-run",))
        self.assertEqual((data["dry_run"], data["requests"]), (True, 72))
        dry = [json.loads(x) for x in (self.d / "t" / "requests.dry-run.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual((len(dry), {x["dry_run"] for x in dry}, {x["ok"] for x in dry}), (72, {True}, {False}))
        self.assertFalse((self.d / "t" / "results.jsonl").exists())
        self.assertFalse((self.d / "t" / "result_vars.json").exists())

    def test_live_run_fails_closed_without_credentials(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            self.refused("AUTH.CREDENTIALS", None)
        self.assertFalse((self.d / "t" / "results.jsonl").exists())


ANCHOR_STATE = {"id": "ANC-001", "statement": STATEMENT, "scope": "the runtime crates", "kind": "directive"}


def request_line(item_id, text, *cands, title=""):
    return {"item": {"id": item_id, "title": title, "text": text}, "anchor": dict(ANCHOR_STATE),
            "questions": [{"candidate_id": c, "questions": qs} for c, qs in cands]}


def alt_set(n):
    return {role: question(role, n) for role in ROLES}


def jsonl(lines):
    return "".join(json.dumps(x) + "\n" for x in lines)


class BatchTests(TournamentCase):
    """The low layer: JSONL request lines in, JSONL result lines out on stdout and in the append-only log."""

    LINES = [request_line("s1", "We copy the legacy crates.", ("cur", PLAN_QS["questions"]), ("alt", alt_set(1)), title="Sprint 1"),
             request_line("s3", "# Sprint 3\n\nCopy the legacy runtime crates.\n", ("cur", PLAN_QS["questions"]))]
    FIXTURE = {"s1/cur": plan_answers(), "s1/alt/r2": plan_answers(comp="no"), "alt": plan_answers(), "*": plan_answers(conf="yes")}

    def subprocess_batch(self, run_dir, *extra, stdin=None):
        """The installed script as a separate process: stdout bytes exactly as a caller sees them."""
        argv = [sys.executable, str(SCRIPTS / "jev_judge.py"), "batch", "--run-dir", str(self.d / run_dir), "--run-name", "r1",
                "--answers-file", self.put("answers.json", self.FIXTURE), "--repeat", "2", "--request-prefix", "run-7", *extra]
        proc = subprocess.run(argv, input=stdin, capture_output=True, cwd=str(self.d))
        return proc

    def log(self, run_dir):
        return (self.d / run_dir / "tournament-r1.jsonl").read_bytes()

    def test_lines_are_keyed_by_id_with_verdicts_and_request_evidence(self):
        proc = self.subprocess_batch("runs", "--input", self.put("in.jsonl", jsonl(self.LINES)))
        self.assertEqual((proc.returncode, proc.stderr), (0, b""))
        lines = [json.loads(x) for x in proc.stdout.decode("utf-8").splitlines()]
        self.assertEqual([x["request_id"] for x in lines],
                         ["run-7/s1/ANC-001/cur/r1", "run-7/s1/ANC-001/cur/r2", "run-7/s1/ANC-001/alt/r1", "run-7/s1/ANC-001/alt/r2",
                          "run-7/s3/ANC-001/cur/r1", "run-7/s3/ANC-001/cur/r2"])
        by_key = {(x["item_id"], x["candidate_id"], x["repeat"]): x for x in lines}
        self.assertEqual((by_key[("s1", "cur", 1)]["verdict"], by_key[("s1", "alt", 2)]["verdict"], by_key[("s3", "cur", 1)]["verdict"]),
                         ("satisfied", "not_addressed", "contradicted"))
        line = by_key[("s1", "alt", 2)]
        self.assertEqual(line["answers"]["addressed"]["probabilities"], answer("no")["probabilities"])
        self.assertEqual((line["run_id"], line["ok"], line["retry_count"], line["schema"]),
                         (hashlib.sha256(b"run-7/s1/ANC-001/alt/r2").hexdigest()[:16], True, 0, "plan-anchor/jev-batch-result/1"))
        self.assertEqual(line["request"]["questions"], alt_set(1))
        self.assertEqual(line["request"]["state"]["item"], {"id": "s1", "title": "Sprint 1", "text": "We copy the legacy crates."})
        self.assertEqual(by_key[("s1", "cur", 1)]["request_sha256"], by_key[("s1", "cur", 2)]["request_sha256"])
        try:
            import jsonschema
        except ImportError:  # pragma: no cover - CI installs it
            return
        schemas = SKILL / "assets" / "schemas"
        for name, values in (("jev-batch-request", self.LINES), ("jev-batch-result", lines)):
            validator = jsonschema.Draft202012Validator(json.loads((schemas / f"{name}.schema.json").read_text(encoding="utf-8")))
            for value in values:
                validator.validate(value)

    def test_log_matches_stdout_byte_for_byte_and_stdin_matches_file_input(self):
        from_file = self.subprocess_batch("a", "--input", self.put("in.jsonl", jsonl(self.LINES)))
        from_stdin = self.subprocess_batch("b", stdin=jsonl(self.LINES).encode("utf-8"))
        self.assertEqual((from_file.returncode, from_stdin.returncode), (0, 0))
        self.assertEqual(len(from_file.stdout.splitlines()), 6)
        self.assertEqual(self.log("a"), from_file.stdout)
        self.assertEqual(self.log("b"), from_stdin.stdout)
        self.assertEqual(from_stdin.stdout, from_file.stdout)
        # the log is append-only: a second run with the same name adds its lines after the first run's
        again = self.subprocess_batch("a", "--input", str(self.d / "in.jsonl"))
        self.assertEqual(self.log("a"), from_file.stdout + again.stdout)

    def test_results_stream_in_request_order_as_each_answer_arrives(self):
        """Completion order is forced to c3, c1, c2 with events (no sleeps); lines still come out c1, c2, c3, and c1
        is yielded while c2 is still unanswered, so nothing is held back for the end of the batch."""
        line = request_line("s1", "text", ("c1", PLAN_QS["questions"]), ("c2", PLAN_QS["questions"]), ("c3", PLAN_QS["questions"]))
        c3_done, release_c2 = threading.Event(), threading.Event()
        completed, waits = [], []
        real = jj.run_batch_job

        def controlled(job, settings, api_key, fixture, abort):
            if job.candidate_id == "c1":
                waits.append(c3_done.wait(timeout=30))  # a guard against a deadlocked implementation, not a timing input
            if job.candidate_id == "c2":
                waits.append(release_c2.wait(timeout=30))
            result = real(job, settings, api_key, fixture, abort)
            completed.append(job.candidate_id)
            if job.candidate_id == "c3":
                c3_done.set()
            return result

        settings = jj.BatchSettings("plan", "fixture-model", 1, "p", 0.6, 30.0, 3, 24000, False)

        async def consume():
            got = []
            async for result in jj.stream_batch([line], settings, "", {"*": plan_answers()}):
                got.append((result["candidate_id"], list(completed)))
                release_c2.set()
            return got

        with mock.patch.object(jj, "run_batch_job", controlled):
            got = jj.asyncio.run(consume())
        self.assertEqual(waits, [True, True])
        self.assertEqual([cid for cid, _ in got], ["c1", "c2", "c3"])
        self.assertEqual(got[0][1], ["c3", "c1"])  # c1 was yielded before c2 had an answer
        self.assertEqual(completed, ["c3", "c1", "c2"])

    def test_failed_call_is_a_line_and_exit_2_with_the_error_on_stderr(self):
        self.FIXTURE = {"s1/cur": [{"__error__": "JEV.OVERLOADED"}, {"__error__": "JEV.OVERLOADED"}], "*": plan_answers()}
        proc = self.subprocess_batch("runs", "--repeat", "1", stdin=jsonl(self.LINES[:1]).encode("utf-8"))
        self.assertEqual(proc.returncode, 2)
        lines = [json.loads(x) for x in proc.stdout.decode("utf-8").splitlines()]
        failed = next(x for x in lines if x["candidate_id"] == "cur")
        self.assertEqual((failed["ok"], failed["retry_count"], failed["error"]["code"], failed["verdict"]), (False, 1, "JEV.OVERLOADED", None))
        self.assertTrue(next(x for x in lines if x["candidate_id"] == "alt")["ok"])
        self.assertEqual(json.loads(proc.stderr)["error"]["code"], "JEV.OVERLOADED")
        self.assertEqual(self.log("runs"), proc.stdout)

    def test_bad_input_is_refused_before_any_line(self):
        def refused(lines_text, *extra):
            code, out = run_cli(["batch", "--input", self.put("bad.jsonl", lines_text), "--run-dir", str(self.d / "runs"), "--dry-run", *extra])
            self.assertEqual((code, out["success"]), (2, False), out)
            return out["error"]["code"]
        good = jsonl(self.LINES)
        self.assertEqual(refused(good + "{not json\n"), "INPUT.MALFORMED")
        self.assertEqual(refused(jsonl([request_line("s1", "x", ("c", PLAN_QS["questions"]), ("c", PLAN_QS["questions"]))])), "VALIDATION.INPUT")
        self.assertEqual(refused(good + jsonl(self.LINES[:1])), "VALIDATION.INPUT")  # the same request twice
        self.assertEqual(refused(jsonl([request_line("bad id", "x", ("c", PLAN_QS["questions"]))])), "VALIDATION.INPUT")
        self.assertEqual(refused(good, "--max-workers", "5"), "VALIDATION.INPUT")
        self.assertEqual(refused("\n"), "INPUT.EMPTY")
        self.assertFalse((self.d / "runs").exists())
        code, out = run_cli(["batch", "--input", self.put("ok.jsonl", good)])
        self.assertEqual((code, out["error"]["code"]), (2, "VALIDATION.INPUT"))  # no log directory

    def test_live_run_fails_closed_before_any_line(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}), mock.patch.object(jj, "credential_store_api_key", return_value=""):
            code, out = run_cli(["batch", "--input", self.put("in.jsonl", jsonl(self.LINES)), "--run-dir", str(self.d / "runs")])
        self.assertEqual((code, out["error"]["code"]), (2, "AUTH.CREDENTIALS"))
        self.assertFalse((self.d / "runs").exists())


@unittest.skipIf(os.name == "nt", "the fake tracker CLI is a POSIX script")
class BeadBatchTests(TournamentCase):
    """The high layer reads beads through the tracker anchor_tracker.py selects (a fake CLI here; no Dolt server)
    and produces low-layer request lines; it never writes to the tracker."""

    BEADS = {
        "ex-7": {"id": "ex-7", "title": "Sprint 7 runtime crates", "description": "Copy the legacy runtime crates.",
                 "acceptance_criteria": "Crates build.", "notes": "not sent at the plan gate", "status": "open"},
        "ex-8": {"id": "ex-8", "title": "Sprint 8 scheduler", "description": "Copy the scheduler crate.", "status": "open"},
        "ex-q": {"id": "ex-q", "title": "ANC-001 plan questions", "status": "open",
                 "description": "Current overrides:\n\n```json\n" + json.dumps({"questions": {"addressed": question("addressed", 5)}}) + "\n```\n",
                 "dependents": [{"id": c, "dependency_type": "parent-child"} for c in ("ex-c1", "ex-c2", "ex-c3")]},
        "ex-c1": {"id": "ex-c1", "parent": "ex-q", "status": "open", "description": "```json\n" + json.dumps({"questions": alt_set(1)}) + "\n```"},
        "ex-c2": {"id": "ex-c2", "parent": "ex-q", "status": "closed", "close_reason": "lost", "description": "```json\n{}\n```"},
        "ex-c3": {"id": "ex-c3", "parent": "ex-q", "status": "open", "description": "```json\n{}\n```"},
    }

    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q", str(self.d)], check=True)
        beads = self.d / ".beads"
        beads.mkdir()
        if TEST_TRACKER == "bd":
            (beads / "metadata.json").write_text(json.dumps({"backend": "dolt"}), encoding="utf-8")
        bin_dir = self.d / "bin"
        bin_dir.mkdir()
        db = self.put("bin/beads.json", self.BEADS)
        calls = self.d / "bin" / "calls.log"
        cli = bin_dir / TEST_TRACKER
        cli.write_text(
            f"#!{sys.executable}\nimport json, sys\ndb = json.load(open({db!r}))\n"
            f"open({str(calls)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
            "args = [a for a in sys.argv[1:] if a != '--json']\n"
            "if args[0] == 'show':\n    print(json.dumps([db[i] for i in args[1:]]))\n"
            "elif args[0] == 'children':\n    print(json.dumps([b for b in db.values() if b.get('parent') == args[1]]))\n"
            "else:\n    sys.exit(3)\n", encoding="utf-8")
        cli.chmod(0o755)
        self.calls = calls
        self.path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        self.anchors = self.put("plan/anchors.json", record(anchor(beads={"anchor": None, "plan_questions": "ex-q", "dev_questions": None})))

    def bead_batch(self, *extra):
        argv = ["bead-batch", "--anchors", self.anchors, "--gate", "plan", "--anchor", "ANC-001", "--item", "ex-7", "--item", "ex-8",
                "--repository-root", str(self.d), *extra]
        with mock.patch.dict(os.environ, {"PATH": self.path}):
            return run_cli(argv)

    def test_emit_produces_the_exact_request_lines(self):
        code, out = self.bead_batch("--candidates", "--emit")
        self.assertEqual(code, 0, out)
        current = dict(PLAN_QS["questions"], addressed=question("addressed", 5))
        cands = [{"candidate_id": "ex-q", "questions": current, "roles": PLAN_QS["roles"]},
                 {"candidate_id": "ex-c1", "questions": {k: alt_set(1)[k] for k in PLAN_QS["questions"]}, "roles": PLAN_QS["roles"]},
                 {"candidate_id": "ex-c3", "questions": PLAN_QS["questions"], "roles": PLAN_QS["roles"]}]
        expected = [
            {"item": {"id": "ex-7", "title": "Sprint 7 runtime crates",
                      "text": "# Sprint 7 runtime crates\n\n## Description\n\nCopy the legacy runtime crates.\n\n## Acceptance criteria\n\nCrates build.\n"},
             "anchor": ANCHOR_STATE, "questions": cands},
            {"item": {"id": "ex-8", "title": "Sprint 8 scheduler", "text": "# Sprint 8 scheduler\n\n## Description\n\nCopy the scheduler crate.\n"},
             "anchor": ANCHOR_STATE, "questions": cands},
        ]
        self.assertEqual(out, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in expected))
        verbs = {line.split()[0] for line in self.calls.read_text(encoding="utf-8").splitlines()}
        self.assertLessEqual(verbs, {"show", "children"})  # reads only

    def test_without_candidates_only_the_question_bead_is_judged(self):
        code, out = self.bead_batch("--emit")
        self.assertEqual(code, 0, out)
        self.assertEqual([[c["candidate_id"] for c in json.loads(x)["questions"]] for x in out.splitlines()], [["ex-q"], ["ex-q"]])

    def test_piped_run_equals_batch_over_the_emitted_lines(self):
        """No judging logic in the adapter: its run is byte-identical to `batch` over the lines it emits."""
        _, emitted = self.bead_batch("--candidates", "--emit")
        fixture = self.put("answers.json", {"ex-c1": plan_answers(comp="no"), "*": plan_answers()})
        common = ("--answers-file", fixture, "--run-name", "r1", "--request-prefix", "t")
        code, piped = self.bead_batch("--candidates", *common)
        self.assertEqual(code, 0, piped)
        code, direct = run_cli(["batch", "--input", self.put("emitted.jsonl", emitted), "--run-dir", str(self.d / "direct"), *common])
        self.assertEqual(code, 0, direct)
        self.assertEqual(piped, direct)
        self.assertEqual((self.d / "plan" / "anchor-runs" / "tournament-r1.jsonl").read_text(encoding="utf-8"), piped)
        self.assertEqual(len(piped.splitlines()), 6)

    def test_unresolved_and_malformed_question_beads_are_refused(self):
        self.anchors = self.put("plan/anchors.json", record(anchor()))
        code, out = self.bead_batch("--emit")
        self.assertEqual((code, out["error"]["code"]), (2, "QUESTIONS.BEAD_UNRESOLVED"), out)
        self.anchors = self.put("plan/anchors.json", record(anchor(beads={"anchor": None, "plan_questions": "ex-7", "dev_questions": None})))
        code, out = self.bead_batch("--emit")
        self.assertEqual((code, out["error"]["code"]), (2, "QUESTIONS.BEAD_MALFORMED"), out)


if __name__ == "__main__":
    unittest.main()
