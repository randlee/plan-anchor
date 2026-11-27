# sc-plan-anchor requirements

**Status:** Active  
**Version:** 0.14.0  
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

## REQ-PA-0001: Anchor storage with verbatim quote and statement

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The skill shall store every anchor in `anchors.json` with an immutable verbatim `quote` and a separately authored, user-approved testable `statement`.

### Rationale

Source: PRD "Provenance & reporting"; `design/data-model-and-gating.md` §2. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test reads anchors.json and finds every anchor has a verbatim `quote` field and a separate `statement` field.
- [ ] A test that tries to change an existing anchor's `quote` finds the `quote` unchanged in anchors.json.
- [ ] A test finds each anchor's `statement` in anchors.json is recorded as user-approved, separate from the `quote`.

## REQ-PA-0002: ANC-NNN ID allocation and register IDs

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The script shall allocate `ANC-NNN` IDs as max plus one, never reuse them, and keep register IDs for REQ and ADR anchors.

### Rationale

Source: `design/data-model-and-gating.md` §2. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test adds an anchor to a register whose highest `ANC-NNN` ID is ANC-007 and the script allocates ANC-008.
- [ ] A test retires the anchor with the highest `ANC-NNN` ID, adds a new anchor, and the script allocates an ID that was not used before.
- [ ] A test adds REQ and ADR anchors and the script keeps their register IDs instead of allocating `ANC-NNN` IDs.

## REQ-PA-0003: Anchor selection for judging by status

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Only `locked` and `promoted` anchors shall be judged by `--all`, and an explicit `--anchor` on a proposed or retired anchor shall be refused (`ANCHOR.NOT_LOCKED`) unless `--include-unlocked` is given; no anchor to judge is `ANCHOR.NONE` and an unknown ID `ANCHOR.UNKNOWN`.

### Rationale

Source: `design/data-model-and-gating.md` §6. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test runs judge with `--all` over anchors in every status and only `locked` and `promoted` anchors are judged.
- [ ] A test runs judge with an explicit `--anchor` on a proposed anchor and on a retired anchor and each is refused with `ANCHOR.NOT_LOCKED`; the same runs with `--include-unlocked` judge the anchor.
- [ ] A test with no anchor to judge returns `ANCHOR.NONE`.
- [ ] A test with an unknown anchor ID returns `ANCHOR.UNKNOWN`.

## REQ-PA-0004: Anchor add confirmation, duplicate and lint checks

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Nothing shall be locked without user confirmation. `add` shall always refuse a statement that repeats the quote and a likely duplicate (word overlap ≥ 0.6, `ANCHOR.DUPLICATE_CANDIDATE`, unless `--allow-similar`; an existing REQ/ADR ID is `ANCHOR.DUPLICATE`); other lint findings are warnings unless `--strict` (`ANCHOR.LINT`); the testability rubric runs only with `--rubric` (`ANCHOR.NOT_TESTABLE` unless `--allow-untestable`).

### Rationale

Source: SKILL.md "Design positions" (Capture); `references/anchor-capture.md`. Status: shipped (lint and rubric are not mandatory in the script; the skill instructs running them).

### Success Criteria

**Acceptance Criteria:**

- [ ] A test shows that no anchor is locked without user confirmation.
- [ ] A test shows `add` refuses a statement that repeats the quote, refuses a likely duplicate with word overlap ≥ 0.6 as `ANCHOR.DUPLICATE_CANDIDATE` unless `--allow-similar` is given, and refuses an existing REQ/ADR ID as `ANCHOR.DUPLICATE`.
- [ ] A test shows other lint findings from `add` are warnings without `--strict` and `ANCHOR.LINT` errors with `--strict`.
- [ ] A test shows the testability rubric runs only with `--rubric` and reports `ANCHOR.NOT_TESTABLE` unless `--allow-untestable` is given.

## REQ-PA-0005: anchors.md rendered from anchors.json

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- `anchors.md` shall be rendered from `anchors.json` and never hand-edited.

### Rationale

Source: `design/data-model-and-gating.md` §1. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] Rendering anchors.md from anchors.json produces output identical to the committed anchors.md.
- [ ] A test that hand-edits anchors.md and re-renders from anchors.json finds the hand edit replaced by the rendered content.

