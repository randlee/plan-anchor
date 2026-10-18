# sc-plan-anchor requirements

Requirements for the `plan-anchoring` skill in `plugins/sc-plan-anchor/`. Each
entry is derived from an existing source; nothing here is new scope.

- **Source** cites an anchor in [`plans/phase-a/anchors.json`](plans/phase-a/anchors.json)
  (`ANC-NNN`), the [Phase A intent](plans/phase-a/intent.md) (`INTENT`), a
  document, or an operator decision (`OPERATOR`). Retired anchors are cited only
  where their retirement reason says the requirement itself remains.
- **Status** describes the system at the top of the 0.7.0 stack: `shipped`
  (built there) or `planned` (decided, not built there).
- **Verified** names the test that exercises the requirement, as
  `file::Class.test`, with files under `tests/sc-plan-anchor/`; a bare
  `Class.test` is in the file named just before it. `none` means no test was
  found; `partial` says what the test does not cover.

Architecture decisions are in [architecture.md](architecture.md); component and
call-graph detail is in [design/architecture-and-call-graphs.md](design/architecture-and-call-graphs.md)
and [design/data-model-and-gating.md](design/data-model-and-gating.md).

## Anchors and records

**REQ-001** The skill shall store every anchor in `anchors.json` with an immutable verbatim `quote` and a separately authored, user-approved testable `statement`.
Source: PRD "Provenance & reporting"; `design/data-model-and-gating.md` §2. Status: shipped.
Verified: `test_jev_judge.py::QuoteTests.test_anc_requires_a_quote`, `QuoteTests.test_statement_equal_to_quote_is_refused`, `RetireUpdateTests.test_update_fields_and_fixtures`.

**REQ-002** The script shall allocate `ANC-NNN` IDs as max plus one, never reuse them, and keep register IDs for REQ and ADR anchors.
Source: `design/data-model-and-gating.md` §2. Status: shipped.
Verified: `test_jev_judge.py::AddTests.test_next_anc_id_allocation`, `AddTests.test_register_anchors_keep_their_id_and_refuse_duplicates`.

**REQ-003** Only `locked` and `promoted` anchors shall be judged by `--all`, and an explicit `--anchor` on a proposed or retired anchor shall be refused.
Source: `design/data-model-and-gating.md` §6. Status: shipped.
Verified: `test_jev_judge.py::JudgeFixtureTests.test_explicit_anchor_must_be_locked_unless_included`, `JudgeFixtureTests.test_all_skips_proposed_and_requires_some_anchor`.

**REQ-004** Nothing shall be locked without user confirmation, and a statement shall pass the lint, the testability rubric and the duplicate check before `add` accepts it.
Source: SKILL.md "Design positions" (Capture); `references/anchor-capture.md`. Status: shipped.
Verified: partial: `test_jev_judge.py::LintTests.test_add_reports_warnings_and_strict_refuses`, `RubricTests.test_add_rubric_gate`, `DedupeTests.test_add_refuses_duplicate_candidates_unless_allowed`. User confirmation is a skill instruction with no test.

**REQ-005** `anchors.md` shall be rendered from `anchors.json` and never hand-edited.
Source: `design/data-model-and-gating.md` §1. Status: shipped.
Verified: `test_jev_judge.py::QuoteTests.test_shipped_example_record_is_valid_lint_clean_and_renders`.

**REQ-006** An anchor shall be able to carry an `exclude` list of `{item, reason}` entries; `judge` shall skip each listed cell without calling Jev, report it as `excluded` (passing) with its reason in the run summary, report, coverage, diff and `anchors.md`, with no approval workflow and no other new verdict state.
Source: OPERATOR; `design/anchor-tuning-stand-ins.md` "Anchor exclusions"; ADR-012. Status: shipped.
Verified: `test_jev_judge_exclude.py::JudgeExclusionTests.test_excluded_cell_makes_no_transport_call_and_passes`, `JudgeExclusionTests.test_only_the_excluded_cell_is_skipped`, `JudgeExclusionTests.test_planted_negative_other_item_or_near_miss_is_judged`, `OutputTests.test_report_always_shows_the_exclusion_reason`, `OutputTests.test_coverage_lists_excluded_cells_with_reasons`, `OutputTests.test_diff_carries_the_exclusion`, `OutputTests.test_render_lists_exclusions_under_the_anchor`, `SchemaTests.test_empty_reason_is_rejected`, `ExcludeCommandTests.test_exclude_on_a_locked_anchor_keeps_version_and_records_history`.

