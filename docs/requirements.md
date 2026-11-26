# sc-plan-anchor requirements

**Status:** Active  
**Version:** 1.0.0  
**Created:** 2026-10-17  
**Last Updated:** 2026-11-26  
**Owner:** Rand Lee  

Requirements for the `plan-anchoring` skill in `plugins/sc-plan-anchor/`. Each
entry is derived from an existing source; nothing here is new scope.

- **Source** cites an anchor in [`plans/phase-a/anchors.json`](plans/phase-a/anchors.json)
  (`ANC-NNN`), the [Phase A intent](plans/phase-a/intent.md) (`INTENT`), a
  document, or an operator decision (`OPERATOR`). Retired anchors are cited only
  where their retirement reason says the requirement itself remains.
- **Status** describes the code at 0.8.3 (`fix/0.8.3-errors`): `shipped` (built),
  `planned` (decided, not built).

Architecture decisions are in [architecture.md](architecture.md); component and
call-graph detail is in [design/architecture-and-call-graphs.md](design/architecture-and-call-graphs.md)
and [design/data-model-and-gating.md](design/data-model-and-gating.md).

## Anchors and records

## REQ-PA-0001:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The skill shall store every anchor in `anchors.json` with an immutable verbatim `quote` and a separately authored, user-approved testable `statement`.

### Rationale

Source: PRD "Provenance & reporting"; `design/data-model-and-gating.md` §2. Status: shipped.


## REQ-PA-0002:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The script shall allocate `ANC-NNN` IDs as max plus one, never reuse them, and keep register IDs for REQ and ADR anchors.

### Rationale

Source: `design/data-model-and-gating.md` §2. Status: shipped.


## REQ-PA-0003:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Only `locked` and `promoted` anchors shall be judged by `--all`, and an explicit `--anchor` on a proposed or retired anchor shall be refused (`ANCHOR.NOT_LOCKED`) unless `--include-unlocked` is given; no anchor to judge is `ANCHOR.NONE` and an unknown ID `ANCHOR.UNKNOWN`.

### Rationale

Source: `design/data-model-and-gating.md` §6. Status: shipped.


## REQ-PA-0004:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Nothing shall be locked without user confirmation. `add` shall always refuse a statement that repeats the quote and a likely duplicate (word overlap ≥ 0.6, `ANCHOR.DUPLICATE_CANDIDATE`, unless `--allow-similar`; an existing REQ/ADR ID is `ANCHOR.DUPLICATE`); other lint findings are warnings unless `--strict` (`ANCHOR.LINT`); the testability rubric runs only with `--rubric` (`ANCHOR.NOT_TESTABLE` unless `--allow-untestable`).

### Rationale

Source: SKILL.md "Design positions" (Capture); `references/anchor-capture.md`. Status: shipped (lint and rubric are not mandatory in the script; the skill instructs running them).


## REQ-PA-0005:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- `anchors.md` shall be rendered from `anchors.json` and never hand-edited.

### Rationale

Source: `design/data-model-and-gating.md` §1. Status: shipped.


## REQ-PA-0006:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- An anchor shall be able to carry an `exclude` list of `{item, reason}` entries; `judge` shall skip each listed cell without calling Jev, report it as `excluded` (passing) with its reason in the run summary, report, coverage, diff and `anchors.md`, with no approval workflow and no other new verdict state.

### Rationale

Source: OPERATOR; `design/anchor-tuning-stand-ins.md` "Anchor exclusions". Status: shipped.


## Jev requests and gating

## REQ-PA-0007:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Each Jev request shall contain exactly `state.anchor {id, statement, scope}`, `state.item {id, title, text}`, and the gate's question set, and shall not contain intent, source metadata, or a second anchor or item.

### Rationale

Source: OPERATOR; PRD "Keep the state small"; `design/data-model-and-gating.md` §3. Status: shipped.


## REQ-PA-0008:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The planning gate shall send a bead whole, never shorten prose.

### Rationale

Source: OPERATOR; `experiments/2026-10-10-redact-only-when-oversize.md`. Status: shipped.


## REQ-PA-0009:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The script shall turn independent answers into one verdict in code, first match wins. For a directive: relevance `no` at confidence ≥ 0.6 is `not_applicable`; a lower-confidence relevance `no` falls through and ends as `underspecified`; then `contradicted`, `underspecified`, `not_addressed`, and `asserted_only` or `satisfied` only when compliance is `yes` and conflict is a confident `no` (otherwise `underspecified`). A prohibition and a structural anchor gate differently (REQ-PA-0075).

### Rationale

Source: OPERATOR; `design/data-model-and-gating.md` §4. Status: shipped.