## REQ-PA-0006: Anchor exclude list in judge

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- An anchor shall be able to carry an `exclude` list of `{item, reason}` entries; `judge` shall skip each listed cell without calling Jev, report it as `excluded` (passing) with its reason in the run summary, report, coverage, diff and `anchors.md`, with no approval workflow and no other new verdict state.

### Rationale

Source: OPERATOR; `design/anchor-tuning-stand-ins.md` "Anchor exclusions". Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test writes an anchor with an `exclude` list of `{item, reason}` entries and the anchor record accepts the list.
- [ ] A test runs `judge` on an anchor with an `exclude` entry and the listed cell is skipped with no Jev call.
- [ ] The skipped cell appears as `excluded` (passing) with its reason in the run summary, report, coverage, diff and `anchors.md`.
- [ ] The `judge` code has no approval workflow for exclusions and no verdict state other than `excluded` added for them.

## Jev requests and gating

## Jev requests and gating

## REQ-PA-0007: Contents of each Jev request

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Each Jev request shall contain exactly `state.anchor {id, statement, scope}`, `state.item {id, title, text}`, and the gate's question set, and shall not contain intent, source metadata, or a second anchor or item.

### Rationale

Source: OPERATOR; PRD "Keep the state small"; `design/data-model-and-gating.md` §3. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test inspects a composed Jev request and finds exactly `state.anchor {id, statement, scope}`, `state.item {id, title, text}` and the gate's question set.
- [ ] A test inspects a composed Jev request and finds no intent, no source metadata, and no second anchor or item.

## REQ-PA-0008: Planning gate sends whole beads

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The planning gate shall send a bead whole, never shorten prose.

### Rationale

Source: OPERATOR; `experiments/2026-10-10-redact-only-when-oversize.md`. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test shows the planning gate sends a bead whole, with the bead prose identical to the bead text and not shortened.

## REQ-PA-0009: Directive verdict combination order

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The script shall turn independent answers into one verdict in code, first match wins. For a directive: relevance `no` at confidence ≥ 0.6 is `not_applicable`; a lower-confidence relevance `no` falls through and ends as `underspecified`; then `contradicted`, `underspecified`, `not_addressed`, and `asserted_only` or `satisfied` only when compliance is `yes` and conflict is a confident `no` (otherwise `underspecified`). A prohibition and a structural anchor gate differently (REQ-PA-0075).

### Rationale

Source: OPERATOR; `design/data-model-and-gating.md` §4. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test with a directive and relevance `no` at confidence 0.6 or higher gets the verdict `not_applicable`; with relevance `no` below confidence 0.6 the verdict is `underspecified`.
- [ ] Tests feeding answers that match more than one verdict get the first match in the order `not_applicable`, `contradicted`, `underspecified`, `not_addressed`, then `asserted_only` or `satisfied`.
- [ ] A test gets `asserted_only` or `satisfied` only when compliance is `yes` and conflict is a confident `no`, and gets `underspecified` for every other compliance and conflict combination at that step.
- [ ] A test passes the same answers to the script twice and gets the same verdict, computed in code.

## REQ-PA-0010: Coverage and run differences computed from run files

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Coverage across items and run-to-run differences shall be computed by the script from run files, never asked of Jev. Dry-run run files already on disk shall be skipped.

### Rationale

Source: PRD "Do the counting in code"; `design/data-model-and-gating.md` §5. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test computes coverage across items from run files and the script produces the coverage with no Jev call.
- [ ] A test computes run-to-run differences from run files and the script produces the differences with no Jev call.
- [ ] A test places a dry-run run file on disk and the coverage and run-to-run differences skip that dry-run run file.

## REQ-PA-0013: Live run file contents

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Each live run shall be written to its own run file that copies the statement, quote and provenance it judged. Each anchor result in a run file shall carry plan-anchor's own `anchor_id` and the `session_id` of every Jev query that produced it (two when the request was confirmed, REQ-PA-0076). A run file shall not contain Jev's answers, `model_answered` or `attempts`; they are read from the sc-agent session row with that `session_id`.

### Rationale