## Jev requests and gating

**REQ-007** Each Jev request shall contain exactly `state.anchor {id, statement, scope}`, `state.item {id, title, text}`, and the gate's question set, and shall not contain intent, source metadata, or a second anchor or item.
Source: OPERATOR; PRD "Keep the state small"; `design/data-model-and-gating.md` §3. Status: shipped.
Verified: partial: `test_jev_judge.py::QuoteTests.test_run_results_carry_the_quote` (asserts `state.anchor` exactly), `test_gate_prompts.py::FreeFormSprintDryRunTests.test_free_form_sprint_builds_a_request_at_both_gates` (asserts `state.item` exactly). No test asserts that `state` has no other keys.

**REQ-008** The planning gate shall send a bead whole when it fits 24,000 request bytes, never shorten prose, reduce only the longest eligible fenced code blocks to signatures when it does not fit, and refuse with `PLAN.TOO_LARGE` before sending when it still does not fit.
Source: OPERATOR; `experiments/2026-10-10-redact-only-when-oversize.md`. Status: shipped.
Verified: `test_jev_judge.py::PlanSizeTests.test_plan_gate_sends_a_fitting_bead_whole`, `PlanSizeTests.test_oversize_plan_bead_reduces_only_its_longest_blocks`, `PlanSizeTests.test_oversize_plan_bead_is_refused_and_nothing_is_sent`, `PlanSizeTests.test_plan_gate_context_overflow_is_too_large_not_halved`, `RequestBytesDefaultTests.test_default_depends_on_the_gate_and_the_flag_overrides`.

**REQ-009** The script shall turn independent answers into one verdict in code, first match wins: relevance `no` at confidence ≥ 0.6 is `not_applicable`; a lower-confidence relevance `no` falls through and ends as `underspecified`; then `contradicted`, `underspecified`, `not_addressed`, `asserted_only`, `satisfied`.
Source: OPERATOR; `design/data-model-and-gating.md` §4. Status: shipped.
Verified: `test_jev_judge.py::DecideTests` (all rows, including `test_row1_not_applicable` and `test_threshold_boundaries`).

**REQ-010** Coverage across items and run-to-run differences shall be computed by the script from run files, never asked of Jev.
Source: PRD "Do the counting in code"; `design/data-model-and-gating.md` §5. Status: shipped.
Verified: `test_jev_judge.py::CoverageTests.test_uncovered_latest_wins_and_dry_runs_ignored`, `DiffTests`.

**REQ-011** The script alone shall own the retry policy: up to three attempts for 429, 529, 5xx, network and invalid responses, no retry on 401, and an error on one anchor shall not lose the others.
Source: `design/architecture-and-call-graphs.md` §4. Status: shipped.
Verified: `test_jev_judge.py::TransportPolicyTests`.

**REQ-012** Every Jev answer shall be checked by `validate_response`, which requires exactly the requested answer IDs.
Source: `design/architecture-and-call-graphs.md` §4. Status: shipped.
Verified: `test_jev_judge.py::ResponseValidationTests.test_validate_response_requires_exact_answer_ids`.

**REQ-013** Each run shall be written to its own run file that copies the statement, quote and provenance it judged.
Source: `design/data-model-and-gating.md` §1–2. Status: shipped.
Verified: `test_jev_judge.py::QuoteTests.test_run_results_carry_the_quote`, `JudgeFixtureTests.test_run_file_names_are_sanitised_and_never_collide`.

**REQ-014** A failing report shall name the anchor and show its statement next to the user's verbatim quote.
Source: PRD "Provenance & reporting". Status: shipped.
Verified: `test_jev_judge.py::ReportTests.test_line_format_quotes_the_statement`.

