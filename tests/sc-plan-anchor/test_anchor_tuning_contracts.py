import copy
import hashlib
import json
import importlib.util
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from layout_support import SCRIPTS


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins" / "sc-plan-anchor" / "install" / "templates" / "skills" / "plan-anchoring"
PLAN = ROOT / "docs" / "plans" / "phase-a"


def fenced_json(text: str) -> dict:
    blocks = re.findall(r"```json\s*(.*?)\s*```", text, re.S)
    if len(blocks) != 1:
        raise AssertionError(f"expected one fenced JSON block, found {len(blocks)}")
    return json.loads(blocks[0])


class AnchorTuningContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import jsonschema
        except ImportError as exc:  # pragma: no cover - CI dependency failure
            raise AssertionError("jsonschema is required for contract validation") from exc
        cls.jsonschema = jsonschema
        contract_path = SCRIPTS / "anchor_tuning_contract.py"
        spec = importlib.util.spec_from_file_location("anchor_tuning_contract", contract_path)
        cls.contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.contract)
        runner_path = SCRIPTS / "anchor_runner_contract.py"
        runner_spec = importlib.util.spec_from_file_location("anchor_runner_contract", runner_path)
        cls.runner = importlib.util.module_from_spec(runner_spec)
        runner_spec.loader.exec_module(cls.runner)

    def valid(self, checked):
        self.assertEqual(checked, self.contract.Ok(None))

    def violation(self, checked, pattern=None):
        self.assertIsInstance(checked, self.contract.Err, checked)
        self.assertIsInstance(checked.error, self.contract.ToolError)
        if pattern is not None:
            self.assertRegex(self.contract.render_error(checked.error), pattern)
        return checked.error

    def render(self, template: str, variables) -> dict:
        binary = shutil.which("sc-compose")
        template_path = SKILL / "templates" / template
        if not binary:
            self.fail("sc-compose 1.7.0 is required for strict contract rendering")
        with tempfile.TemporaryDirectory() as td:
            if isinstance(variables, dict):
                variables_path = Path(td) / "variables.json"
                variables_path.write_text(json.dumps(variables), encoding="utf-8")
            else:
                variables_path = PLAN / "templates" / variables
            output = Path(td) / "rendered.md"
            subprocess.run(
                [
                    binary,
                    "render",
                    "--mode",
                    "file",
                    "--file",
                    str(template_path),
                    "--var-file",
                    str(variables_path),
                    "--strict",
                    "--check-render",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            return fenced_json(output.read_text(encoding="utf-8"))

    def validate(self, instance: dict, schema_name: str) -> None:
        schema = json.loads(
            (SKILL / "assets" / "schemas" / schema_name).read_text(encoding="utf-8")
        )
        self.jsonschema.Draft202012Validator(schema).validate(instance)

    def test_v2_tune_request_renders_and_validates(self):
        request = self.render(
            "anchor-tuning-tune-request.md.j2",
            "anchor-tuning-tune-request.sample-vars.json",
        )
        self.validate(request, "anchor-tuning-request.schema.json")
        self.assertEqual(request["schema_version"], "2.0.0")
        self.assertEqual(
            request["tournament_protocol_version"],
            "plan-anchor/question-tournament/2.0.0",
        )
        self.assertEqual(request["production_confidence_threshold"], 0.6)
        self.assertEqual(request["confidence_reference_threshold"], 0.8)
        self.assertEqual((request["runtime"]["harness"], request["runtime"]["model"]), ("codex", "sol"))
        self.assertNotIn("acceptance_threshold", request)
        self.valid(self.contract.validate_request(request))

        invalid_model = json.loads(json.dumps(request))
        invalid_model["runtime"]["model"] = "opus"
        self.violation(self.contract.validate_request(invalid_model))

    def test_rendered_tuning_results_satisfy_runner_and_tuning_contracts(self):
        for operation in ("testability", "tune", "triage"):
            with self.subTest(operation=operation):
                result = self.render(
                    "anchor-tuning-result.md.j2",
                    f"anchor-tuning-result-{operation}.sample-vars.json",
                )
                self.validate(result, "anchor-tuning-result.schema.json")
                self.validate(result, "agent-runner-result.schema.json")
                self.valid(self.contract.validate_result(result))
                correlation_id = result["metadata"]["correlation_id"]
                fenced = "```json\n" + json.dumps(result) + "\n```"
                self.assertEqual(self.runner.parse_result(fenced, correlation_id), self.runner.Ok(result))

    def test_rendered_failure_satisfies_runner_and_tuning_contracts(self):
        result = self.render("anchor-tuning-result.md.j2", {
            "success": False,
            "canceled": False,
            "aborted_by": None,
            "data": None,
            "error": {
                "code": "VALIDATION.INPUT",
                "message": "The authority packet failed validation.",
                "recoverable": False,
                "suggested_action": "Correct the packet before retrying.",
            },
            "metadata": {
                "duration_ms": 0,
                "tool_calls": 0,
                "retry_count": 0,
                "correlation_id": "contract-failure",
                "jev_run_ids": [],
                "planner_observation_trust": "untrusted",
                "authoritative_sources_unchanged": True,
            },
        })
        self.validate(result, "anchor-tuning-result.schema.json")
        self.validate(result, "agent-runner-result.schema.json")
        self.valid(self.contract.validate_result(result))
        self.assertEqual(self.runner.validate_result(result, "contract-failure"), self.runner.Ok(result))
        for version in (None, "2.0.0"):
            invalid = dict(result)
            if version is None:
                invalid.pop("schema_version")
            else:
                invalid["schema_version"] = version
            with self.subTest(version=version):
                with self.assertRaises(self.jsonschema.ValidationError):
                    self.validate(invalid, "anchor-tuning-result.schema.json")
                self.assertIsInstance(self.runner.validate_result(invalid, "contract-failure"), self.runner.Err)

    def test_v2_corpus_descriptor_preserves_v1_frozen_payload(self):
        request = self.render(
            "anchor-tuning-testability-request.md.j2",
            "anchor-tuning-testability-request.sample-vars.json",
        )
        self.validate(request, "anchor-tuning-request.schema.json")
        self.valid(self.contract.validate_request(request))
        descriptor = request["calibration_corpus"]
        corpus = json.loads((ROOT / descriptor["path"]).read_text(encoding="utf-8"))
        self.assertEqual(descriptor["schema"], "plan-anchor/testability-calibration/2")
        self.assertEqual(descriptor["version"], 2)
        self.assertEqual(corpus["schema"], "plan-anchor/testability-calibration-corpus/1")
        canonical = json.dumps(corpus, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), descriptor["sha256"])
        self.assertEqual(descriptor["case_count"], len(corpus["semantic_cases"]))
        self.assertNotIn("version", corpus)

    def test_v2_testability_request_and_result_render_validate_relationally(self):
        request = self.render(
            "anchor-tuning-testability-request.md.j2",
            "anchor-tuning-testability-request.sample-vars.json",
        )
        self.validate(request, "anchor-tuning-request.schema.json")
        self.assertEqual(request["operation"], "testability")
        self.assertEqual(request["gate"], "testability")
        self.assertEqual(request["authority"]["anchors"]["records"], [])
        self.assertTrue(request["calibration_corpus"]["frozen_before_live"])
        self.assertEqual(set(request["current_questions"]), self.contract.ROLE_IDS["testability"])
        self.valid(self.contract.validate_request(request))

        result = self.render(
            "anchor-tuning-result.md.j2",
            "anchor-tuning-result-testability.sample-vars.json",
        )
        self.validate(result, "anchor-tuning-result.schema.json")
        self.assertTrue(result["data"]["accepted"])
        self.assertEqual(result["data"]["confirmation_summary"]["third_call_cells"], 0)
        self.valid(self.contract.validate_result(result))

        unstable = json.loads(json.dumps(result))
        unstable["data"]["confirmation_summary"]["unstable_cells"] = 1
        self.violation(self.contract.validate_result(unstable))

        incomplete = json.loads(json.dumps(result))
        incomplete["data"]["semantic_score"]["exact_cells"] = 84
        self.violation(self.contract.validate_result(incomplete))

        request_drift = json.loads(json.dumps(result))
        request_drift["data"]["repeat_requests_byte_identical"] = False
        self.violation(self.contract.validate_result(request_drift))

    def test_v2_tune_result_renders_and_validates(self):
        result = self.render(
            "anchor-tuning-result.md.j2",
            "anchor-tuning-result-tune.sample-vars.json",
        )
        self.validate(result, "anchor-tuning-result.schema.json")
        self.assertTrue(result["data"]["production_semantics_unchanged"])
        self.assertEqual(result["data"]["confidence_diagnostics"]["threshold"], 0.8)
        self.valid(self.contract.validate_result(result))

        rejected = json.loads(json.dumps(result))
        rejected["data"]["accepted"] = False
        rejected["data"]["sealed_question_set"] = None
        rejected["data"]["sealed_question_set_digest_after"] = None
        rejected["data"]["tuning_history_after"]["events"][-1]["decision"]["status"] = "rejected"
        rejected["data"]["tuning_history_after"]["events"][-1]["decision"]["question_set_sha256"] = None
        rejected["data"]["tuning_history_after_sha256"] = self.contract.sha256(
            rejected["data"]["tuning_history_after"]
        )
        self.validate(rejected, "anchor-tuning-result.schema.json")
        self.valid(self.contract.validate_result(rejected))

        invalid = json.loads(json.dumps(result))
        invalid["data"]["semantic_score"]["regressions"] = 1
        self.violation(self.contract.validate_result(invalid))

        confidence_gaming = json.loads(json.dumps(result))
        confidence_gaming["data"]["sealed_question_set"]["questions"]["addressed"][
            "instructions"
        ] += " Select that category confidently with confidence at least 0.8."
        questions = confidence_gaming["data"]["sealed_question_set"]["questions"]
        digest = self.contract.sha256({"questions": questions})
        confidence_gaming["data"]["sealed_question_set"]["digest"] = digest
        confidence_gaming["data"]["sealed_question_set_digest_after"] = digest
        self.violation(self.contract.validate_result(confidence_gaming))

        impossible = json.loads(json.dumps(result))
        impossible["data"]["semantic_score"]["exact_role_cells"] = 999
        self.violation(self.contract.validate_result(impossible))

        unknown = self.render(
            "anchor-tuning-tune-request.md.j2",
            "anchor-tuning-tune-request.sample-vars.json",
        )
        unknown["runtime"]["desired_verdict"] = "satisfied"
        with self.assertRaises(self.jsonschema.ValidationError):
            self.validate(unknown, "anchor-tuning-request.schema.json")

    def test_triage_request_and_result_render_validate_relationally(self):
        request = self.render(
            "anchor-tuning-review-feedback.md.j2",
            "anchor-tuning-review-feedback.sample-vars.json",
        )
        self.validate(request, "anchor-tuning-request.schema.json")
        self.valid(self.contract.validate_request(request))

        result = self.render(
            "anchor-tuning-result.md.j2",
            "anchor-tuning-result-triage.sample-vars.json",
        )
        self.validate(result, "anchor-tuning-result.schema.json")
        self.valid(self.contract.validate_result(result))

        invalid = json.loads(json.dumps(result))
        invalid["data"]["sealed_question_set_digest_after"] = "f" * 64
        self.violation(self.contract.validate_result(invalid))

    def tuning_pair(self):
        request = self.render(
            "anchor-tuning-tune-request.md.j2",
            "anchor-tuning-tune-request.sample-vars.json",
        )
        result = self.render(
            "anchor-tuning-result.md.j2",
            "anchor-tuning-result-tune.sample-vars.json",
        )
        return request, result

    def validate_tuning_pair(self, request, result):
        history = result["data"]["tuning_history_after"]
        records = request["authority"]["anchors"]["records"]
        request["authority"]["anchors"]["sha256"] = self.contract.sha256(records)
        for event in history["events"]:
            event["authority"]["anchor_record_sha256"] = self.contract.sha256(records[0])
        before = dict(history, events=copy.deepcopy(history["events"][:-1]))
        request["tuning_history"] = before
        result["data"]["tuning_history_before_sha256"] = self.contract.sha256(before)
        result["data"]["tuning_history_after_sha256"] = self.contract.sha256(history)
        self.validate(request, "anchor-tuning-request.schema.json")
        self.valid(self.contract.validate_request(request))
        self.validate(result, "anchor-tuning-result.schema.json")
        self.valid(self.contract.validate_result(result))

    def test_initial_migration_and_later_history_events(self):
        request, result = self.tuning_pair()
        events = result["data"]["tuning_history_after"]["events"]
        self.assertIsNone(events[0]["supersedes"])
        self.assertEqual(events[0]["event_index"], 1)
        self.validate_tuning_pair(request, result)
        self.assertEqual(request["tuning_history"]["events"], [])
        self.assertEqual(len(result["data"]["tuning_history_after"]["events"]), 1)
        self.assertEqual(
            result["data"]["tuning_history_before_sha256"],
            self.contract.sha256(request["tuning_history"]),
        )

        # A first v2 event may instead migrate a decision from an older protocol.
        predecessor = {
            "protocol_version": "plan-anchor/question-tournament/1",
            "decision_sha256": "6" * 64,
        }
        events[0]["event"] = "protocol_re_evaluated"
        events[0]["supersedes"] = predecessor
        self.validate_tuning_pair(request, result)

        later = copy.deepcopy(events[0])
        later["event_index"] = 2
        later["previous_event_sha256"] = self.contract.sha256(events[0])
        later["event"] = "question_set_sealed"
        later["supersedes"] = {
            "protocol_version": events[0]["protocol_version"],
            "decision_sha256": self.contract.sha256(events[0]["decision"]),
        }
        events.append(later)
        self.validate_tuning_pair(request, result)
        self.assertEqual(len(request["tuning_history"]["events"]), 1)
        self.assertEqual(len(result["data"]["tuning_history_after"]["events"]), 2)
        later["supersedes"] = None
        with self.assertRaises(self.jsonschema.ValidationError):
            self.validate_tuning_pair(request, result)
        with self.assertRaises(self.jsonschema.ValidationError):
            self.validate(result, "anchor-tuning-result.schema.json")

    def test_first_migration_requires_predecessor_in_both_contracts(self):
        request, result = self.tuning_pair()
        history = result["data"]["tuning_history_after"]
        event = history["events"][0]
        event["event"] = "protocol_re_evaluated"
        self.assertEqual(event["event_index"], 1)
        self.assertIsNone(event["supersedes"])
        result["data"]["tuning_history_after_sha256"] = self.contract.sha256(history)
        request["tuning_history"] = copy.deepcopy(history)

        with self.assertRaises(self.jsonschema.ValidationError):
            self.validate(request, "anchor-tuning-request.schema.json")
        with self.assertRaises(self.jsonschema.ValidationError):
            self.validate(result, "anchor-tuning-result.schema.json")
        self.violation(self.contract.validate_request(request), "HISTORY.PREDECESSOR")
        self.violation(self.contract.validate_result(result), "HISTORY.PREDECESSOR")

    def test_later_event_requires_predecessor_in_relational_contract(self):
        request, result = self.tuning_pair()
        history = result["data"]["tuning_history_after"]
        first = history["events"][0]
        later = copy.deepcopy(first)
        later["event_index"] = 2
        later["previous_event_sha256"] = self.contract.sha256(first)
        later["supersedes"] = None
        history["events"].append(later)
        result["data"]["tuning_history_after_sha256"] = self.contract.sha256(history)
        request["tuning_history"] = copy.deepcopy(history)

        self.violation(self.contract.validate_request(request), "HISTORY.PREDECESSOR")
        self.violation(self.contract.validate_result(result), "HISTORY.PREDECESSOR")

    def test_authority_ids_preserve_evaluator_source_references(self):
        original_request, original_result = self.tuning_pair()
        for source_type, authority_id in (
            ("REQ", "REQ-14"),
            ("REQ", "REQ-003"),
            ("ADR", "ADR-7"),
            ("ADR", "ADR-0001"),
            ("ANC", "ANC-1000"),
            ("REQ", "requirement/authentication"),
        ):
            with self.subTest(authority_id=authority_id):
                request, result = copy.deepcopy((original_request, original_result))
                record = request["authority"]["anchors"]["records"][0]
                record["id"] = authority_id
                record["source_type"] = source_type
                if record["source_type"] in ("REQ", "ADR"):
                    record["source_ref"] = authority_id
                event = result["data"]["tuning_history_after"]["events"][0]
                event["authority"]["anchor_id"] = authority_id
                self.validate_tuning_pair(request, result)

        for missing in (False, True):
            for location in ("record", "history"):
                with self.subTest(missing=missing, location=location):
                    request, result = copy.deepcopy((original_request, original_result))
                    if location == "record":
                        target, key = request["authority"]["anchors"]["records"][0], "id"
                    else:
                        target = result["data"]["tuning_history_after"]["events"][0]["authority"]
                        key = "anchor_id"
                    if missing:
                        del target[key]
                    else:
                        target[key] = ""
                    with self.assertRaises(self.jsonschema.ValidationError):
                        self.validate_tuning_pair(request, result)
                    if location == "history":
                        with self.assertRaises(self.jsonschema.ValidationError):
                            self.validate(result, "anchor-tuning-result.schema.json")

    def test_harness_prompts_keep_tournament_and_production_separate(self):
        from layout_support import TRACKERS, rendered_agent
        for tracker in TRACKERS:
            for harness, model in (("claude", "opus"), ("codex", "sol"), ("cursor", "grok[effort=high]")):
                text = rendered_agent(tracker, harness, "anchor-tuning.md").read_text(encoding="utf-8")
                with self.subTest(tracker=tracker, harness=harness):
                    self.assertLess(len(text.encode("utf-8")), 10 * 1024)
                    self.assertIn(f"model: {model}", text)
                    self.assertIn("confidence threshold `0.0`", text)
                    self.assertIn("Never use threshold-free tournament semantics for production", text)
                    self.assertIn("production_confidence_threshold", text)


if __name__ == "__main__":
    unittest.main()