Source: `design/data-model-and-gating.md` §1–2; OPERATOR (phase j session-log ruling, 2026-11-24). Status: shipped for the copied statement, quote and provenance; planned for `session_id` in place of the answers, `model_answered` and `attempts` (phase j).

### Success Criteria

**Acceptance Criteria:**

- [ ] A test performs a live run and finds the run written to its own run file containing a copy of the statement, quote and provenance it judged.
- [ ] Each anchor result in the run file carries plan-anchor's own `anchor_id` and the `session_id` of every Jev query that produced the result, two `session_id` values when the request was confirmed (REQ-PA-0076).
- [ ] The run file contains no Jev answers, no `model_answered` and no `attempts`; a test reads those from the sc-agent session row with the recorded `session_id`.

## REQ-PA-0014: Failing report anchor, statement and quote

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- A failing report shall name the anchor and show its statement next to the user's verbatim quote.

### Rationale

Source: PRD "Provenance & reporting". Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test shows a failing report names the anchor and shows the anchor statement next to the user's verbatim quote.

## Data leaving the machine and configuration

## Data leaving the machine and configuration

## REQ-PA-0019: Repository settings file in .sc/plan-anchor/settings.yaml

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Repository settings shall live in `.sc/plan-anchor/settings.yaml`: YAML with snake_case keys (`schema_version`, `anchor_tracker`, `allow_remote_judge`, `plan_dir` (REQ-PA-0088)), committed, no secrets, `schema_version: 1`, and strict validation that rejects unknown keys, duplicate keys and wrong types.

### Rationale

Source: OPERATOR. Status: shipped. Values are parsed with PyYAML's `SafeLoader` (YAML 1.1), so `allow_remote_judge: yes` reads as `true` and is accepted; `plan_anchor_settings.py set` writes only `true` or `false`. "Committed" is checked only as not git-ignored (`set` reports `settings_ignored_by_git`); tracking is not checked.

### Success Criteria

**Acceptance Criteria:**

- [ ] The repository settings are read from `.sc/plan-anchor/settings.yaml` as YAML with the snake_case keys `schema_version`, `anchor_tracker`, `allow_remote_judge` and `plan_dir`, and `schema_version: 1`.
- [ ] `.sc/plan-anchor/settings.yaml` is committed and contains no secrets.
- [ ] Tests load `.sc/plan-anchor/settings.yaml` with an unknown key, a duplicate key, and a wrong type, and validation rejects each one.

## Trackers

## Trackers

## REQ-PA-0021: Tracker support for br and bd

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Anchor and question storage, and both gates, shall work with either `br` or `bd`.

### Rationale

Source: OPERATOR; INTENT "Success"; retired ANC-007 (requirement retained). Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] Tests run anchor storage, question storage, the planning gate and the development gate with `br` and pass.
- [ ] The same tests run with `bd` and pass.

## REQ-PA-0022: Tracker selection rules

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Tracker selection shall be: an explicit `anchor_tracker` in the settings file in effect (the nearest, REQ-070) wins and is validated against disk; otherwise a Dolt-backed `.beads/` selects `bd`, any other `.beads/` selects `br`, and no `.beads/` selects `br`; a mismatch is an error, never a silent switch.

### Rationale

Source: OPERATOR. Status: shipped. Since 0.8.2 `install.py` applies these rules to both trackers; an installed `anchor_tracker.py` is rendered for one tracker (REQ-059) and refuses a setting naming the other (`SETTINGS.INVALID_TRACKER`) or a `.beads/` that does not fit it (`TRACKER.MISMATCH` in a `br` install, `TRACKER.DOLT_REQUIRED` in a `bd` install), with the installer's `--tracker` as the suggested action.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test shows an explicit `anchor_tracker` in the nearest settings file in effect wins and is validated against disk.
- [ ] A test shows that without an explicit `anchor_tracker`, a Dolt-backed `.beads/` selects `bd`, any other `.beads/` selects `br`, and no `.beads/` selects `br`.
- [ ] A test shows a mismatch between the selected tracker and disk is an error, with no silent switch of tracker.

