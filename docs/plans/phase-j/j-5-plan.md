# j-5 plan: plan-anchor on the j-4 client

Base (one, for code and records): plan-anchor `origin/plan/phase-j` @ cee4dc1, which carries the phase-j record trim (#158). `sprint/j-5` branches from it; the PR targets `integrate/phase-j` (7cff34f) and so brings cee4dc1's records and code with it; every REQ/ADR and line cited here is read at cee4dc1, not at 7cff34f. `JJ:N` = `plugins/sc-plan-anchor/install/templates/skills/plan-anchoring/scripts/jev_judge.py.j2` at that commit (4,625 lines); `S/` = that `scripts/` folder; `T/` = `tests/sc-plan-anchor/`. The upstream plans cite JJ by older line numbers (`leaning_of` :1913, :2222, :2247, `decide` :1842); at cee4dc1 they are :1781, :2057, :3198 and :1710. Client API = sc-agent `origin/sprint/j-4:docs/plans/phase-j/j-4-plan.md` (rendered `consumer.py.j2` 2.0.0, here `S/decidr_client.py.j2`). Record ids are those on `plan/phase-j` (PR #159, which renames them to REQ-PA-/ADR-PA-, is open and not cited). Written by reading the code; no j-5 code yet.

## Goal

Rand (ANC-015, ANC-016, rule 0): "judge-jev and plan-anchor simply supply tool name and follow the rules established for all decidr based tools"; "derivative tools should defer to the default tool rules and not use injection path for production code (test only)". Measurable: plan-anchor sends only through the rendered j-4 client on one `open_run(...)` per live command, with required resends passing `cache=False` on the call (upstream dependency: j-3/j-4 add per-call `cache=`); `batch`, `bead-batch`, `tournament` write `jev-batch-result/2` lines only; run files hold `session_ids`, not answers (REQ-013, REQ-086); and these greps over `S/*.j2` minus `decidr_client.py.j2` are empty: `from result |redact_sensitive|BEARER_RE|DEFAULT_MODEL|remote_preflight|total_attempts|fixture_attempt|questions_digest|BATCH_MAX_WORKERS|retry_count|model_answered|raw_response|jev-batch-result/1|stamp\(|general_log`.

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

## Deliverables
1. J5-S01: Import Result types from decidr_client; delete result.py.j2
2. J5-S02: with_run: one Run per live command
3. J5-S03: dry_run_sink: dry runs write requests only to --out or stdout
4. J5-S04: call_jev on the Run returning Reply; per-call cache for resends
5. J5-S05: batch_verdict: typed verdict callback for run_batch
6. J5-S06: run_recorded_batch on decidr_client.run_batch
7. J5-S07: read_batch_results /2 only
8. J5-S08: index_stream keyed by request_id with answers by session
9. J5-S09: Run file run/2 named by run_id with session_ids
10. J5-S10: run_answers: report reads answers from session rows
11. J5-S11: canonical_digest local
12. J5-S12: Redaction via decidr_client.redact_secrets
13. J5-S13: CLI model/timeout/workers pass-through, no defaults
14. J5-S14: add --dry-run

Exact code for each: the dev bead agt-j-5.group-dev Signatures and design "Public surface".

## Does Not Close
- Hosted CI install from PyPI (red until sc-decidr is published; suites run against the prerelease).
- The HOME writes in `test_installer_skill.py` (agt-li2k).
- Phase 2 run start/end records and Phase 3 SQLite tables.
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
             command: Callable[[Any], Result[dict, ClientError]]) -> Result[dict, ClientError]
    # dry run: command(None); no Run, the wheel is never imported (REQ-047, REQ-083).
    # live and --answers-file: with decidr_client.open_run(model=args.model, project=args.project, timeout_secs=args.timeout,
    #                                   workers=args.max_workers) as run: command(run)  (Err -> returned, nothing sent);
    #   a fixture run sends nothing (answers come from the file, run_batch(run, fixture=)), zero network calls (REQ-016),
    #   and writes its run file and lines like a live run with run.run_id, session_id null (same as j-6)
def dry_run_sink(args: argparse.Namespace, run_dir: pathlib.Path) -> Result[Callable[[Mapping[str, Any]], None], ClientError]
    # writes each would-send request, redact_secrets'd, as one JSON line to --out or stdout;
    # --out inside run_dir: Err VALIDATION.INPUT (REQ-083)
