# sc-plan-anchor architecture decisions

Numbered decisions for the `plan-anchoring` skill. Components, call graphs,
the retry sequence and harness execution are already drawn in
[design/architecture-and-call-graphs.md](design/architecture-and-call-graphs.md);
the record schema, verdict table and anchor lifecycle are in
[design/data-model-and-gating.md](design/data-model-and-gating.md). This file
records only the decisions and why; requirements are in
[requirements.md](requirements.md).

Status is `accepted` (in force on `main`), `planned` (decided, not built), or
`partial` (decided, built in some modules only). Dates are when the decision
first landed or was made.

## ADR-001 Exact work in the script, judgment in the session and Jev

Status: accepted. Date: 2026-10-09.

Context: Facts stated during planning are lost as context compresses, and
language models cannot count, gate reliably, or keep a request byte-identical.

Decision: Three tiers. `scripts/jev_judge.py` owns IDs, request composition,
gating, retries, run files, coverage, diffs and reports. The main session owns
capture, approval and triage. Jev answers independent typed questions about one
anchor and one item. Agents run the script once and return its result. See
§1 of the call-graph document.

Consequences: Gating and coverage are reproducible and unit-tested offline.
Agents may not add retry loops or compute verdicts. Jev never sees more than
one anchor and one item. REQ-009, REQ-010, REQ-011.

## ADR-002 Jev payload: anchor, item, questions; intent is not sent

Status: accepted. Date: 2026-10-09 (24k cap 2026-10-10).

Context: Jev accuracy degrades as unrelated text grows (a planted
contradiction 28k bytes deep scored 0.46 against 0.79 near the top). Cutting
prose to fit removed evidence Jev used
([experiment](experiments/2026-10-10-redact-only-when-oversize.md)).

Decision: The request is `state.anchor {id, statement, scope}`,
`state.item {id, title, text}` and the gate's question set. Intent and source
metadata are not sent, so each sprint must stand alone as a fresh developer
would read it. The planning request cap is 24,000 bytes. Prose is never cut;
only the longest fenced code blocks are reduced to signatures, and only when
the bead does not otherwise fit; a bead that still does not fit is refused as
`PLAN.TOO_LARGE`. The development gate keeps its 64,000-byte evidence cap with
tail shortening.

Consequences: Oversize plans are fixed by triage or splitting, never by
raising the cap. Missing cross-sprint context shows up as `not_addressed` or
`underspecified` and is fixed in the sprint text. REQ-007, REQ-008.

## ADR-003 Relevance gating threshold

Status: accepted. Date: 2026-10-09.

Context: Answers to the questions in one request are independent, so relevance
cannot gate the others inside Jev. A wavering relevance answer must not be
read as "does not apply".

Decision: `decide()` applies relevance first: `no` at confidence ≥ 0.6 is
`not_applicable`; anything weaker falls through and, without a confident
compliance and conflict answer, ends as `underspecified`. Contradiction
outranks underspecification. Full order in §4 of the data-model document.

Consequences: Cells near 0.6 on unrelated sprints can fail as
`underspecified`; ADR-012 adds an explicit exclusion for that case rather than
changing the threshold. REQ-009.

## ADR-004 Tracker: br or bd, selected once

Status: accepted. Date: 2026-10-17.

Context: Consumers use either `br` or `bd`, which do not share a storage
format, and `bd` needs a Dolt backend this skill cannot provision.

Decision: `anchor_tracker.py resolve` selects once per repository. An explicit
`anchor_tracker` in committed `.sc/plan-anchor/settings.yaml` wins and is
checked against disk. Otherwise a Dolt-backed `.beads/` selects `bd`, any other
`.beads/` selects `br`, and none selects `br` (`write --init` may run
`br init`). The skill never runs or recommends `bd init`. A mismatch is a typed
error; there is no fallback to the other CLI. The planning reviewer re-resolves
and rejects a mismatch. plan-anchor itself pins `br`.

Consequences: Anchor storage and the planning gate are tracker-neutral. The
development gate's `bd`-only carve-out is reversed by ADR-014. REQ-021 to
REQ-025.

## ADR-005 Plan sources: Markdown authoritative, tracker copy equivalent

Status: superseded by ADR-014. Date: 2026-10-11.

Context: Plans are written as Markdown, but some teams keep a tracker copy;
the two must not judge differently.