## REQ-PA-0023: br init as the only bootstrap

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The skill and the installer shall never run or recommend `bd init`; `br init` is the only bootstrap and runs only on `anchor_tracker.py write --init` or `install.py --init-br`, with fixed argv and no shell.

### Rationale

Source: OPERATOR. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A search of the skill and installer files finds no command that runs `bd init` and no text that recommends `bd init`.
- [ ] A test finds `br init` runs on `anchor_tracker.py write --init` and on `install.py --init-br`, and on no other command.
- [ ] A test finds `br init` is invoked with a fixed argv and no shell.

## REQ-PA-0025: Gate reviewer tracker resolution

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Both gate reviewers shall take the tracker from `anchor_tracker.py resolve`, never from a default, and reject a mismatch with a supplied value.

### Rationale

Source: OPERATOR; SKILL.md Step 1. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A look at both gate reviewer definitions shows the tracker taken from `anchor_tracker.py resolve` and not from a default.
- [ ] A test supplies a tracker value that differs from `anchor_tracker.py resolve` and each gate reviewer rejects the mismatch.

## Agents and runner

## REQ-PA-0031: Agent definition installation across harnesses

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Each agent definition shall be installed in its harness directory (`.claude/agents`, `.codex/agents`, `.cursor/agents`) from one body template plus per-harness frontmatter (`install/harness/<target>/agents/`), with bodies identical across harnesses after frontmatter and registries identical after the harness path.

### Rationale

Source: ANC-009. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] After install, each agent definition is present in `.claude/agents`, `.codex/agents` and `.cursor/agents`, built from one body template plus the per-harness frontmatter in `install/harness/<target>/agents/`.
- [ ] A comparison of each agent definition across harnesses with frontmatter removed shows identical bodies.
- [ ] A comparison of the registries across harnesses with the harness path removed shows identical registries.

## REQ-PA-0032: Runner resolution of agent registry trust

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The runner shall resolve the agent path, registry version, declared model and file hash once per invocation, so agents contain no registry trust logic. The gate agents do carry the `jev_judge.py` trust rule (REQ-069) as prompt text, which `agent-preflight` enforces.

### Rationale

Source: INTENT "Success"; retired ANC-003 (requirement retained). Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test shows the runner resolves the agent path, registry version, declared model and file hash once per invocation.
- [ ] A look at the agent files shows the agents contain no registry trust logic, and the gate agents carry the `jev_judge.py` trust rule (REQ-PA-0069) as prompt text.
- [ ] A test shows `agent-preflight` enforces the `jev_judge.py` trust rule prompt text in the gate agents.

## REQ-PA-0033: Fenced JSON object per agent invocation and result

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Each agent invocation and result shall carry exactly one fenced JSON object, rejected at the boundary when malformed.

### Rationale

Source: INTENT "Success"; retired ANC-004 (requirement retained). Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test finds each agent invocation and each agent result carries exactly one fenced JSON object.
- [ ] A test passes a malformed fenced JSON object to the boundary and gets a rejection.

## REQ-PA-0034: Agent inputs confined to Git workspace

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Agent inputs shall carry validated paths and identifiers confined to the Git workspace, never shell command strings.

### Rationale

Source: retired ANC-008 (requirement retained); `design/architecture-and-call-graphs.md` §5. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test passes an agent input path outside the Git workspace and validation rejects the path.
- [ ] A test passes agent input paths and identifiers inside the Git workspace and validation accepts them.
- [ ] Agent input definitions carry paths and identifiers and contain no shell command strings.

## REQ-PA-0036: Separate planning and code-review gate agents

**Status:** planned  

### Requirement Statement

**MUST statements:**

- The planning gate and the code-review (development) gate shall be separate agents with separate Python entry points; plan review is production, code review is not.

### Rationale

Source: OPERATOR. Status: planned. The agents are separate; both run through `jev_judge.py judge --gate plan|dev`.

### Success Criteria

**Acceptance Criteria:**

- [ ] A look at the plugin files shows the planning gate and the code-review (development) gate are separate agents with separate Python entry points.

## Question tuning

## Question tuning

## REQ-PA-0037: Verdict-neutral question tuning

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Question tuning shall translate approved INTENT and ANC records into accurate Jev questions without optimizing for a favorable plan verdict, and the tuning contracts shall reject a desired verdict as an input.