## Data leaving the machine and configuration

**REQ-015** Live Jev calls shall fail closed without a TypeSafe API key and an explicit remote-judge opt-in, and send nothing in that case.
Source: PRD "Jev data handling"; `design/architecture-and-call-graphs.md` §6. Status: shipped.
Verified: `test_jev_judge.py::FailClosedTests.test_missing_key_and_missing_opt_in` (asserts zero transport calls).

**REQ-016** `--dry-run` and `--answers-file` execution shall make zero network calls.
Source: INTENT "Success"; retired ANC-006 (requirement retained). Status: shipped.
Verified: partial: `test_jev_judge.py::FailClosedTests.test_fixture_and_dry_run_need_neither` runs both modes with no key and exits 0, and `JudgeFixtureTests.test_dry_run_writes_requests_and_totals_and_exits_zero` checks zero attempts; neither asserts that the transport stub received no body.

**REQ-017** Script output shall redact the exact TypeSafe API-key value and bearer tokens from every emitted value and never write them to a run file.
Source: ANC-012. Status: shipped.
Verified: `test_jev_judge.py::FailClosedTests.test_every_emitted_value_redacts_the_live_key_and_bearer_tokens`, `FailClosedTests.test_key_format_checked_and_never_echoed`, `test_anchor_runner_contract.py::RunnerContractTests.test_attestation_is_redacted_and_atomic_failures_are_typed`.

**REQ-018** Plan-anchor shall not read runtime configuration from environment variables other than `TYPESAFE_API_KEY`.
Source: ANC-005; INTENT "Success". Status: shipped (not met; see note).
Verified: none. Note: `jev_judge.py` reads `PLAN_ANCHOR_ALLOW_REMOTE_JUDGE`, `PLAN_ANCHOR_JEV_URL`, `PLAN_ANCHOR_JEV_MODEL`, `PLAN_ANCHOR_CONFIDENCE_THRESHOLD`, `PLAN_ANCHOR_CONFIRM_NEAR`, `PLAN_ANCHOR_MAX_ITEM_CHARS` and `PLAN_ANCHOR_MAX_CODE_LINES`, and `test_jev_judge.py::ErrorHandlingTests.test_env_numbers_are_checked` exercises them. ADR-016 (REQ-065) removes `PLAN_ANCHOR_ALLOW_REMOTE_JUDGE`; the rest remain.

**REQ-019** Repository settings shall live in `.sc/plan-anchor/settings.yaml`: YAML with snake_case keys, committed, no secrets, `schema_version: 1`, and strict validation that rejects unknown keys, duplicate keys and wrong types.
Source: OPERATOR. Status: shipped.
Verified: `test_anchor_tracker.py::MalformedInputTests` (`test_unknown_keys_are_rejected`, `test_schema_version_must_be_integer_one`, `test_tracker_value_must_be_bd_or_br`), `RepositoryContractTests.test_settings_file_is_not_gitignored`, `WriteAndInitTests.test_write_produces_committed_format`.

**REQ-020** Settings shall gain a `fast_agents.profiles` list of `{name, tool, model, timeout_seconds}` under the same strict validation.
Source: OPERATOR; `design/anchor-tuning-stand-ins.md` "Configuration". Status: planned (strict validation rejects the key).
Verified: none.

## Trackers

**REQ-021** Anchor and question storage, and both gates, shall work with either `br` or `bd`.
Source: OPERATOR; INTENT "Success"; retired ANC-007 (requirement retained). Status: shipped.
Verified: `test_anchor_tracker.py::SelectionRuleTests`, `test_gate_prompts.py::GatePromptTests.test_both_gates_resolve_the_tracker_for_question_beads`, `test_tracker_prompt_regressions.py::TrackerPromptRegressionTests.test_development_gate_resolves_tracker_and_takes_caller_text`, `test_install.py::RenderingTests.test_both_gates_render_the_selected_tracker`.

