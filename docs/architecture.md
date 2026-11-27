# sc-plan-anchor architecture decisions

**Status:** Active  
**Version:** 0.14.0  
**Created:** 2026-10-17  
**Last Updated:** 2026-11-26  
**Owner:** Rand Lee  
**Decision Date:** 2026-10-09  

Numbered decisions for the `plan-anchoring` skill. Components, call graphs,
the retry sequence and harness execution are already drawn in
[design/architecture-and-call-graphs.md](design/architecture-and-call-graphs.md);
the record schema, verdict table and anchor lifecycle are in
[design/data-model-and-gating.md](design/data-model-and-gating.md). This file
records only the decisions and why; requirements are in
[requirements.md](requirements.md).

Statuses describe the code at 0.8.3 (`fix/0.8.3-errors`): `accepted` (built and in
force), `partial` (built, with the named deviations), `planned` (decided, not
built), `superseded` (replaced by the named ADR) or `retired` (withdrawn).
Dates are when the decision first landed or was made.

## ADR-PA-0001: Exact work in the script, judgment in the session and Jev

**Status:** accepted  
**Decision Date:** 2026-10-09  

Status: accepted (amended for 0.12.1). Date: 2026-10-09.

### Context

Facts stated during planning are lost as context compresses, and
language models cannot count, gate reliably, or keep a request byte-identical.

### Decision

Three tiers. `scripts/jev_judge.py` owns IDs, request composition,
gating, run files, coverage, diffs and reports. Live calls use the lazily
imported `sc-decidr` wheel through the generated `decidr_client.py`.
The main session owns capture, approval and triage. Jev answers independent typed questions about one
anchor and one item. Agents run the script once and return its result. See
§1 of the call-graph document.

### Rationale

Facts stated during planning are lost as context compresses, and language models cannot count, gate reliably, or keep a request byte-identical. Putting the exact work in the script makes gating and coverage reproducible and unit-tested offline, while judgment stays with the session and Jev, which never sees more than one anchor and one item.

### Alternatives Considered

#### Alternative 1: Language models do the exact work

**Description:** The session or its agents count, gate, compose requests and retry on their own.

**Why Rejected:** Language models cannot count, gate reliably, or keep a request byte-identical.

### Consequences

Gating and coverage are reproducible and unit-tested offline.
Agents may not add retry loops or compute verdicts. Jev never sees more than
one anchor and one item. REQ-PA-0009, REQ-PA-0010.

## ADR-PA-0002: Jev payload: anchor, item, questions; intent is not sent

**Status:** accepted  
**Decision Date:** 2026-10-09  

Status: accepted. Date: 2026-10-09.

### Context

Jev accuracy degrades as unrelated text grows (a planted
contradiction 28k bytes deep scored 0.46 against 0.79 near the top). Cutting
prose to fit removed evidence Jev used
([experiment](experiments/2026-10-10-redact-only-when-oversize.md)).

### Decision

The request is `state.anchor {id, statement, scope}`,
`state.item {id, title, text}` and the gate's question set. Intent and source
metadata are not sent, so each sprint must stand alone as a fresh developer
would read it. Prose is never cut.

### Rationale

Jev's accuracy falls as unrelated text grows: a planted contradiction deep in a long request scored 0.46 against 0.79 near the top, so the request carries only the anchor, the item and the questions. Prose is never cut because cutting it to fit removed evidence Jev relied on. Gaps in cross-sprint context then surface as not_addressed or underspecified verdicts and are fixed in the sprint text itself.

### Consequences

Missing cross-sprint context shows up as `not_addressed` or
`underspecified` and is fixed in the sprint text. REQ-PA-0007, REQ-PA-0008.

## ADR-PA-0003: Relevance gating threshold

**Status:** accepted  
**Decision Date:** 2026-10-09  

Status: accepted. Date: 2026-10-09.

### Context

Answers to the questions in one request are independent, so relevance
cannot gate the others inside Jev. A wavering relevance answer must not be
read as "does not apply".

### Decision

`decide()` applies relevance first: `no` at confidence ≥ 0.6 is
`not_applicable`; anything weaker falls through and, without a confident
compliance `yes` and a confident conflict `no`, ends as `underspecified`.
Contradiction outranks underspecification. The anchor's `kind` changes which
roles gate: a `prohibition` ignores compliance, and a `structural` anchor is
not sent to Jev at the planning gate (`deterministic_only`, passing) and is
gated as a directive at the development gate. A live answer within 0.10 of the
threshold is asked again and must agree, else the cell is `underspecified`
(`unstable`); `--no-confirm` turns this off. The re-ask is sent with
`cache=False`, so it is a new Jev call and not a result-cache hit (ADR-PA-0017).
Full order in §4 of the data-model document.