### Rationale

Source: ANC-010, ANC-031. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test passes a desired verdict as an input to each tuning contract and gets a rejection.
- [ ] A look at the question tuning prompts finds Jev questions translated from approved INTENT and ANC records, with no instruction to aim for a favorable plan verdict.

## REQ-PA-0038: anchor-tuning subagent and tournament Jev queries

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- `anchor-tuning` shall run as a dedicated Opus/Sol (Cursor: Grok at high effort) subagent of the planner that judges a candidate pool larger than production in parallel, ranks it and seals a smaller production set. The tuner's Jev queries shall go only through `jev_judge.py tournament`, which sends each one through sc-agent `send` so that it gets a row in the sc-agent session log; the tuner shall not call Jev any other way.

### Rationale

Source: ANC-020, ANC-026, ANC-027; OPERATOR (phase j session-log ruling, 2026-11-24). Status: shipped (the tournament sends through the sc-decidr client).

### Success Criteria

**Acceptance Criteria:**

- [ ] The `anchor-tuning` agent definition runs as a subagent of the planner on Opus/Sol, and on Cursor on Grok at high effort.
- [ ] An `anchor-tuning` run judges a candidate pool larger than production in parallel, ranks the pool and seals a smaller production set.
- [ ] Each Jev query of an `anchor-tuning` run goes through `jev_judge.py tournament` via sc-agent `send` and has a row in the sc-agent session log.
- [ ] The `anchor-tuning` text and code contain no Jev call other than `jev_judge.py tournament`.

## REQ-PA-0039: anchor-tuning temporary plan copies

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- `anchor-tuning` shall test candidates only on temporary plan copies with diagnostic additions and removals and shall not modify authoritative plan sources.

### Rationale

Source: ANC-021, ANC-022. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A look at the `anchor-tuning` definition shows candidates tested only on temporary plan copies with diagnostic additions and removals.
- [ ] A test runs `anchor-tuning` and the authoritative plan sources are byte-identical before and after.

## REQ-PA-0040: Concurrent anchor-tuning launch and digest wait

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The planner shall launch one named `anchor-tuning` subagent concurrently after the first draft and INTENT/ANC capture, and leaf plan review shall wait for the sealed question-set digest.

### Rationale

Source: ANC-023; INTENT "Review policy". Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A look at the planner instructions shows the planner launches one named `anchor-tuning` subagent concurrently after the first draft and INTENT/ANC capture.
- [ ] A look at the planner instructions shows leaf plan review waits for the sealed question-set digest.

## REQ-PA-0041: anchor-tuning INTENT/ANC refinement recommendations

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- `anchor-tuning` may recommend clarity-only INTENT/ANC refinements but shall not apply them; the user approves each, and approval invalidates the affected oracles and rankings.

### Rationale

Source: ANC-024, ANC-025. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test runs `anchor-tuning` and finds INTENT/ANC records unchanged, with any clarity-only refinements returned only as recommendations.
- [ ] A test finds each recommended refinement is applied only after the user approves that refinement.
- [ ] A test approves a refinement and finds the affected oracles and rankings marked invalid.

## REQ-PA-0042: Disputed failure handoff to anchor-tuning

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- After plan review, disputed failures shall go to `anchor-tuning` only through a checked-in `sc-compose` Jinja2 template, and the tuner shall return exactly one of `plan_violation` (question digest unchanged) or `question_defect`.

### Rationale

Source: ANC-028, ANC-029, ANC-030. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] After plan review, disputed failures go to `anchor-tuning` only through a checked-in `sc-compose` Jinja2 template.
- [ ] A test of the tuner's result on a disputed failure returns exactly one of `plan_violation` or `question_defect`.
- [ ] When the tuner returns `plan_violation`, the question digest is unchanged.

## Python and CLI contract

## REQ-PA-0051: Typed agent launch failure reasons

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Every agent launch shall report a typed failure reason, and failures shall never fall back silently.

### Rationale

Source: OPERATOR; `design/anchor-tuning-stand-ins.md` "Failures". Status: shipped for runner contract failures.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test shows every failed agent launch reports a typed failure reason.
- [ ] A test shows an agent launch failure does not fall back silently.