**REQ-022** Tracker selection shall be: an explicit `anchor_tracker` in the committed settings wins and is validated against disk; otherwise a Dolt-backed `.beads/` selects `bd`, any other `.beads/` selects `br`, and no `.beads/` selects `br`; a mismatch is an error, never a silent switch.
Source: OPERATOR. Status: shipped.
Verified: `test_anchor_tracker.py::SelectionRuleTests` (all), `SelectionRuleTests.test_selection_never_switches_to_the_other_cli`.

**REQ-023** The skill and the installer shall never run or recommend `bd init`; `br init` is the only bootstrap and runs only on `anchor_tracker.py write --init` or `install.py --init-br`, with fixed argv and no shell.
Source: OPERATOR. Status: shipped.
Verified: `test_anchor_tracker.py::WriteAndInitTests.test_bd_is_never_initialized`, `WriteAndInitTests.test_init_runs_br_init_with_fixed_argv_and_no_shell`, `test_tracker_prompt_regressions.py::TrackerPromptRegressionTests.test_no_text_recommends_bd_init`, `TrackerPromptRegressionTests.test_tracker_script_never_builds_a_bd_init_argv`, `test_install.py::InstallTests.test_bd_refused_without_dolt`, `InstallTests.test_no_beads_without_init_flag_is_typed_error`.

**REQ-024** The plan-anchor repository itself shall pin `anchor_tracker: br`.
Source: OPERATOR. Status: shipped.
Verified: `test_anchor_tracker.py::RepositoryContractTests.test_this_repository_pins_br`.

**REQ-025** Both gate reviewers shall take the tracker from `anchor_tracker.py resolve`, never from a default, and reject a mismatch with a supplied value.
Source: OPERATOR; SKILL.md Step 1. Status: shipped.
Verified: `test_tracker_prompt_regressions.py::TrackerPromptRegressionTests.test_planning_gate_obtains_tracker_from_resolve`, `TrackerPromptRegressionTests.test_development_gate_resolves_tracker_and_takes_caller_text`, `TrackerPromptRegressionTests.test_hardcoded_tracker_assignment_is_gone`, `test_gate_prompts.py::GatePromptTests.test_both_gates_resolve_the_tracker_for_question_beads`.

**REQ-026** The skill shall document `br` initialization with no prerequisite beyond a local Git repository.
Source: ANC-018. Status: shipped.
Verified: `test_tracker_prompt_regressions.py::TrackerPromptRegressionTests.test_installation_doc_covers_br_and_selection`.

REQ-027 to REQ-029 (plan sources) are retired with ADR-005 and ADR-014; the numbers are not reused.

## Agents and runner

**REQ-030** Claude workflows shall invoke subagents with the Agent tool, never the Task tool; Cursor uses its Task tool without a model override.
Source: ANC-002; `references/agent-delegation-workflow.md`. Status: shipped.
Verified: none (instruction text only; no test asserts it).

**REQ-031** Each agent definition shall reside in its harness directory (`.claude/agents`, `.codex/agents`, `.cursor/agents`), with bodies identical across harnesses after frontmatter and registries identical after the harness path.
Source: ANC-009. Status: shipped.
Verified: `test_harness_agent_drift.py::HarnessAgentDriftTests`, `test_anchor_runner_contract.py::RunnerContractTests.test_resolves_real_claude_and_codex_registries`.

**REQ-032** The runner shall resolve the agent path, registry version, declared model and file hash once per invocation, so agents contain no install-path search or registry trust logic.
Source: INTENT "Success"; retired ANC-003 (requirement retained). Status: shipped.
Verified: `test_anchor_runner_contract.py::RunnerContractTests.test_rejects_traversal_symlink_nonregular_and_identity_mismatches`, `RunnerContractTests.test_detects_hash_change_after_resolution`.

**REQ-033** Each agent invocation and result shall carry exactly one fenced JSON object, rejected at the boundary when malformed.
Source: INTENT "Success"; retired ANC-004 (requirement retained). Status: shipped.
Verified: `test_anchor_runner_contract.py::RunnerContractTests.test_request_and_result_require_exactly_one_json_fence`, `RunnerContractTests.test_sc_compose_invocation_has_one_valid_fenced_request`.