### Rationale

Answers to the questions in one request are independent, so relevance cannot gate the others inside Jev and has to be applied afterwards. A wavering relevance answer is not to be read as "does not apply", so only a confident relevance no counts as not applicable and weaker answers fall through.

### Alternatives Considered

#### Alternative 1: Relevance gates the other questions inside Jev

**Description:** Jev skips the other questions when relevance is `no`.

**Why Rejected:** Answers to the questions in one request are independent, so relevance cannot gate the others inside Jev.

#### Alternative 2: Any relevance `no` is not applicable

**Description:** A relevance `no` at any confidence makes the cell `not_applicable`.

**Why Rejected:** A wavering relevance answer must not be read as "does not apply".

### Consequences

Cells near 0.6 on unrelated sprints can fail as
`underspecified`; REQ-PA-0006 adds an explicit exclusion for that case rather than
changing the threshold. REQ-PA-0009, REQ-PA-0075, REQ-PA-0076.

## ADR-PA-0004: Tracker: br or bd, selected once

**Status:** accepted  
**Decision Date:** 2026-10-17  

Status: accepted. Date: 2026-10-17.

### Context

Consumers use either `br` or `bd`, which do not share a storage
format, and `bd` needs a Dolt backend this skill cannot provision.

### Decision

`anchor_tracker.py resolve` selects once per repository. An explicit
`anchor_tracker` in committed `.sc/plan-anchor/settings.yaml` wins and is
checked against disk. Otherwise a Dolt-backed `.beads/` selects `bd`, any other
`.beads/` selects `br`, and none selects `br` (`write --init` may run
`br init`). The skill never runs or recommends `bd init`. A mismatch is a typed
error; there is no fallback to the other CLI. Both gate reviewers re-resolve
and reject a mismatch. plan-anchor itself pins `br`. The settings file in
effect is the nearest one at or above the repository (ADR-015); the disk check
runs in every repository, including against an inherited setting. The
installer (ADR-015) applies the same rules when it renders and writes the
setting. Since 0.8.2 the installer is the only code that applies them to both
trackers: an installed `anchor_tracker.py` is rendered for one tracker
(ADR-015) and refuses a setting naming the other (`SETTINGS.INVALID_TRACKER`)
or a `.beads/` that does not fit it (`TRACKER.MISMATCH` in a `br` install,
`TRACKER.DOLT_REQUIRED` in a `bd` install), pointing at the installer's
`--tracker`. `resolve` prints the tracker in JSON; the calling agent sets
`$ANCHOR_TRACKER` from it.

### Rationale

Consumers use either br or bd, which do not share a storage format, and bd needs a Dolt backend the skill cannot provision, so the tracker is chosen once per repository rather than guessed per call or swapped on failure. Selecting it once keeps anchor storage and both gates tracker-neutral.

### Consequences

Anchor storage and both gates are tracker-neutral. REQ-PA-0021 to
REQ-PA-0025.

## ADR-PA-0008: Harness-specific agents behind one trusted runner

**Status:** accepted  
**Decision Date:** 2026-10-11  

Status: accepted. Date: 2026-10-11.

### Context

Claude Code, Codex and Cursor differ in launch syntax and model
names. Letting each agent search install paths and validate itself duplicated
trust logic.

### Decision

Each harness has its own `agents/` directory and registry, with
bodies identical after frontmatter. Gate agents use Sonnet, Luna or Composer;
the tuner uses Opus, Sol or Grok at high effort. Claude and Codex launch with
the Agent tool, Cursor with its Task tool. `anchor_runner_contract.py` resolves
path, version, model and hash once, and every invocation and result is one
fenced JSON object; agent inputs carry validated identifiers, never command
strings. Which `jev_judge.py` an agent may run is ADR-015's trust rule (the
nearest per-folder install). See §5 of the call-graph document.

### Rationale

Claude Code, Codex and Cursor differ in launch syntax and model names, so each harness gets its own agents and registry. Letting each agent search install paths and validate itself duplicated trust logic, so path, version, model and hash are resolved once by a single runner instead of by the agents.

### Consequences

Drift between harness copies (`install/harness/<target>/` and
the rendered agent bodies) fails CI. The registry and agent identity are
resolved by the runner, not the agents. REQ-PA-0031 to REQ-PA-0034.

## ADR-PA-0010: Independent question tuning

**Status:** accepted  
**Decision Date:** 2026-10-11  

Status: accepted. Date: 2026-10-11.

### Context

A planner that tunes its own questions tunes them toward a pass.

### Decision