## Documentation and packaging

## REQ-PA-0057: Gate sprint text input and tracker use

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Both gates shall judge the sprint text the calling agent supplies through `judge --item-file` (or stdin), read from wherever that agent wrote the plan, with no plan parsing or format requirement; anchor records shall use only the tracker `anchor_tracker.py` resolves, and installed skill and agent text shall name only the installed tracker's commands.

### Rationale

Source: OPERATOR (2026-10-17); INTENT "Success"; ADR-PA-0014; ANC-016; ANC-017. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] Both gates judge the sprint text supplied through `judge --item-file` or stdin, read from where the calling agent wrote the plan.
- [ ] The gates apply no plan parsing or format requirement to the sprint text.
- [ ] Anchor records use only the tracker `anchor_tracker.py` resolves.
- [ ] Installed skill and agent text names only the installed tracker's commands.

## Installer

## Remote-judge consent

## REQ-PA-0065: allow_remote_judge consent setting

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- Consent to send plan text to TypeSafe shall be `allow_remote_judge: true|false` in the committed `.sc/plan-anchor/settings.yaml` (the nearest file), never an environment variable and never inferred from past runs; the answer recorded with `plan_anchor_settings.py set allow_remote_judge true|false`.

### Rationale

Source: OPERATOR (2026-10-17); OPERATOR (phase j plan-review ruling, 2026-11-24) (consent covers TypeSafe only). Status: shipped (0.7.1).

### Success Criteria

**Acceptance Criteria:**

- [ ] Consent to send plan text to TypeSafe is read from `allow_remote_judge: true|false` in the nearest committed `.sc/plan-anchor/settings.yaml`.
- [ ] A test sets an environment variable and leaves past runs present, with `allow_remote_judge` unset, and consent is not granted.
- [ ] `plan_anchor_settings.py set allow_remote_judge true|false` records the answer in `.sc/plan-anchor/settings.yaml`.

## Per-folder installs (0.8.0)

## Judging and installer details

## REQ-PA-0075: Anchor kind values and gating

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- An anchor's `kind` shall be `directive` (the default, and the reading of a record without one), `prohibition` or `structural`, set by `add --kind` or `update --kind` and checked by `validate`. A prohibition ignores compliance: `not_applicable` on a confident relevance `no`, `contradicted` on a confident conflict `yes`, `underspecified` when relevance is unclear or below the threshold or conflict is not a confident `no`, `asserted_only` when the development gate's evidence is a confident `no`, else `satisfied`. A structural anchor is never sent to Jev at the planning gate (verdict `deterministic_only`, which passes, also in `check-fixtures`) and is gated as a directive at the development gate.

### Rationale

Source: CHANGELOG 0.3.0. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test shows an anchor's `kind` is `directive` by default and for a record without one, accepts `prohibition` or `structural` through `add --kind` or `update --kind`, and is checked by `validate`.
- [ ] A test shows a prohibition ignores compliance and yields `not_applicable` on a confident relevance `no`, `contradicted` on a confident conflict `yes`, `underspecified` when relevance is unclear or below the threshold or conflict is not a confident `no`, `asserted_only` when the development gate's evidence is a confident `no`, else `satisfied`.
- [ ] A test shows a structural anchor is not sent to Jev at the planning gate and gets verdict `deterministic_only`, which passes, also in `check-fixtures`.
- [ ] A test shows a structural anchor is gated as a directive at the development gate.