**REQ-034** Agent inputs shall carry validated paths and identifiers confined to the Git workspace, never shell command strings.
Source: retired ANC-008 (requirement retained); `design/architecture-and-call-graphs.md` §5. Status: shipped.
Verified: `test_jev_judge.py::AgentPreflightTests`.

**REQ-035** The plugin shall not define or invoke `arch-qa` or `req-qa`.
Source: ANC-014. Status: shipped.
Verified: none (no file in `plugins/` names them; no test guards it).

**REQ-036** The planning gate and the code-review (development) gate shall be separate agents with separate Python entry points; plan review is production, code review is not.
Source: OPERATOR; ADR-009. Status: planned. The agents are separate; both run through `jev_judge.py judge --gate plan|dev`.
Verified: none.

## Question tuning

**REQ-037** Question tuning shall translate approved INTENT and ANC records into accurate Jev questions without optimizing for a favorable plan verdict, and the tuning contracts shall reject a desired verdict as an input.
Source: ANC-010, ANC-031. Status: shipped.
Verified: `test_anchor_tuning_contracts.py::AnchorTuningContractTests.test_v2_tune_result_renders_and_validates` (rejects `runtime.desired_verdict`).

**REQ-038** `anchor-tuning` shall run as a dedicated Opus/Sol (Cursor: Grok at high effort) subagent of the planner that calls Jev directly and in parallel over a candidate pool larger than production, ranks it and seals a smaller production set.
Source: ANC-020, ANC-026, ANC-027. Status: shipped.
Verified: partial: `test_anchor_tuning_contracts.py::AnchorTuningContractTests.test_harness_prompts_keep_tournament_and_production_separate` (models and tournament/production split), `test_v2_tune_result_renders_and_validates`. Parallel direct calls are prompt instructions with no test.

**REQ-039** `anchor-tuning` shall test candidates only on temporary plan copies with diagnostic additions and removals and shall not modify authoritative plan sources.
Source: ANC-021, ANC-022. Status: shipped.
Verified: partial: `test_anchor_tuning_contracts.py::AnchorTuningContractTests.test_rendered_tuning_results_satisfy_runner_and_tuning_contracts` (result carries `authoritative_sources_unchanged`); no test checks the sources byte-for-byte after a run.

**REQ-040** The planner shall launch a named `<team>-anchor-tuning` subagent concurrently after the first draft and INTENT/ANC capture, and leaf plan review shall wait for the sealed question-set digest.
Source: ANC-023; INTENT "Review policy". Status: shipped.
Verified: none.

**REQ-041** `anchor-tuning` may recommend clarity-only INTENT/ANC refinements but shall not apply them; the user approves each, and approval invalidates the affected oracles and rankings.
Source: ANC-024, ANC-025. Status: shipped.
Verified: partial: `test_anchor_tuning_contracts.py::AnchorTuningContractTests.test_initial_migration_and_later_history_events`, `test_first_migration_requires_predecessor_in_both_contracts` (versioned authority history); user approval itself has no test.

**REQ-042** After plan review, disputed failures shall go to `anchor-tuning` only through a checked-in `sc-compose` Jinja2 template, and the tuner shall return exactly one of `plan_violation` (question digest unchanged) or `question_defect`.
Source: ANC-028, ANC-029, ANC-030. Status: shipped.
Verified: `test_anchor_tuning_contracts.py::AnchorTuningContractTests.test_triage_request_and_result_render_validate_relationally`.

**REQ-043** `judge --stand-ins <names|all>` shall send the identical Jev request to fast stand-in models (Claude `haiku`, Codex `luna`) in parallel with Jev, one session per cell per model in an empty temp dir with no tools, validate each answer with `validate_response`, and record it beside the Jev answer without changing gating.
Source: OPERATOR; `design/anchor-tuning-stand-ins.md`. Status: planned.
Verified: none.

**REQ-044** `follow-up --run --cell --profile --question` shall resume the session of the stand-in that gave the answer and append the turn to the run's transcript file.
Source: OPERATOR; `design/anchor-tuning-stand-ins.md`. Status: planned.
Verified: none.