def call_jev(run: Any, body: Mapping[str, Any], *, cache: bool | None = None) -> Result[Reply, ClientError]
    # decidr_client.call_result(run, body, cache=cache, abort_on=frozenset({"auth"}), consent_what="The anchor statement and the item text")
def batch_verdict(job: decidr_client.BatchJob, settings: decidr_client.BatchSettings,
                  answers: Mapping[str, Any] | None) -> tuple[str | None, float | None, str | None]
    # (verdict, round(min_confidence, 3), leaning) from decide(answers, job.roles, settings.threshold, job.kind)
    # and decide(..., 0.0, job.kind)[0]; (None, None, None) when answers is None. decide() JJ:1710 unchanged.
def run_recorded_batch(run: Any | None, lines: list, settings: decidr_client.BatchSettings, fixture: Mapping[str, Any] | None,
                       log_path: pathlib.Path | None, *, echo: bool, question_sets: dict,
                       on_request: Callable[[Any], object] | None = None,
                       answers_out: dict[str, Mapping[str, Any]] | None = None) -> Result[decidr_client.StreamedResult, ClientError]
    # validate_request_lines -> batch_jobs -> decidr_client.run_batch(run, jobs, settings, on_line=..., fixture=fixture,
    #   on_request=on_request, abort_on=frozenset({"auth"}), verdict=batch_verdict, consent_what=...,
    #   cache=None)  (repeats > 1 are uncached inside j-4 run_batch; not restated here, ANC-015);
    # on_line appends encode_result_line(line) to log_path (None on dry run), echoes when echo, fills answers_out[request_id]
def read_batch_results(path: str) -> Result[list[dict], ClientError]                       # /2 only
def index_stream(raw_lines: list[dict], jobs: list[decidr_client.BatchJob],
                 answers: Mapping[str, Mapping[str, Any]]) -> Result[dict, ClientError]   # keyed by request_id
def assemble_run(ctx: dict, rec: dict, anchors_path: str, item: dict, results: list, run_id: str | None) -> dict   # schema plan-anchoring/run/2
def write_run(run: dict, path: pathlib.Path) -> str
def run_answers(run: dict) -> Result[dict[str, dict[str, Any]], ClientError]
    # report's read of a run/2 file's answers: decidr_client.answers_for([{"request_id": f"{anchor_id}#{i}", "session_id": s,
    #   "project": run["project"]} for each result's session_ids]); fixture runs: the file's own `fixture_answers`