## REQ-PA-0010:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Coverage across items and run-to-run differences shall be computed by the script from run files, never asked of Jev. Dry-run run files already on disk shall be skipped.

### Rationale

Source: PRD "Do the counting in code"; `design/data-model-and-gating.md` §5. Status: shipped.


## REQ-PA-0013:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Each live run shall be written to its own run file that copies the statement, quote and provenance it judged. Each anchor result in a run file shall carry plan-anchor's own `anchor_id` and the `session_id` of every Jev query that produced it (two when the request was confirmed, REQ-PA-0076). A run file shall not contain Jev's answers, `model_answered` or `attempts`; they are read from the sc-agent session row with that `session_id`.

### Rationale

Source: `design/data-model-and-gating.md` §1–2; OPERATOR (phase j session-log ruling, 2026-11-24). Status: shipped for the copied statement, quote and provenance; planned for `session_id` in place of the answers, `model_answered` and `attempts` (phase j).


## REQ-PA-0014:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- A failing report shall name the anchor and show its statement next to the user's verbatim quote.

### Rationale

Source: PRD "Provenance & reporting". Status: shipped.


## Data leaving the machine and configuration

## REQ-PA-0019:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Repository settings shall live in `.sc/plan-anchor/settings.yaml`: YAML with snake_case keys (`schema_version`, `anchor_tracker`, `allow_remote_judge`, `plan_dir` (REQ-PA-0088)), committed, no secrets, `schema_version: 1`, and strict validation that rejects unknown keys, duplicate keys and wrong types.

### Rationale

Source: OPERATOR. Status: shipped. Values are parsed with PyYAML's `SafeLoader` (YAML 1.1), so `allow_remote_judge: yes` reads as `true` and is accepted; `plan_anchor_settings.py set` writes only `true` or `false`. "Committed" is checked only as not git-ignored (`set` reports `settings_ignored_by_git`); tracking is not checked.


## Trackers

## REQ-PA-0021:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Anchor and question storage, and both gates, shall work with either `br` or `bd`.

### Rationale

Source: OPERATOR; INTENT "Success"; retired ANC-007 (requirement retained). Status: shipped.


## REQ-PA-0022:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Tracker selection shall be: an explicit `anchor_tracker` in the settings file in effect (the nearest, REQ-070) wins and is validated against disk; otherwise a Dolt-backed `.beads/` selects `bd`, any other `.beads/` selects `br`, and no `.beads/` selects `br`; a mismatch is an error, never a silent switch.

### Rationale

Source: OPERATOR. Status: shipped. Since 0.8.2 `install.py` applies these rules to both trackers; an installed `anchor_tracker.py` is rendered for one tracker (REQ-059) and refuses a setting naming the other (`SETTINGS.INVALID_TRACKER`) or a `.beads/` that does not fit it (`TRACKER.MISMATCH` in a `br` install, `TRACKER.DOLT_REQUIRED` in a `bd` install), with the installer's `--tracker` as the suggested action.


## REQ-PA-0023:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The skill and the installer shall never run or recommend `bd init`; `br init` is the only bootstrap and runs only on `anchor_tracker.py write --init` or `install.py --init-br`, with fixed argv and no shell.

### Rationale

Source: OPERATOR. Status: shipped.


## REQ-PA-0025:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Both gate reviewers shall take the tracker from `anchor_tracker.py resolve`, never from a default, and reject a mismatch with a supplied value.

### Rationale

Source: OPERATOR; SKILL.md Step 1. Status: shipped.


## Agents and runner

## REQ-PA-0031:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Each agent definition shall be installed in its harness directory (`.claude/agents`, `.codex/agents`, `.cursor/agents`) from one body template plus per-harness frontmatter (`install/harness/<target>/agents/`), with bodies identical across harnesses after frontmatter and registries identical after the harness path.

### Rationale

Source: ANC-009. Status: shipped.


## REQ-PA-0032:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The runner shall resolve the agent path, registry version, declared model and file hash once per invocation, so agents contain no registry trust logic. The gate agents do carry the `jev_judge.py` trust rule (REQ-069) as prompt text, which `agent-preflight` enforces.

### Rationale

Source: INTENT "Success"; retired ANC-003 (requirement retained). Status: shipped.


## REQ-PA-0033:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Each agent invocation and result shall carry exactly one fenced JSON object, rejected at the boundary when malformed.

### Rationale

Source: INTENT "Success"; retired ANC-004 (requirement retained). Status: shipped.


## REQ-PA-0034:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Agent inputs shall carry validated paths and identifiers confined to the Git workspace, never shell command strings.

### Rationale