## REQ-PA-0076: Near-threshold confirmation re-ask

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- When a live answer to a gating role (not a prohibition's compliance) is within 0.10 of the threshold, `judge` and `check-fixtures` shall send the identical request once more with `cache=False`, so that the second send is a new Jev call with its own session row and not a result-cache hit: agreement sets `confirmed`; disagreement makes the cell `underspecified` with `unstable`, both verdicts and both `session_id`s; a second call with no answer keeps the first verdict, records `confirm_error` and exits 2 (REQ-050). It is on by default; `--no-confirm` turns it off and `--confirm-near-threshold` only states the default; fixture answers are never re-asked. Every judged result carries `leaning` (the verdict at threshold 0), and an `underspecified` one carries `low_questions`. When `--repeat` of `batch` or `bead-batch`, or the tournament request's `repeat_count`, is greater than 1, every repeat shall be sent with `cache=False`, all repeats in one call that keeps their order, so that each repeat is its own Jev call with its own `session_id`. The second and third testability confirmations of `rubric` and `add --rubric` shall also be sent with `cache=False`.

### Rationale

Source: CHANGELOG 0.3.0, 0.7.3; OPERATOR (phase j session-log ruling, 2026-11-24). Status: shipped; planned for `cache=False` and both `session_id`s in place of the second answers (phase j).

Source: OPERATOR (phase j session-log ruling, 2026-11-24); OPERATOR (phase j ruling, 2026-11-24); `skills/plan-anchoring/references/question-tuning.md` "Run". Status: planned (phase j; today `_rubric_judgement` in `jev_judge.py.j2` re-asks with the cache on).

### Success Criteria

**Acceptance Criteria:**

- [ ] A test with a live gating-role answer (not a prohibition's compliance) within 0.10 of the threshold finds `judge` and `check-fixtures` send the identical request once more with `cache=False`, producing a new Jev call with its own session row.
- [ ] A test finds agreement sets `confirmed`, and disagreement makes the cell `underspecified` with `unstable`, both verdicts and both `session_id`s.
- [ ] A test where the second call returns no answer finds the first verdict kept, `confirm_error` recorded and exit 2.
- [ ] Tests find the re-ask runs by default, does not run with `--no-confirm`, is not re-asked for fixture answers, and every judged result carries `leaning` with each `underspecified` result also carrying `low_questions`.
- [ ] A test shows that with `--repeat` of `batch` or `bead-batch`, or the tournament request's `repeat_count`, greater than 1, every repeat is sent with `cache=False`, all repeats in one call that keeps their order, each repeat a separate Jev call with its own `session_id`.
- [ ] A test shows the second and third testability confirmations of `rubric` and `add --rubric` are sent with `cache=False`.

## REQ-PA-0078: Record subcommands and version bumps

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The record subcommands shall be `add` (`--status proposed|locked`, default `proposed`; `--stated-by` defaults to `USER`), `update`, `retire`, `exclude` (`--remove`), `set-beads`, `promote --adr` and `render`; `retire` and `promote` bump `version`, `exclude` and `set-beads` do not, and `promote` does not check the anchor's status. No subcommand moves `proposed` to `locked` or writes `question_overrides`, which `judge` still reads from the record before `--overrides-file`.

### Rationale

Source: CHANGELOG 0.2.0, 0.3.0; `design/data-model-and-gating.md` §2, §6. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] The record CLI offers `add` (`--status proposed|locked`, default `proposed`; `--stated-by` default `USER`), `update`, `retire`, `exclude` (`--remove`), `set-beads`, `promote --adr` and `render`.
- [ ] Tests show `retire` and `promote` bump `version`, `exclude` and `set-beads` leave `version` unchanged, and `promote` runs regardless of the anchor's status.
- [ ] Tests show no subcommand moves `proposed` to `locked` or writes `question_overrides`.
- [ ] A test shows `judge` reads `question_overrides` from the record before `--overrides-file`.

## REQ-PA-0079: compose-item and shape commands

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- `compose-item` shall build the item text from a tracker `show --json` (`--show-json`, `-` for stdin), optional `--children-json` and `--sections`; `--for plan` keeps the description and acceptance criteria and drops children. `shape` shall report size and shape metrics and never gate.

### Rationale

Source: CHANGELOG 0.3.0. Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] A test runs `compose-item` with `--show-json` from a file and with `-` for stdin, with optional `--children-json` and `--sections`, and the item text is built from those inputs.
- [ ] A test runs `compose-item --for plan` and the item text keeps the description and acceptance criteria and drops children.
- [ ] A test runs `shape` and the output reports size and shape metrics and does not gate.

## REQ-PA-0081: Gate agent stop on TRACKER.SHOW_FAILED

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- When a gate agent's question bead cannot be shown by the tracker, the agent shall stop with `TRACKER.SHOW_FAILED` rather than judge with the default questions.