Decision: `scripts/plan_source.py` normalizes a phase index plus authoritative
sprint documents, or a tracker epic copy, to the same ordered items and
byte-identical Jev request bodies. Markdown is authoritative when both exist.
Markdown review needs tracker records only for anchor roots and their question
children. Structural defects and copy drift fail before delegation.

Consequences: Differing answers to identical requests are model instability,
not adapter drift. A single unstructured Markdown plan is not accepted.
REQ-027 to REQ-029.

## ADR-006 Python: stdlib, 3.9 floor, Result for expected failures

Status: partial. Date: 2026-10-17.

Context: Scripts run inside agent sessions on any developer machine, and the
calling agent needs a typed failure, not a traceback.

Decision: Standard library only on Python 3.9+, except PyYAML for settings,
imported lazily. Expected failures are returned as `Result[T, E]` from
`scripts/result.py`: frozen `Ok`/`Err` dataclasses with a literal `ok`
discriminant and a `ToolError {code, message, action, data}`. Exceptions are
for bugs; the CLI boundary converts them to `SCRIPT.INTERNAL`. All Python is
unit-tested; CI runs ubuntu, macOS and Windows on 3.9 and 3.x, plus a no-PyYAML
and PyYAML-floor job.

Consequences: `plan_anchor_settings.py` and `anchor_tracker.py` follow it.
`jev_judge.py` (`JudgeError`), `plan_source.py` (`SourceError`),
`anchor_runner_contract.py` (`RunnerContractError`) and
`anchor_tuning_contract.py` (`ContractError`) still raise; their conversion is
stack layer 2 of the stand-ins plan, with no behavior change. REQ-047,
REQ-048, REQ-052.

## ADR-007 CLI contract: JSON envelope, exit 2 for errors

Status: partial. Date: 2026-10-17.

Context: Agents branch on exit code and parse stdout; an error that looks like
a negative answer, or a non-JSON error, sends them down the wrong path.

Decision: Every command prints `{success, data, error}`; errors carry
`{code, message, recoverable, suggested_action}`. Exit 0 is success, exit 1 is
only a completed run whose answer is negative (failing gate, lint warnings,
fixture mismatch), and exit 2 is any error. Agent launches report a typed
failure reason.

Consequences: `anchor_tracker.py`, `plan_source.py` and
`anchor_runner_contract.py` comply. `jev_judge.py` exits 2 for raised errors
but 1 for a `judge` run containing per-anchor `error` verdicts (transport
failures after retries) and for any returned `success: false` envelope.
`anchor_tuning_contract.py` exits 1 on invalid input and prints
`{valid, error}`. Both are to be aligned. REQ-049 to REQ-051.

## ADR-008 Harness-specific agents behind one trusted runner

Status: accepted. Date: 2026-10-11.

Context: Claude Code, Codex and Cursor differ in launch syntax and model
names. Letting each agent search install paths and validate itself duplicated
trust logic.

Decision: Each harness has its own `agents/` directory and registry, with
bodies identical after frontmatter. Gate agents use Sonnet, Luna or Composer;
the tuner uses Opus, Sol or Grok at high effort. Claude and Codex launch with
the Agent tool, Cursor with its Task tool. `anchor_runner_contract.py` resolves
path, version, model and hash once, and every invocation and result is one
fenced JSON object; agent inputs carry validated identifiers, never command
strings. See §5 of the call-graph document.

Consequences: Drift between harness copies fails CI. Agents contain no
installation search. REQ-030 to REQ-034.

## ADR-009 Separate planning and code-review gates

Status: planned. Date: 2026-10-17.

Context: Both gates run today through `jev_judge.py judge --gate plan|dev` and
share code paths, so a change for one can move the other. Plan review is in
production use; code review is not.

Decision: The planning gate and the code-review gate become separate agents
with separate Python entry points.

Consequences: The production plan-review path can be hardened and released
without carrying development-gate changes. The shared judge core stays in one
module. REQ-036.

## ADR-010 Independent question tuning

Status: accepted. Date: 2026-10-11.

Context: A planner that tunes its own questions tunes them toward a pass.

Decision: A dedicated `anchor-tuning` subagent of the planner, launched
concurrently after the first draft and INTENT/ANC capture, treats approved
INTENT and ANC as its only authority, freezes an oracle before seeing Jev
answers, calls Jev directly and in parallel over a candidate pool larger than
production, and seals a smaller production set. It tests on temporary plan
copies only and never edits authoritative sources. It may recommend
clarity-only INTENT/ANC changes; the user approves each. Disputed review
failures reach it only through a checked-in `sc-compose` template, and it
returns exactly `plan_violation` or `question_defect`. No desired verdict is
an input; `anchor_tuning_contract.py` rejects one.