def canonical_digest(value: Any) -> str      # sha256 of json.dumps(value, sort_keys=True, separators=(",", ":")); plan-anchor's tune-contract digest
```

Signature changes (no new names): `judge_context(args, rec, *, triage=False)` (drops `remote`), `ask_jev_once(args, run, body, questions, fixture, fixture_keys) -> Result[Reply, ClientError]`, `_first_answer(ctx, a, qs, body, fixture_key) -> Result[Reply, ClientError]`, `ask_triage(ctx, a, qs, deferred, item, fixture_key, entry) -> Result[None, ClientError]`, `judge_entries(ctx, prepared, item, fixture_key) -> Result[list, ClientError]`, `_rubric_judgement(args, run, body, qs, fixture, cid, threshold, lint_errors) -> Result[tuple[list[Reply], dict], ClientError]`, `batch_log_path(run_dir: str, run_name: str, run_id: str) -> Result[pathlib.Path, ClientError]`. `ctx["run"]` carries the Run inside the judge family. `cmd_judge`, `cmd_check_fixtures`, `cmd_dedupe`, `cmd_rubric`, `cmd_add`, `cmd_batch`, `cmd_bead_batch`, `cmd_tournament` keep `(args) -> Result[dict, ClientError]` and call `with_run`.

Error ids: none new. `VALIDATION.INPUT` (dry-run `--out` inside `anchor-runs/`), `INPUT.MALFORMED` (a non-/2 result line, a non-run/2 run file), and the client's `AUTH.CREDENTIALS`, `POLICY.REMOTE_JUDGE_DISABLED`, `DEPENDENCY.SC_DECIDR`, `CANCELED` passed through.

## Replaces

| item | replaces (file:line) | deleted with it |
|---|---|---|
| import from decidr_client | JJ:118; S/anchor_tracker:92, anchor_tuning_contract:32, anchor_runner_contract:51, change_report:58, plan_anchor_settings:81 | S/result.py.j2 (110), T/test_result.py |
| `with_run` | per-call Run wiring in call_jev JJ:1655-1658 and _live_batch_results JJ:3294-3299; the 5 `remote_preflight` blocks JJ:1868-1871, :2433-2437, :2701-2705, :3346-3350, :4263-4267 (the client's gate decides) | `remote` param of judge_context; `ctx["live"]` |
| `dry_run_sink` | judge dry-run run file JJ:2045-2050, :2149-2151 (`requests`, `totals`); tournament `TOURNAMENT_DRY_RESULTS` JJ:3595, :4239-4246; dry-run lines from `run_batch_job` JJ:3172-3173 | dry-run run files and dry-run result lines (REQ-083) |
| `call_jev(run, body)` -> Reply | call_jev JJ:1653-1663 and judge_with_policy JJ:1666-1681 (at cee4dc1 it sends once and applies no size limit: the cap, halving and PLAN.TOO_LARGE went in the record trim 4d0c22f; REQ-008 'send a bead whole' holds because call_jev sends the body unchanged; REQ-077 is not on the base) | judge_with_policy; meta `attempts`, `retry_after_ms`; the `{"model","answers","usage","attempts"}` dict |
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
| result entries | JJ:2038, :2081-2082, :2089, :2094, :2725-2729, :2453/:2458 | `answers`, `answers_second`, `answers_third`, `usage`, `attempts`, `triage_attempts`; each entry gains `session_ids`: `Reply.session_id` of every answered send and `err.data.get("session_id")` of every failed send that has one (a failed batch job keeps `line.session_id`) |
| near-threshold resend `call_jev(..., cache=False)` | JJ:2061-2079 | the two `total_attempts` merges |
| rubric confirmations 2-3 `cache=False` | `_rubric_ask` JJ:2568-2575, `_rubric_judgement` JJ:2578-2605 | `attempts` accounting |
| `write_run(run, path)` | JJ:2155-2166 | collision loop |
| `run_answers` | `triage_lines` JJ:2838 reading `r["answers"]` | — |
| `canonical_digest` local | JJ:3110-3112 delegating to `decidr_client.questions_digest` (deleted in j-4) | — |
| `redact_secrets` | `BEARER_RE` JJ:180, `redact_sensitive` JJ:208-222 (uses at :226, :297, :3284, :3373, :3391, :3574) | both |
| CLI `--model/--timeout/--max-workers` default None | JJ:4304-4306, :4342, :4348, :4383-4384, :4449-4450, :4466-4467, :4551-4553 | `DEFAULT_MODEL` JJ:123, `getattr(..., DEFAULT_MODEL)` JJ:1833, timeout defaults JJ:1834, :1920 |
| `batch_log_path` by run_id | JJ:3310-3316 | `stamp()` JJ:237-238 |
| `collect_runs` reads run/2 | JJ:2921-2934 | the `dry_run` skip JJ:2931 and its test (test_jev_judge.py:1483 'dry runs never count'); dry runs write no run file (REQ-083), skipping old ones is back-compat (ANC-002, ANC-003; owner ruling, REQ-PA-0010 skip statement deleted on develop #159) |
| change_report run/2 | S/change_report.py.j2:405 glob reads any `{gate}-*.json` | the `dry_run` skip at :410 and its test assertion (test_change_report.py:274); no skip of non-run/2 files (no back-compat until SQLite 1.0, ANC-002) |

New capability (counted separately): `add --dry-run` (REQ-083 names every `--dry-run`; `add --rubric` sends today with no dry run).

Upstream dependency: j-3 adds a per-call `cache=` override on `Run.send`/`send_batch`; j-4 adds `cache: bool | None = None` to `call_result(...)` and `run_batch(...)` and drops `open_run(repeat=)` (about +4 Rust, planned there, not here). plan-anchor uses only the per-call flag: one cache mechanism. Lead decision 2026-11-26 (rule 0).

Redaction (REQ-083, REQ-047): live and fixture runs have the wheel, so `decidr_client.redact_secrets` removes provider-key values and bearer tokens. A dry run imports no wheel; `redact_secrets` then removes bearer tokens only (upstream dependency: j-4 `redact_secrets` skips provider keys when `load_wheel()` is `Err`).

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

## Plan decisions (no question to Rand)

1. Fixture runs open a real Run and send nothing (aligned with j-6); dry runs open no Run and import no wheel. The earlier "fixture runs open no Run" was lead advice, removed by the owner correction of 2026-11-26.
2. Run files keep the `<gate>-` prefix so change_report's glob stays; uniqueness is the ULID, so the collision loop goes.
3. Record conflicts to delete on develop (listed, not edited here): REQ-047 ', an `--answers-file` run included,' (fixture runs now use the wheel; J-5-13); ADR-006 'scripts/result.py: frozen Ok/Err dataclasses ...' and 'share result.py' and ADR-015 '(result.py, plan_anchor_paths.py)' name the deleted module (J-5-10; the design stands: Result types come from the generated decidr_client.py). With ANC-015: REQ-047's sentence on when `decidr_client.py` may import `sc_agent` (a cross-tool client rule); REQ-085's `cache=False` mechanics restate the wheel's cache rule.

## Lead decisions (2026-11-26, rule 0)

1. Per-send cache: resends pass `cache=False` on the call for judge, check-fixtures, rubric, add --rubric; the per-call `cache=` is j-3/j-4's work (upstream dependency). No second Run.
2. Fixture run files carry `fixture_answers` (not Jev's answers; REQ-013 untouched).
## Done checks

- Build: `sc-compose render` of `consumer.py.j2` into S/decidr_client.py.j2 matches the j-4 prerelease byte for byte; `python3 scripts/check_version_sync.py`; installer renders all templates.
- Greps (empty): the Goal grep; `grep -rn 'jev-batch-result/1\|plan-anchoring/run/1' plugins` (empty), and `grep -rln 'jev-batch-result/1' tests` lists only T/test_tournament.py (test_v1_stream_is_refused); `grep -rn 'general_log\|seams=' plugins` (tests only, ANC-016).
- T/test_run_scoped.py::RunScopedCommandTests (sc_agent.testing.fake_open_run; deterministic, no sleep/threads/key/HOME): `test_each_live_command_opens_one_run` (8 commands), `test_intentional_resends_pass_cache_false_per_call` (judge, check-fixtures, rubric, add --rubric; one Run each), `test_model_timeout_workers_pass_through_unchanged` (haiku, luna, jev, None), `test_dry_run_imports_no_wheel_and_sends_nothing` (`sys.modules["sc_agent"] = None`), `test_fixture_run_opens_a_run_sends_nothing_and_writes_like_live`, `test_failed_send_session_id_recorded`, `test_dry_run_redacts_bearer_without_wheel`, `test_dry_run_writes_nothing_under_anchor_runs`, `test_dry_run_out_inside_anchor_runs_is_refused`, `test_open_run_err_sends_nothing`, `test_auth_error_aborts_remaining_jobs`, `test_run_file_named_by_run_id_with_session_ids_and_no_answers`, `test_batch_lines_equal_wheel_schema_keys` (schema via importlib.resources), `test_batch_verdict_fills_three_fields`, `test_redaction_uses_client_redact_secrets`.
- T/test_tournament.py: `test_rescore_reads_answers_by_session_id` (`--results`, fake session_rows), `test_fixture_tournament_scores_in_memory_answers`, `test_history_evidence_names_session_ids`, `test_v1_stream_is_refused`.
- T/test_change_report.py: `test_report_reads_run2_answers_from_session_rows`.
- Whole suite: `python3 -m pytest tests/sc-plan-anchor -q` green; tests/integration against the j-4 prerelease wheel: haiku and luna with `TYPESAFE_API_KEY` unset.
- coverage skips nothing because dry runs write no run file

## Budget

Rust: 0 (phase total unchanged by j-5). Python production (S/*.j2 minus the generated decidr_client.py.j2), rough: deletions about -520 (result.py.j2 110, jev_judge about 410 per Deletions), restructure additions about +120 (with_run, dry_run_sink, run_recorded_batch body, run_answers, run/2 entries, signature edits), restructure net about -400 (<= 0). New capability about +3 (`add --dry-run`). decidr_client.py.j2 is regenerated (653 -> about 700, j-4's count, not plan-anchor's).
Plan-qa-4 findings applied: J-5-01, 06, 07, 08, 09, 10, 12, 13. J-5-05 closed: owner ruling (REQ-PA-0010 skip statement deleted, #159) - dry runs write no run file; the skip is back-compat (ANC-002/003) and is deleted with its test. The beads (agt-j-5, agt-j-5.group-dev) are the plan; this file mirrors them.