A dedicated `anchor-tuning` subagent of the planner, launched
concurrently after the first draft and INTENT/ANC capture, treats approved
INTENT and ANC as its only authority, freezes an oracle before seeing Jev
answers, judges a candidate pool larger than production in parallel, and
seals a smaller production set. Its Jev queries go only through
`jev_judge.py tournament`, which sends each one through sc-agent `send`, so
every query has a row in the sc-agent session log (ADR-PA-0017); the tuner never
calls Jev another way. It tests on temporary plan copies only and never
edits authoritative sources. It may recommend clarity-only INTENT/ANC changes;
the user approves each. Disputed review
failures reach it only through a checked-in `sc-compose` template, and it
returns exactly `plan_violation` or `question_defect`. No desired verdict is
an input; `anchor_tuning_contract.py` rejects one.

### Rationale

A planner that tunes its own questions tunes them toward a pass, so tuning is handed to a separate subagent whose only authority is the approved INTENT and anchors. For the same reason, a planner's claim that the plan is fine and the questions should be fixed is treated as untrusted context.

### Alternatives Considered

#### Alternative 1: The planner tunes its own questions

**Description:** The planner that wrote the plan also tunes the questions that judge it.

**Why Rejected:** A planner that tunes its own questions tunes them toward a pass.

### Consequences

Leaf plan review waits for the sealed digest. A planner's "the
plan is fine, fix the questions" is untrusted context. REQ-PA-0037 to REQ-PA-0042.

## ADR-PA-0014: The calling agent supplies the plan text; no gate parses plans

**Status:** accepted  
**Decision Date:** 2026-10-17  

Status: accepted. Date: 2026-10-17.

### Context

The skill anchors Markdown plans and `bd`/`br` plans alike. ADR-005
put `plan_source.py` between the plan and the gates: it accepts only a
`plan-phase-*.md` index with a fixed sprint table and fixed `Authoritative ...`
headings, or a tracker epic copied in that shape. Real plans are not written
that way. On atm-core's phase-bi (`bd`, sprint beads with `Goal`,
`Deliverables`, `Does Not Close`), both `discover-tracker` (`SOURCE.PHASE_ID`)
and `discover-markdown` (`SOURCE.PHASE_INDEX`) refuse the plan. ADR-PA-0004 also
left the development gate calling `bd` directly.

### Decision

The calling agent wrote the plan to its medium, knows that medium,
and reads the sprint back from it (the Markdown file, `br show`, `bd show`, or
its own context). It passes that text to `jev_judge.py judge --item-id
--item-title --item-file` (or stdin) for both gates. No gate parses, discovers
or normalizes plans. Anchor and question records live in the tracker
`anchor_tracker.py` resolves (ADR-PA-0004), which the installer selects; installed
text names only that tracker's commands.

### Rationale

Real plans are not written in the fixed shape the earlier plan parser accepted; on atm-core's phase-bi both discovery commands refused the plan. The calling agent wrote the plan and knows its medium, so having it supply the text lets any plan format work and keeps the plan format and the anchor tracker independent choices.

### Consequences

Any plan format works, and the plan's format and the anchor
tracker are independent choices. Markdown-versus-tracker-copy parity is no longer checked by
the skill; the plan's author owns it. `plan_source.py` and its contract are
not shipped. REQ-PA-0021, REQ-PA-0057.

## ADR-PA-0017: Jev queries are recorded once, in sc-agent's session log

**Status:** accepted  
**Decision Date:** 2026-11-24  

Status: accepted at phase j plan review, 2026-11-24; binding on sprint j-4,
which builds it when it merges into plan-anchor's integrate/phase-j.
Date: 2026-11-24.

### Context

Every Jev query from every tool goes through sc-agent `send` or
`send_batch` and gets one session-log row keyed by its ULID `session_id`
(owner ruling, 2026-11-24). Run files, result lines and the tournament log
copied the answers, `model_answered` and attempt counts that the row already
holds.

### Decision

Plan-anchor's records hold only what it derives (verdicts, leaning,
rankings) and its own ids (`anchor_id`, `candidate_id`, repeat), and reference
the `session_id` of each query they used. They never copy the composed request body, Jev's
answers, `model_answered` or attempt counts.

### Rationale

Every Jev query from every tool already goes through sc-agent send or send_batch and gets one session-log row keyed by its session_id, per the owner ruling of 2026-11-24. Run files, result lines and the tournament log were copying answers, model_answered and attempt counts that the row already holds, so plan-anchor keeps only what it derives and references the row instead.

### Alternatives Considered

#### Alternative 1: Copy answers into plan-anchor's records

**Description:** Run files, result lines and the tournament log keep the request body, answers and attempt counts.

**Why Rejected:** The session-log row already holds them.

### Consequences

Reading an answer, or rescoring a tournament with `--results`,
needs the sc-agent session log. REQ-PA-0013, REQ-PA-0038, REQ-PA-0076, REQ-PA-0083.