**REQ-045** The stand-in tuning loop shall treat stand-in output as advisory and divergence as signal, keep the tuner neutral, always run the follow-up turns without asking permission, and make one small plan edit per iteration followed by a re-run.
Source: OPERATOR; `design/anchor-tuning-stand-ins.md` "The loop". Status: planned.
Verified: none.

**REQ-046** Each tuning plan edit shall be its own commit, recorded in a notes table row (change, reason, run IDs, before/after failing cells) and compared with `jev_judge.py diff`; there shall be no ledger CLI.
Source: OPERATOR; `design/anchor-tuning-stand-ins.md` "Ledger". Status: planned; only the `diff` subcommand is built.
Verified: `diff` only: `test_jev_judge.py::DiffTests`.

## Python and CLI contract

**REQ-047** Skill scripts shall use the standard library on Python 3.9 or newer; PyYAML is allowed only in `plan_anchor_settings.py` and `anchor_tracker.py`, imported lazily and reported as `DEPENDENCY.PYYAML` when missing. The installer is the exception (REQ-059).
Source: OPERATOR; ADR-006. Status: shipped.
Verified: `test_anchor_tracker.py::RepositoryContractTests.test_other_scripts_stay_stdlib_only`, `MalformedInputTests.test_missing_pyyaml_is_a_typed_error_not_a_fallback`; CI `dependency-floor` job.

**REQ-048** Functions that can fail in an expected way shall return `Result[T, E]` (frozen `Ok`/`Err` with a literal `ok` discriminant) rather than raise; exceptions are for bugs and are converted to `SCRIPT.INTERNAL` at the CLI boundary.
Source: OPERATOR; ADR-006. Status: shipped in every skill script and `install.py`, except that `anchor_runner_contract.py` converts only I/O errors (`SCRIPT.IO`) and lets other exceptions escape.
Verified: `test_result.py::ResultHelperTests`, `ScriptErrValueTests`, `JevPropagationTests.test_main_reports_an_unexpected_exception_as_script_internal`, `test_anchor_tracker.py::CliTests.test_unexpected_exception_becomes_script_internal`, `test_error_contracts.py::TuningContractCli.test_unexpected_failure_is_script_internal`, `test_jev_judge.py::ErrorHandlingTests.test_unexpected_exceptions_become_script_internal`.

**REQ-049** Every error shall be printed as the JSON envelope `{success: false, data, error: {code, message, recoverable, suggested_action}}`, never a traceback.
Source: OPERATOR; ADR-007. Status: shipped, except argparse usage errors in `jev_judge.py`, `anchor_runner_contract.py` and `anchor_tuning_contract.py`, which are plain text on stderr.
Verified: `test_error_contracts.py::JevJudgeErrorContracts.test_every_offline_error_code_keeps_its_exact_envelope`, `RunnerContractErrorContracts.test_fence_error_envelopes`, `RunnerContractErrorContracts.test_resolve_error_envelopes`, `TuningContractCli.test_cli_reports_every_error_as_an_envelope_with_exit_two`, `test_jev_judge.py::ErrorHandlingTests.test_every_file_argument_yields_json_errors`, `test_anchor_tracker.py::CliTests.test_envelope_and_exit_codes`, `CliTests.test_usage_errors_are_json`, `test_install.py::InstallTests.test_cli_envelope_and_exit_codes`.

**REQ-050** Exit codes shall be 0 for success, 1 only for a completed run with a negative result, and 2 for any error. A `judge` run whose cells include `verdict: error` is a completed run with a negative result (exit 1); errors that stop a run exit 2.
Source: OPERATOR; ADR-007. Status: shipped, except `jev_judge.py validate`, which exits 1 with a `success: false` error envelope.
Verified: `test_error_contracts.py::JevJudgeErrorContracts.test_fixture_missing_is_a_per_anchor_error_verdict`, `JevTransportErrorContracts.test_401_aborts_the_run_with_body_withheld`, `JevTransportErrorContracts.test_transient_codes_retry_three_times_then_record_an_error_verdict`, `test_anchor_tracker.py::CliTests.test_fatal_codes_exit_two`, `test_jev_judge.py::ErrorHandlingTests.test_exit_codes`. `test_error_contracts.py::JevJudgeErrorContracts.test_validate_problems_and_lint_warnings_exit_one` pins the `validate` deviation.

