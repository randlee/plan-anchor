# j-5 plan: plan-anchor on the j-4 client

Base: plan-anchor `origin/plan/phase-j` @ cee4dc1. `JJ:N` = `plugins/sc-plan-anchor/install/templates/skills/plan-anchoring/scripts/jev_judge.py.j2` at that commit (4,625 lines); `S/` = that `scripts/` folder; `T/` = `tests/sc-plan-anchor/`. The upstream plans cite JJ by older line numbers (`leaning_of` :1913, :2222, :2247, `decide` :1842); at cee4dc1 they are :1781, :2057, :3198 and :1710. Client API = sc-agent `origin/sprint/j-4:docs/plans/phase-j/j-4-plan.md` (rendered `consumer.py.j2` 2.0.0, here `S/decidr_client.py.j2`). Record ids are those on `plan/phase-j` (PR #159, which renames them to REQ-PA-/ADR-PA-, is open and not cited). Written by reading the code; no j-5 code yet.

## Goal

Rand (ANC-015, ANC-016, rule 0): "judge-jev and plan-anchor simply supply tool name and follow the rules established for all decidr based tools"; "derivative tools should defer to the default tool rules and not use injection path for production code (test only)". Measurable: plan-anchor sends only through the rendered j-4 client on one `open_run(...)` per live command (plus one `cache=False` Run where a resend is required, see Rule-7 item 1); `batch`, `bead-batch`, `tournament` write `jev-batch-result/2` lines only; run files hold `session_ids`, not answers (REQ-013, REQ-086); and these greps over `S/*.j2` minus `decidr_client.py.j2` are empty: `from result |redact_sensitive|BEARER_RE|DEFAULT_MODEL|remote_preflight|total_attempts|fixture_attempt|questions_digest|BATCH_MAX_WORKERS|retry_count|model_answered|raw_response|jev-batch-result/1|stamp\(|general_log`.

## Layout

| file | holds after j-5 |
|---|---|
| S/decidr_client.py.j2 | re-render of j-4 `consumer.py.j2` with `client_name=plan-anchor, sitr=false, tool_version={{ version }}`; never hand-edited |
| S/result.py.j2 | deleted (Ok/Err/Result/ToolError/err/run_main/utf8_stdio come from decidr_client) |
| S/jev_judge.py.j2 | CLI and plan-anchor domain logic: question sets, `decide`, triage, run files, batch request building, tournament scoring; `with_run`, `dry_run_sink`, `batch_verdict` |
| S/change_report.py.j2 | run-file loading for `report`; `run/2` only |
| S/anchor_tracker.py.j2, S/anchor_tuning_contract.py.j2, S/anchor_runner_contract.py.j2, S/plan_anchor_settings.py.j2 | import line only (result -> decidr_client); anchor_tuning_contract: evidence keys per Contracts |
| assets/schemas/jev-batch-result.schema.json | deleted (the wheel ships /2; tests read it via importlib.resources) |
| assets/schemas/anchor-tuning-result.schema.json, anchor-tuning-request.schema.json, assets/examples/run.live.example.json | evidence/run keys per Contracts |
| scripts/install_sc_decidr_ci.py | pin = the j-4 prerelease |
| T/test_run_scoped.py (new), T/test_tournament.py, T/test_jev_judge.py, T/test_change_report.py, T/test_anchor_tuning_contracts.py | tests below; T/test_result.py, T/sc_decidr_test_double.py deleted (FakeRun replaces the double) |

## Library pattern (rule 0)

- Config: plan-anchor passes `--model`, `--timeout`, `--max-workers`, `--project` through as optional overrides (default `None`); the wheel's layered config resolves everything else. No default model, worker cap, timeout default or request cap in plan-anchor.
- Logging: the client passes `tool="plan-anchor"`; logs go to `<PLAN_ANCHOR_LOG_ROOT|~/.sc-agent>/logs/plan-anchor.log.jsonl`. plan-anchor's production code never passes `seams`; tests pass `seams={"general_log": ...}` or use `sc_agent.testing.fake_open_run` (ANC-016).
- Limits: none of plan-anchor's own; the Run's errors are returned unchanged.
- Results: every client call is read as a typed value (`isinstance(x, Err)`, `.value`, `Reply.answers`), never as a dict.

## Public surface (exact Python; plan-anchor has no Rust)

```python
# S/jev_judge.py.j2 (and the 5 other importers)
from decidr_client import Err, Ok, Result, ToolError, err, run_main, utf8_stdio, ClientError, Reply, from_tool_error, typed_answer, NoulAnswer, ChoiceAnswer, ScoreAnswer, BoxAnswer

def with_run(args: argparse.Namespace,
             command: Callable[[Any, Any], Result[dict, ClientError]], *,
             resend: bool = False) -> Result[dict, ClientError]
    # dry run or --answers-file: command(None, None); the wheel is never imported (REQ-016, REQ-047).
    # live: with decidr_client.open_run(model=args.model, project=args.project, timeout_secs=args.timeout,
    #                                   workers=args.max_workers, repeat=args.repeat) as run  (Err -> returned, nothing sent)
    #       and, when resend, a second open_run(..., cache=False) as fresh: command(run, fresh if resend else None)
def dry_run_sink(args: argparse.Namespace, run_dir: pathlib.Path) -> Result[Callable[[Mapping[str, Any]], None], ClientError]
    # writes each would-send request, redact_secrets'd, as one JSON line to --out or stdout;
    # --out inside run_dir: Err VALIDATION.INPUT (REQ-083)
def call_jev(run: Any, body: Mapping[str, Any]) -> Result[Reply, ClientError]
    # decidr_client.call_result(run, body, abort_on=frozenset({"auth"}), consent_what="The anchor statement and the item text")
def batch_verdict(job: decidr_client.BatchJob, settings: decidr_client.BatchSettings,
                  answers: Mapping[str, Any] | None) -> tuple[str | None, float | None, str | None]
    # (verdict, round(min_confidence, 3), leaning) from decide(answers, job.roles, settings.threshold, job.kind)
    # and decide(..., 0.0, job.kind)[0]; (None, None, None) when answers is None. decide() JJ:1710 unchanged.
def run_recorded_batch(run: Any | None, lines: list, settings: decidr_client.BatchSettings, fixture: Mapping[str, Any] | None,
                       log_path: pathlib.Path | None, *, echo: bool, question_sets: dict,
                       on_request: Callable[[Any], object] | None = None,
                       answers_out: dict[str, Mapping[str, Any]] | None = None) -> Result[decidr_client.StreamedResult, ClientError]
    # validate_request_lines -> batch_jobs -> decidr_client.run_batch(run, jobs, settings, on_line=..., fixture=fixture,
    #   on_request=on_request, abort_on=frozenset({"auth"}), verdict=batch_verdict, consent_what=...);
    # on_line appends encode_result_line(line) to log_path (None on dry run), echoes when echo, fills answers_out[request_id]
def read_batch_results(path: str) -> Result[list[dict], ClientError]                       # /2 only
def index_stream(raw_lines: list[dict], jobs: list[decidr_client.BatchJob],
                 answers: Mapping[str, Mapping[str, Any]]) -> Result[dict, ClientError]   # keyed by request_id
def assemble_run(ctx: dict, rec: dict, anchors_path: str, item: dict, results: list, run_id: str | None) -> dict   # schema plan-anchoring/run/2
def write_run(run: dict, path: pathlib.Path) -> str
def run_answers(run: dict) -> Result[dict[str, dict[str, Any]], ClientError]
    # report's read of a run/2 file's answers: decidr_client.answers_for([{"request_id": f"{anchor_id}#{i}", "session_id": s,
    #   "project": run["project"]} for each result's session_ids]); fixture runs: the file's own fixture answers (Rule-7 item 2)
def canonical_digest(value: Any) -> str      # sha256 of json.dumps(value, sort_keys=True, separators=(",", ":")); plan-anchor's tune-contract digest
```

Signature changes (no new names): `judge_context(args, rec, *, triage=False)` (drops `remote`), `ask_jev_once(args, run, body, questions, fixture, fixture_keys) -> Result[Reply, ClientError]`, `_first_answer(ctx, a, qs, body, fixture_key) -> Result[Reply, ClientError]`, `ask_triage(ctx, a, qs, deferred, item, fixture_key, entry) -> Result[None, ClientError]`, `judge_entries(ctx, prepared, item, fixture_key) -> Result[list, ClientError]`, `_rubric_judgement(args, run, fresh, body, qs, fixture, cid, threshold, lint_errors) -> Result[tuple[list[Reply], dict], ClientError]`, `batch_log_path(run_dir: str, run_name: str, run_id: str) -> Result[pathlib.Path, ClientError]`. `ctx["run"]`, `ctx["fresh"]` carry the Runs inside the judge family. `cmd_judge`, `cmd_check_fixtures`, `cmd_dedupe`, `cmd_rubric`, `cmd_add`, `cmd_batch`, `cmd_bead_batch`, `cmd_tournament` keep `(args) -> Result[dict, ClientError]` and call `with_run`.

Error ids: none new. `VALIDATION.INPUT` (dry-run `--out` inside `anchor-runs/`), `INPUT.MALFORMED` (a non-/2 result line, a non-run/2 run file), and the client's `AUTH.CREDENTIALS`, `POLICY.REMOTE_JUDGE_DISABLED`, `DEPENDENCY.SC_DECIDR`, `CANCELED` passed through.

## Replaces

| item | replaces (file:line) | deleted with it |
|---|---|---|
| import from decidr_client | JJ:118; S/anchor_tracker:92, anchor_tuning_contract:32, anchor_runner_contract:51, change_report:58, plan_anchor_settings:81 | S/result.py.j2 (110), T/test_result.py |
| `with_run` | per-call Run wiring in call_jev JJ:1655-1658 and _live_batch_results JJ:3294-3299; the 5 `remote_preflight` blocks JJ:1868-1871, :2433-2437, :2701-2705, :3346-3350, :4263-4267 (the client's gate decides) | `remote` param of judge_context; `ctx["live"]` |
| `dry_run_sink` | judge dry-run run file JJ:2045-2050, :2149-2151 (`requests`, `totals`); tournament `TOURNAMENT_DRY_RESULTS` JJ:3595, :4239-4246; dry-run lines from `run_batch_job` JJ:3172-3173 | dry-run run files and dry-run result lines (REQ-083) |
| `call_jev(run, body)` -> Reply | call_jev JJ:1653-1663 and judge_with_policy JJ:1666-1681 | judge_with_policy; meta `attempts`, `retry_after_ms`; the `{"model","answers","usage","attempts"}` dict |
| `fixture_response` body | JJ:1692-1698 (`fixture_attempt`, `usage`) | `usage` key |
| `batch_verdict` | `batch_result_fields` JJ:3192-3198 and `leaning_of` JJ:1781-1783 (its use JJ:2057 becomes `decide(..., 0.0, kind)[0]`) | dict-merge of verdict keys into the line |
| `run_recorded_batch` on `run_batch` | `run_batch_job` JJ:3170-3189, `_live_batch_results` JJ:3250-3306, the fixture loop JJ:3375-3395, `check_fixture_coverage` call JJ:3359-3361 | position bookkeeping, synthesized `attempts`, the AUTH/POLICY early return (now `abort_on`) |
| `batch_jobs` body | JJ:3159 `{"model": settings.model, ...}` | `model` in the body (the Run's) |
| `BatchSettings` 5 fields | JJ:4226-4227 9-arg construction; `batch_request_cap` JJ:2395-2397 | `model`, `timeout`, `max_workers`, request cap |
| `read_batch_results` /2 only | JJ:3243-3245 | `"plan-anchor/jev-batch-result/1"` (ANC-002, ANC-003) |
| `index_stream(..., answers)` | JJ:4023-4049 | request/`request_sha256`/`raw_response` integrity check JJ:4038-4045, `dry_run` check JJ:4035-4037 |
| `_history_event` evidence | JJ:4070-4072 | `canonical_request_sha256`, `raw_response_sha256` |
| `tournament_result` evidence | JJ:4121, :4151, :4155, :4181-4182 | `retries`, `models_answered`, `tool_calls`, `duration_ms`, `max_parallel_evaluators`; `time` import, `started` |
| `cmd_tournament` | JJ:4195-4196 worker cap; fixture answers via `answers_out`, `--results` answers via `decidr_client.answers_for` | `BATCH_MAX_WORKERS` use |
| `assemble_run` run/2 | JJ:2119-2152 | `model_answered`, `model_requested`, `requests`, `totals`; `run_id` from `stamp()` |
| result entries | JJ:2038, :2081-2082, :2089, :2094, :2725-2729, :2453/:2458 | `answers`, `answers_second`, `answers_third`, `usage`, `attempts`, `triage_attempts`; each entry gains `session_ids` |
| near-threshold resend on `ctx["fresh"]` | JJ:2061-2079 | the two `total_attempts` merges |
| rubric confirmations 2-3 on `fresh` | `_rubric_ask` JJ:2568-2575, `_rubric_judgement` JJ:2578-2605 | `attempts` accounting |
| `write_run(run, path)` | JJ:2155-2166 | collision loop |
| `run_answers` | `triage_lines` JJ:2838 reading `r["answers"]` | — |
| `canonical_digest` local | JJ:3110-3112 delegating to `decidr_client.questions_digest` (deleted in j-4) | — |
| `redact_secrets` | `BEARER_RE` JJ:180, `redact_sensitive` JJ:208-222 (uses at :226, :297, :3284, :3373, :3391, :3574) | both |
| CLI `--model/--timeout/--max-workers` default None | JJ:4304-4306, :4342, :4348, :4383-4384, :4449-4450, :4466-4467, :4551-4553 | `DEFAULT_MODEL` JJ:123, `getattr(..., DEFAULT_MODEL)` JJ:1833, timeout defaults JJ:1834, :1920 |
| `batch_log_path` by run_id | JJ:3310-3316 | `stamp()` JJ:237-238 |
| change_report run/2 | S/change_report.py.j2:405 glob reads any `{gate}-*.json` | non-run/2 files are skipped by schema, never parsed further |

New capability (counted separately): `add --dry-run` (REQ-083 names every `--dry-run`; `add --rubric` sends today with no dry run); the `cache=False` second Run (Rule-7 item 1).

## External contracts (examples)

/2 line (stdout, `anchor-runs/tournament-<run_id>.jsonl`, `<out>/results.jsonl`):
```json
{"schema":"jev-batch-result/2","tool":"plan-anchor","tool_version":"0.14.0","run_id":"01KC8Z...","session_id":"01KC8Z...","request_id":"plan/I-1/ANC-001/c1/r1","project":"phase-j","agent_role":"plan-anchor","threshold":0.6,"verdict":"pass","min_confidence":0.82,"leaning":"satisfied","ok":true,"error":null}
```
Run file `anchor-runs/<gate>-<run_id>.json` (check-fixtures: `<gate>-<run_id>-<item>.json`):
```json
{"schema":"plan-anchoring/run/2","run_id":"01KC8Z...","gate":"plan","project":"phase-j","created_at":"2026-11-26T10:00:00+00:00","item":{"id":"I-1","chars":812},"threshold":0.6,"fixture":false,
 "results":[{"anchor_id":"ANC-001","verdict":"satisfied","min_confidence":0.82,"leaning":"satisfied","session_ids":["01KC8Z...","01KC90..."],"confirmed":true}],"summary":{"pass":true}}
```
Tournament evidence in `result_vars.json` / history event: `"evidence":{"session_ids":["01KC..."],"run_ids":["01KC..."]}`.
CLI: `jev_judge.py judge --anchors A --item-id I-1 [--model haiku|luna|jev] [--dry-run [--out F]]`; `add ... --rubric --dry-run`; no flag has a model, timeout or worker default. Log: `~/.sc-agent/logs/plan-anchor.log.jsonl` (wheel default; `PLAN_ANCHOR_LOG_ROOT` overrides). Consent: `.sc/plan-anchor/settings.yaml` `allow_remote_judge`, read by the client only for a TypeSafe Run.

## Deletions (file:line at cee4dc1)

S/result.py.j2 (all); JJ:107 `hashlib` stays (canonical_digest, intent sha); JJ:114 `time`; JJ:123; JJ:180; JJ:208-222; JJ:237-238; JJ:1666-1681; JJ:1781-1783; JJ:1868-1871; JJ:2061-2079 attempts lines; JJ:2149-2151; JJ:2157-2161; JJ:2395-2397; JJ:2433-2437; JJ:2581-2601 attempts lines; JJ:2701-2705; JJ:3170-3198; JJ:3244; JJ:3250-3306; JJ:3346-3350; JJ:3375-3395; JJ:3595; JJ:4035-4045; JJ:4071; JJ:4121, :4151, :4155, :4181-4182; JJ:4195-4196; JJ:4239-4246; JJ:4263-4267; assets/schemas/jev-batch-result.schema.json; T/test_result.py; T/sc_decidr_test_double.py and the tests that assert /1 keys, `attempts`, `retry_count`, old run-file names or the request-integrity check (ANC-003: code and tests together).

## Done checks

- Build: `sc-compose render` of `consumer.py.j2` into S/decidr_client.py.j2 matches the j-4 prerelease byte for byte; `python3 scripts/check_version_sync.py`; installer renders all templates.
- Greps (empty): the Goal grep; `grep -rn 'jev-batch-result/1\|plan-anchoring/run/1' plugins tests`; `grep -rn 'general_log\|seams=' plugins` (tests only, ANC-016).
- T/test_run_scoped.py::RunScopedCommandTests (sc_agent.testing.fake_open_run; deterministic, no sleep/threads/key/HOME): `test_each_live_command_opens_one_run` (8 commands), `test_confirming_commands_open_one_fresh_run_with_cache_false` (judge, check-fixtures, rubric, add --rubric), `test_model_timeout_workers_pass_through_unchanged` (haiku, luna, jev, None), `test_dry_run_and_fixture_import_no_wheel_and_send_nothing` (`sys.modules["sc_agent"] = None`), `test_dry_run_writes_nothing_under_anchor_runs`, `test_dry_run_out_inside_anchor_runs_is_refused`, `test_open_run_err_sends_nothing`, `test_auth_error_aborts_remaining_jobs`, `test_run_file_named_by_run_id_with_session_ids_and_no_answers`, `test_batch_lines_equal_wheel_schema_keys` (schema via importlib.resources), `test_batch_verdict_fills_three_fields`, `test_redaction_uses_client_redact_secrets`.
- T/test_tournament.py: `test_rescore_reads_answers_by_session_id` (`--results`, fake session_rows), `test_fixture_tournament_scores_in_memory_answers`, `test_history_evidence_names_session_ids`, `test_v1_stream_is_refused`.
- T/test_change_report.py: `test_report_reads_run2_answers_from_session_rows`, `test_non_run2_files_skipped`.
- Whole suite: `python3 -m pytest tests/sc-plan-anchor -q` green; tests/integration against the j-4 prerelease wheel: haiku and luna with `TYPESAFE_API_KEY` unset.

## Budget

Rust: 0 (phase total unchanged by j-5). Python production (S/*.j2 minus the generated decidr_client.py.j2), rough: deletions about -520 (result.py.j2 110, jev_judge about 410 per Deletions), restructure additions about +120 (with_run, dry_run_sink, run_recorded_batch body, run_answers, run/2 entries, signature edits), restructure net about -400 (<= 0). New capability about +8 (`add --dry-run`, fresh Run). decidr_client.py.j2 is regenerated (653 -> about 700, j-4's count, not plan-anchor's).

## Plan decisions (no question to Rand)

1. Fixture and dry runs open no Run and import no wheel: REQ-016 and REQ-047 (an `--answers-file` run is standard-library-only) govern; j-4's `run_batch(None, ..., fixture=)` gives `run_id`/`session_id` null. The old prose plan's "fixture through a real Run" came from the lead-sourced text already deleted from REQ-016.
2. Run files keep the `<gate>-` prefix so change_report's glob stays; uniqueness is the ULID, so the collision loop goes.
3. Record conflicts with ANC-015 to delete on develop (listed, not edited here): REQ-047's sentence on when `decidr_client.py` may import `sc_agent` (a cross-tool client rule); REQ-085's `cache=False` mechanics restate the wheel's cache rule.

## Rule-7 items

1. Per-send cache bypass. Check: REQ-076 and REQ-085 require the confirming/rubric resends with `cache=False`; j-3 plan `RunArgs.cache: Option<bool>` is Run-level only (no per-send override), though j1-bead NOTES (Lead 2026-11-24) asked for a per-call `cache=` kwarg. Proposed: open a second `cache=False` Run for those commands (0 Rust, this plan); alternative: `cache=` on `Run.send`/`send_batch` and `call_result` (+~4 Rust in j-3/j-4).
2. Fixture run answers. Check: REQ-013 "A run file shall not contain Jev's answers"; a fixture run has no session rows, so `report` on it could show no triage answers. Proposed: fixture run files keep the fixture answers (they are not Jev's), under `fixture_answers`.