Consequences: Leaf plan review waits for the sealed digest. A planner's "the
plan is fine, fix the questions" is untrusted context. REQ-037 to REQ-042.

## ADR-011 Fast-model stand-ins for tuning

Status: planned. Date: 2026-10-17.

Context: Jev returns choices and confidence but no reason, so a failing cell
cannot be asked why. Predicted (counterfactual) answers from models proved
unreliable.

Decision: `judge --stand-ins` sends the identical Jev request to fast models
(Claude `haiku`, Codex `luna`) configured under `fast_agents.profiles` in
settings, one session per cell per model with no tools in an empty temp dir,
validated by `validate_response`. Stand-in output is advisory and never gates;
divergence from Jev is a signal that the question and the text are misaligned.
`follow-up` resumes the session of the model that answered. The tuner stays
neutral, always runs the follow-up turns, makes one small edit (usually the
sprint's `Prerequisites` or `Additional context`) and re-runs. The ledger is
one commit per edit, a notes table row per iteration and `jev_judge.py diff`;
no ledger CLI. Source: `design/anchor-tuning-stand-ins.md` (draft).

Consequences: Tuning gains an explanation channel without a second verdict.
Settings validation must accept `fast_agents`. The draft's "a stand-in error
makes the run exit 1" conflicts with ADR-007 and must be settled before
layer 3. REQ-020, REQ-043 to REQ-046.

## ADR-012 Anchor exclusions as a plain skip

Status: planned. Date: 2026-10-17.

Context: An anchor that plainly does not apply to an unrelated sprint can still
fail as `underspecified` when relevance wavers near 0.6 (ADR-003).

Decision: An anchor may carry `exclude: [{item, reason}]`. `judge` skips those
cells and reports them as `excluded` with the reason in the run summary and in
`anchors.md`. There is no approval workflow and no other new verdict state.

Consequences: Exclusions are visible and retrievable, and the threshold is
unchanged. REQ-006.

## ADR-013 Repository settings convention

Status: accepted. Date: 2026-10-17.

Context: Behavior varied by machine and environment variable; the skill needs
one committed place for per-repository choices.

Decision: `.sc/<package>/settings.yaml`, here `.sc/plan-anchor/settings.yaml`:
YAML, snake_case, committed, never secrets, `schema_version: 1`, strict
validation (unknown and duplicate keys and wrong types rejected), modeled on
pydantic strictness but implemented with the standard library.

Consequences: A typo never falls back to a default. `TYPESAFE_API_KEY` stays an
environment variable because it is a secret. Several `PLAN_ANCHOR_*`
environment variables are still read by `jev_judge.py`, contrary to ANC-005;
they are candidates to move to CLI flags or settings. REQ-018, REQ-019.

## ADR-014 The calling agent supplies the plan text; no gate parses plans

Status: planned. Date: 2026-10-17. Supersedes ADR-005.

Context: The skill anchors Markdown plans and `bd`/`br` plans alike. ADR-005
put `plan_source.py` between the plan and the gates: it accepts only a
`plan-phase-*.md` index with a fixed sprint table and fixed `Authoritative ...`
headings, or a tracker epic copied in that shape. Real plans are not written
that way. On atm-core's phase-bi (`bd`, sprint beads with `Goal`,
`Deliverables`, `Does Not Close`), both `discover-tracker` (`SOURCE.PHASE_ID`)
and `discover-markdown` (`SOURCE.PHASE_INDEX`) refuse the plan. ADR-004 also
left the development gate calling `bd` directly.

Decision: The calling agent wrote the plan to its medium, knows that medium,
and reads the sprint back from it (the Markdown file, `br show`, `bd show`, or
its own context). It passes that text to `jev_judge.py judge --item-id
--item-title --item-file` (or stdin) for both gates. No gate parses, discovers
or normalizes plans. Anchor and question records live in the tracker
`anchor_tracker.py` resolves (ADR-004), which the installer selects; installed
text names only that tracker's commands.

Consequences: Any plan format works, and the plan's format and the anchor
tracker are independent choices. `judge` keeps its size cap
(`PLAN.TOO_LARGE`). Markdown-versus-tracker-copy parity is no longer checked by
the skill; the plan's author owns it. `plan_source.py` and its contract stop
shipping unless something else still needs them. REQ-021, REQ-027, REQ-057.