**REQ-051** Every agent or stand-in launch shall report a typed failure reason, and failures shall never fall back silently; a stand-in launch failure shall exit 2 with a typed error envelope.
Source: OPERATOR; `design/anchor-tuning-stand-ins.md` "Failures". Status: shipped for runner contract failures; planned for stand-in launches.
Verified: partial: `test_anchor_runner_contract.py::RunnerContractTests.test_attestation_is_redacted_and_atomic_failures_are_typed`.

**REQ-052** CI shall run the full suite on ubuntu, macOS and Windows with Python 3.9 and 3.x, a Python 3.9 job without PyYAML and on the PyYAML 5.1 floor, and an installer job on Python 3.11 (ubuntu, macOS) where the `sc-compose` tests must run rather than skip.
Source: OPERATOR; `.github/workflows/tests.yml`. Status: shipped.
Verified: `test_anchor_tracker.py::RepositoryContractTests.test_ci_installs_pyyaml`; the matrix itself is the workflow.

## Documentation and packaging

**REQ-053** The normal plan-anchoring workflow shall require Jev; offline modes are for development only.
Source: ANC-011. Status: shipped.
Verified: none.

**REQ-054** Examples shall be executable with repository-valid paths, supported commands and supported JSON schemas.
Source: ANC-013. Status: shipped.
Verified: partial: `test_jev_judge.py::QuoteTests.test_shipped_example_record_is_valid_lint_clean_and_renders`, `ErrorHandlingTests.test_documented_question_sets_load`, `RubricTests.test_shipped_question_sets_load_and_fixtures_validate`, `ResponseValidationTests.test_shipped_fixture_passes_validation`. README and reference command snippets are not executed.

**REQ-055** Maintainer tests shall not be redistributed with the plugin.
Source: `tests/sc-plan-anchor/test_package_layout.py`. Status: shipped.
Verified: `test_package_layout.py::MarketplacePackageLayoutTests.test_maintainer_tests_are_not_redistributed_with_the_plugin`.

**REQ-056** `claude-code-skills-agents-guidelines.md` shall be the governing architecture baseline for the skill, agents, registries, runner and orchestration.
Source: ANC-001. Status: shipped.
Verified: none (not mechanically testable).

**REQ-057** Both gates shall judge the sprint text the calling agent supplies through `judge --item-file` (or stdin), read from wherever that agent wrote the plan, with no plan parsing or format requirement; anchor records shall use only the tracker `anchor_tracker.py` resolves, and installed skill and agent text shall name only the installed tracker's commands.
Source: OPERATOR (2026-10-17); INTENT "Success"; ADR-014. Status: shipped.
Verified: `test_gate_prompts.py::GatePromptTests.test_both_gates_take_the_callers_text_as_item_file`, `GatePromptTests.test_no_gate_references_plan_source_descriptors_or_discovery`, `GatePromptTests.test_plan_source_is_not_shipped`, `FreeFormSprintDryRunTests.test_free_form_sprint_builds_a_request_at_both_gates`, `test_install.py::RenderingTests.test_br_and_bd_installs_name_one_tracker`.

**REQ-058** `VERSION` shall be the single source of truth for every shipped version string, and each release shall have a `CHANGELOG.md` section.
Source: OPERATOR (0.6.0 release). Status: shipped.
Verified: `test_version_ssot.py::VersionSingleSourceOfTruthTests.test_every_shipped_version_equals_version_file`, `VersionSingleSourceOfTruthTests.test_planted_drift_is_reported_by_path`, `VersionSingleSourceOfTruthTests.test_missing_changelog_section_is_reported`.

## Installer