Source: retired ANC-008 (requirement retained); `design/architecture-and-call-graphs.md` §5. Status: shipped.


## REQ-PA-0036:

**Status:** planned  

### Requirement Statement

**MUST statements:**

- The planning gate and the code-review (development) gate shall be separate agents with separate Python entry points; plan review is production, code review is not.

### Rationale

Source: OPERATOR. Status: planned. The agents are separate; both run through `jev_judge.py judge --gate plan|dev`.


## Question tuning

## REQ-PA-0037:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Question tuning shall translate approved INTENT and ANC records into accurate Jev questions without optimizing for a favorable plan verdict, and the tuning contracts shall reject a desired verdict as an input.

### Rationale

Source: ANC-010, ANC-031. Status: shipped.


## REQ-PA-0038:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- `anchor-tuning` shall run as a dedicated Opus/Sol (Cursor: Grok at high effort) subagent of the planner that judges a candidate pool larger than production in parallel, ranks it and seals a smaller production set. The tuner's Jev queries shall go only through `jev_judge.py tournament`, which sends each one through sc-agent `send` so that it gets a row in the sc-agent session log; the tuner shall not call Jev any other way.

### Rationale

Source: ANC-020, ANC-026, ANC-027; OPERATOR (phase j session-log ruling, 2026-11-24). Status: shipped (the tournament sends through the sc-decidr client).


## REQ-PA-0039:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- `anchor-tuning` shall test candidates only on temporary plan copies with diagnostic additions and removals and shall not modify authoritative plan sources.

### Rationale

Source: ANC-021, ANC-022. Status: shipped.


## REQ-PA-0040:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The planner shall launch one named `anchor-tuning` subagent concurrently after the first draft and INTENT/ANC capture, and leaf plan review shall wait for the sealed question-set digest.

### Rationale

Source: ANC-023; INTENT "Review policy". Status: shipped.


## REQ-PA-0041:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- `anchor-tuning` may recommend clarity-only INTENT/ANC refinements but shall not apply them; the user approves each, and approval invalidates the affected oracles and rankings.

### Rationale

Source: ANC-024, ANC-025. Status: shipped.


## REQ-PA-0042:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- After plan review, disputed failures shall go to `anchor-tuning` only through a checked-in `sc-compose` Jinja2 template, and the tuner shall return exactly one of `plan_violation` (question digest unchanged) or `question_defect`.

### Rationale

Source: ANC-028, ANC-029, ANC-030. Status: shipped.


## Python and CLI contract

## REQ-PA-0051:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Every agent launch shall report a typed failure reason, and failures shall never fall back silently.

### Rationale

Source: OPERATOR; `design/anchor-tuning-stand-ins.md` "Failures". Status: shipped for runner contract failures.


## Documentation and packaging

## REQ-PA-0057:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Both gates shall judge the sprint text the calling agent supplies through `judge --item-file` (or stdin), read from wherever that agent wrote the plan, with no plan parsing or format requirement; anchor records shall use only the tracker `anchor_tracker.py` resolves, and installed skill and agent text shall name only the installed tracker's commands.

### Rationale

Source: OPERATOR (2026-10-17); INTENT "Success"; ADR-PA-0014; ANC-016; ANC-017. Status: shipped.


## Installer

## Remote-judge consent

## REQ-PA-0065:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Consent to send plan text to TypeSafe shall be `allow_remote_judge: true|false` in the committed `.sc/plan-anchor/settings.yaml` (the nearest file), never an environment variable and never inferred from past runs; the answer recorded with `plan_anchor_settings.py set allow_remote_judge true|false`.

### Rationale

Source: OPERATOR (2026-10-17); OPERATOR (phase j plan-review ruling, 2026-11-24) (consent covers TypeSafe only). Status: shipped (0.7.1).


## Per-folder installs (0.8.0)

## Judging and installer details

## REQ-PA-0075:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- An anchor's `kind` shall be `directive` (the default, and the reading of a record without one), `prohibition` or `structural`, set by `add --kind` or `update --kind` and checked by `validate`. A prohibition ignores compliance: `not_applicable` on a confident relevance `no`, `contradicted` on a confident conflict `yes`, `underspecified` when relevance is unclear or below the threshold or conflict is not a confident `no`, `asserted_only` when the development gate's evidence is a confident `no`, else `satisfied`. A structural anchor is never sent to Jev at the planning gate (verdict `deterministic_only`, which passes, also in `check-fixtures`) and is gated as a directive at the development gate.

### Rationale

Source: CHANGELOG 0.3.0. Status: shipped.