### Rationale

Source: CHANGELOG 0.8.3. Status: shipped (prompt text in `anchor-plan-review` and `anchor-sprint-review`).

### Success Criteria

**Acceptance Criteria:**

- [ ] A look at the `anchor-plan-review` and `anchor-sprint-review` prompts finds the instruction to stop with `TRACKER.SHOW_FAILED` when the tracker cannot show the question bead, instead of judging with the default questions.
- [ ] A test where the tracker cannot show the question bead finds the gate agent returns `TRACKER.SHOW_FAILED` and no verdicts from the default questions.

## REQ-PA-0088: Anchor record location and plan_dir setting

**Status:** shipped  

### Requirement Statement

**MUST statements:**

- The anchor record (`intent.md`, `anchors.json`, `anchors.md`, `anchor-runs/`) shall live in the current phase's plan folder, `docs/plans/phase-<current>/` with the phase id written out, named by `plan_dir` in `.sc/plan-anchor/settings.yaml`. `plan_anchor_settings.py set plan_dir` records it and `show` reports it; a value that is absolute, has an empty, `.` or `..` part, a backslash or a `<placeholder>` is `SETTINGS.INVALID_PLAN_DIR` in the file and `VALIDATION.INPUT` on `set`; the installer and `anchor_tracker.py write` keep it. The skill sets `A="$P/anchors.json"` from it and asks the user when it is unset; no shipped file names a literal folder. A new record's `plan` and `intent_ref` default to the folder holding `--anchors` and `intent.md` beside it.

### Rationale

Source: OPERATOR (issue #58, 0.8.6). Status: shipped.

### Success Criteria

**Acceptance Criteria:**

- [ ] The anchor record (`intent.md`, `anchors.json`, `anchors.md`, `anchor-runs/`) lives in `docs/plans/phase-<current>/` with the phase id written out, named by `plan_dir` in `.sc/plan-anchor/settings.yaml`.
- [ ] `plan_anchor_settings.py set plan_dir` records `plan_dir`, `show` reports it, and the installer and `anchor_tracker.py write` keep it.
- [ ] Tests give a `plan_dir` that is absolute, has an empty, `.` or `..` part, a backslash or a `<placeholder>`, and each is `SETTINGS.INVALID_PLAN_DIR` in the file and `VALIDATION.INPUT` on `set`.
- [ ] The skill sets `A="$P/anchors.json"` from `plan_dir` and asks the user when `plan_dir` is unset, no shipped file names a literal folder, and a new record's `plan` and `intent_ref` default to the folder holding `--anchors` and `intent.md` beside it.

## Session log and run records (phase j)

## Session log and run records (phase j)

## REQ-PA-0083: Dry-run behavior

**Status:** planned  

### Requirement Statement

**MUST statements:**

- A `--dry-run` shall only check that its input composes into valid requests and show the would-send requests, redacted, on stdout, or in the file named by `--out` (for `judge`, `--out` names the requests file on a dry run). A dry run shall write no file under `anchor-runs/`, no run file, no result line and no log event. A `--out` path inside `anchor-runs/` on a dry run shall be refused with `VALIDATION.INPUT`. `--dry-run` and `--answers-file` execution shall make zero network calls.

### Rationale

Source: OPERATOR (phase j session-log ruling, 2026-11-24); INTENT "Success"; retired ANC-006 (requirement retained). Status: planned (phase j; today a dry run writes a run file marked `dry_run`, and `tournament --dry-run` writes `requests.dry-run.jsonl` in `--out`).

### Success Criteria

**Acceptance Criteria:**

- [ ] A test runs `--dry-run` and the input is checked to compose into valid requests and the would-send requests are shown redacted on stdout, or in the file named by `--out` (for `judge`, the requests file).
- [ ] After a dry run, no file is written under `anchor-runs/`, and no run file, result line or log event exists.
- [ ] A dry run with a `--out` path inside `anchor-runs/` is refused with `VALIDATION.INPUT`.
- [ ] A test runs with `--dry-run` with network access blocked and records zero network calls.
- [ ] A test runs with `--answers-file` with network access blocked and records zero network calls.