**REQ-059** `install.py` shall run through `uv run` with PEP 723 metadata (PyYAML, `sc-compose` >=1.7.0,<2, Python 3.11 pin) and render each tracker-naming file strictly for the selected tracker, so a `br` install names no `bd` command and a `bd` install no `br` command; the committed plugin tree shall be the templates' `neutral` render.
Source: OPERATOR; ADR-015. Status: shipped.
Verified: `test_install.py::RenderingTests.test_br_and_bd_installs_name_one_tracker`, `RenderingTests.test_committed_tree_is_the_neutral_render`, `RenderingTests.test_every_template_renders_strictly_for_each_tracker`, `RenderingTests.test_planted_negatives`, `InstallTests.test_missing_sc_compose_is_typed_error`.

**REQ-060** An install shall record version, tracker, targets and a sha256 per file in `.sc/plan-anchor/install-lock.json`; a rerun of the same version shall change nothing, and an upgrade shall remove unchanged files the new version no longer ships while keeping files it does not own.
Source: OPERATOR; ADR-015. Status: shipped.
Verified: `test_install.py::InstallTests.test_rerun_is_idempotent`, `InstallTests.test_upgrade_removes_retired_files_and_keeps_others`, `InstallTests.test_invalid_lock_is_typed_error`, `HistoryMigrationTests.test_migrate_0_6_0_removes_plan_source`.

**REQ-061** The installer shall refuse, before writing anything, a modified, modified-retired, unowned or foreign file (`INSTALL.CONFLICT` naming each path), and `--overwrite` shall move each to `.backup/<UTC>/<path>` before replacing it.
Source: OPERATOR; ADR-015. Status: shipped.
Verified: `test_install.py::InstallTests.test_modified_file_is_refused_then_backed_up_with_overwrite`, `InstallTests.test_modified_retired_file_is_refused`, `InstallTests.test_unowned_file_is_never_overwritten`, `InstallTests.test_foreign_skill_directory_is_refused`.

**REQ-062** A repository vendored before the lock existed shall be adopted once: a file is owned only when its bytes match a file an earlier version shipped, as recorded in `install/legacy-owned.json`, which is generated from git history and checked in CI.
Source: OPERATOR; ADR-015. Status: shipped.
Verified: `test_install.py::HistoryMigrationTests.test_migrate_0_3_0`, `HistoryMigrationTests.test_migrate_0_4_0_removes_retired_agent_and_tests`, `HistoryMigrationTests.test_edited_legacy_file_is_not_owned`, `GeneratedDataTests.test_manifest_and_legacy_are_in_sync`, `GeneratedDataTests.test_legacy_covers_retired_files`.

**REQ-063** Tracker switching shall follow ADR-004's rules: a detected tracker that differs from the installed one is `TRACKER.MISMATCH` until `--tracker` names it; a switch re-renders every locked target, updates `anchor_tracker`, and states that issue data is not migrated; `bd` requires a Dolt-backed `.beads/` (`TRACKER.DOLT_REQUIRED`), and no `.beads/` requires `--init-br` (`TRACKER.NOT_INITIALIZED`).
Source: OPERATOR; ADR-015. Status: shipped.
Verified: `test_install.py::InstallTests.test_switch_br_to_bd_with_dolt`, `InstallTests.test_switch_bd_to_br`, `InstallTests.test_switch_to_br_without_beads_needs_init_flag`, `InstallTests.test_bd_refused_without_dolt`, `InstallTests.test_no_beads_without_init_flag_is_typed_error`.

**REQ-064** `--dry-run` shall report the full plan and write nothing, run no `br init`, and change no file, including for a tracker switch.
Source: OPERATOR; ADR-015. Status: shipped.
Verified: `test_install.py::InstallTests.test_dry_run_writes_nothing`.

## Remote-judge consent

**REQ-065** Consent to send plan text to TypeSafe shall be `allow_remote_judge: true|false` in the committed `.sc/plan-anchor/settings.yaml`, never an environment variable and never inferred from past runs; with the key absent, `judge` shall refuse and send nothing, and the user is asked once and the answer recorded.
Source: OPERATOR (2026-10-17); ADR-016. Status: planned.
Verified: none.

**REQ-066** The installer shall take `--allow-remote-judge` / `--no-remote-judge` and record the answer in the settings file.
Source: OPERATOR (2026-10-17); ADR-016. Status: planned.
Verified: none.