## REQ-PA-0076:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- When a live answer to a gating role (not a prohibition's compliance) is within 0.10 of the threshold, `judge` and `check-fixtures` shall send the identical request once more with `cache=False`, so that the second send is a new Jev call with its own session row and not a result-cache hit: agreement sets `confirmed`; disagreement makes the cell `underspecified` with `unstable`, both verdicts and both `session_id`s; a second call with no answer keeps the first verdict, records `confirm_error` and exits 2 (REQ-050). It is on by default; `--no-confirm` turns it off and `--confirm-near-threshold` only states the default; fixture answers are never re-asked. Every judged result carries `leaning` (the verdict at threshold 0), and an `underspecified` one carries `low_questions`. When `--repeat` of `batch` or `bead-batch`, or the tournament request's `repeat_count`, is greater than 1, every repeat shall be sent with `cache=False`, all repeats in one call that keeps their order, so that each repeat is its own Jev call with its own `session_id`. The second and third testability confirmations of `rubric` and `add --rubric` shall also be sent with `cache=False`.

### Rationale

Source: CHANGELOG 0.3.0, 0.7.3; OPERATOR (phase j session-log ruling, 2026-11-24). Status: shipped; planned for `cache=False` and both `session_id`s in place of the second answers (phase j).

Source: OPERATOR (phase j session-log ruling, 2026-11-24); OPERATOR (phase j ruling, 2026-11-24); `skills/plan-anchoring/references/question-tuning.md` "Run". Status: planned (phase j; today `_rubric_judgement` in `jev_judge.py.j2` re-asks with the cache on).


## REQ-PA-0078:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The record subcommands shall be `add` (`--status proposed|locked`, default `proposed`; `--stated-by` defaults to `USER`), `update`, `retire`, `exclude` (`--remove`), `set-beads`, `promote --adr` and `render`; `retire` and `promote` bump `version`, `exclude` and `set-beads` do not, and `promote` does not check the anchor's status. No subcommand moves `proposed` to `locked` or writes `question_overrides`, which `judge` still reads from the record before `--overrides-file`.

### Rationale

Source: CHANGELOG 0.2.0, 0.3.0; `design/data-model-and-gating.md` §2, §6. Status: shipped.


## REQ-PA-0079:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- `compose-item` shall build the item text from a tracker `show --json` (`--show-json`, `-` for stdin), optional `--children-json` and `--sections`; `--for plan` keeps the description and acceptance criteria and drops children. `shape` shall report size and shape metrics and never gate.

### Rationale

Source: CHANGELOG 0.3.0. Status: shipped.


## REQ-PA-0081:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- When a gate agent's question bead cannot be shown by the tracker, the agent shall stop with `TRACKER.SHOW_FAILED` rather than judge with the default questions.

### Rationale

Source: CHANGELOG 0.8.3. Status: shipped (prompt text in `anchor-plan-review` and `anchor-sprint-review`).


## REQ-PA-0088:

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The anchor record (`intent.md`, `anchors.json`, `anchors.md`, `anchor-runs/`) shall live in the current phase's plan folder, `docs/plans/phase-<current>/` with the phase id written out, named by `plan_dir` in `.sc/plan-anchor/settings.yaml`. `plan_anchor_settings.py set plan_dir` records it and `show` reports it; a value that is absolute, has an empty, `.` or `..` part, a backslash or a `<placeholder>` is `SETTINGS.INVALID_PLAN_DIR` in the file and `VALIDATION.INPUT` on `set`; the installer and `anchor_tracker.py write` keep it. The skill sets `A="$P/anchors.json"` from it and asks the user when it is unset; no shipped file names a literal folder. A new record's `plan` and `intent_ref` default to the folder holding `--anchors` and `intent.md` beside it.

### Rationale

Source: OPERATOR (issue #58, 0.8.6). Status: shipped.


## Session log and run records (phase j)

## REQ-PA-0083:

**Status:** planned  

### Requirement Statement

**MUST statements:**

- A `--dry-run` shall only check that its input composes into valid requests and show the would-send requests, redacted, on stdout, or in the file named by `--out` (for `judge`, `--out` names the requests file on a dry run). A dry run shall write no file under `anchor-runs/`, no run file, no result line and no log event. A `--out` path inside `anchor-runs/` on a dry run shall be refused with `VALIDATION.INPUT`. `--dry-run` and `--answers-file` execution shall make zero network calls.

### Rationale

Source: OPERATOR (phase j session-log ruling, 2026-11-24); INTENT "Success"; retired ANC-006 (requirement retained). Status: planned (phase j; today a dry run writes a run file marked `dry_run`, and `tournament --dry-run` writes `requests.dry-run.jsonl` in `--out`).


