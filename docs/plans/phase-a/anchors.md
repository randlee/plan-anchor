# Anchors - phase-a

Constraints captured during planning. Each anchor is a testable statement written by the orchestrator and approved by the user; the user's verbatim words are kept beneath it as provenance. Every anchor is judged at the planning gate and again at the development gate. Edit `anchors.json`, not this file; this file is rendered.

Intent: `docs/plans/phase-a/intent.md`

| ID | Status | Summary | Stated |
| --- | --- | --- | --- |
| ANC-001 | locked | Guideline baseline | 2026-10-10 |
| ANC-002 | locked | Agent tool only | 2026-10-10 |
| ANC-003 | retired | Resolve agent trust once | 2026-10-10 |
| ANC-004 | retired | Structured agent params | 2026-10-10 |
| ANC-005 | locked | Only API-key environment variable | 2026-10-10 |
| ANC-006 | retired | Offline modes never send | 2026-10-10 |
| ANC-007 | retired | Support bd and br | 2026-10-10 |
| ANC-008 | retired | No shell commands in params | 2026-10-10 |
| ANC-009 | locked | Harness-specific agents | 2026-10-10 |
| ANC-010 | locked | Unbiased question tuning | 2026-10-10 |
| ANC-011 | locked | Jev remains required | 2026-10-10 |
| ANC-012 | locked | Secrets stay redacted | 2026-10-10 |
| ANC-013 | locked | Realistic examples | 2026-10-10 |
| ANC-014 | locked | Exclude sc-lint agents | 2026-10-10 |
| ANC-015 | locked | Authoritative sprint documents | 2026-10-10 |
| ANC-016 | locked | Dual plan sources | 2026-10-10 |
| ANC-017 | locked | Beads only stores anchors | 2026-10-10 |
| ANC-018 | locked | Fast br anchor-store setup | 2026-10-10 |
| ANC-019 | retired | Peer tuning coordinator | 2026-10-11 |
| ANC-020 | locked | Parallel candidate-question tournament | 2026-10-11 |
| ANC-021 | locked | Authoritative plans are read-only to tuning | 2026-10-11 |
| ANC-022 | locked | Diagnostic temporary plan mutations | 2026-10-11 |
| ANC-023 | locked | Concurrent named tuning subagent | 2026-10-11 |
| ANC-024 | locked | Clarity-only authority recommendations | 2026-10-11 |
| ANC-025 | locked | User approves authority refinements | 2026-10-11 |
| ANC-026 | locked | Dedicated planner tuning subagent | 2026-10-11 |
| ANC-027 | locked | Tuner calls Jev directly | 2026-10-11 |
| ANC-028 | locked | Review-to-plan-or-tuner feedback loop | 2026-10-11 |
| ANC-029 | locked | Render planner feedback through checked-in sc-compose template | 2026-10-11 |
| ANC-030 | locked | Require binary evidence-backed tuner disposition | 2026-10-11 |
| ANC-031 | locked | Forbid pass-seeking retuning from planner pressure | 2026-10-11 |
| ANC-032 | locked | Install names only its tracker | 2026-10-17 |
| ANC-033 | locked | Tracker switch equals fresh install | 2026-10-17 |
| ANC-034 | locked | Installed md and py rendered from .j2 | 2026-10-17 |
| ANC-035 | locked | Plugin exposes only the installer | 2026-10-17 |
| ANC-036 | locked | Global destinations refused | 2026-10-17 |

## ANC-001

Anchor: claude-code-skills-agents-guidelines.md is the governing architecture baseline for plan-anchor.

> these guidelines are my expected baseline.  I feel like we need to apply plan-anchoring to the plan-anchor skill

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: locked. Version 5.

Summary: Guideline baseline

Scope: edits the skill, an agent definition, an agent registry, an invocation runner, or plugin orchestration

Deterministic check to pair with the development gate: Run the Phase A compliance validator against the guideline-derived rules and the documented override list.

Beads: anchor `pa-jvb`, plan questions `pa-jvb.1`, dev questions `pa-jvb.2`

Fixtures:
- pass: The Phase A change follows every applicable guideline rule and records the Agent-tool override in the locked anchors.
- fail: The change ignores the guideline because the current implementation already works.

## ANC-002

Anchor: Claude plan-anchor workflows must invoke subagents with the Agent tool.

> yes, the Task tool has been superceeded w/ Agent tool

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: locked. Version 5.

Summary: Agent tool only

Scope: edits Claude delegation instructions, invocation examples, agent manifests, or orchestration tests

Deterministic check to pair with the development gate: Repository validation finds Agent-tool invocation and no active instruction that invokes the Task tool.

Beads: anchor `pa-fwo`, plan questions `pa-fwo.1`, dev questions `pa-fwo.2`

Fixtures:
- pass: Claude invokes anchor-plan-review through the Agent tool.
- fail: Claude invokes anchor-plan-review through the Task tool.

## ANC-003

Anchor: The plan-anchor orchestration boundary must perform agent trust resolution once per invocation.

> why does every agent need to do this?

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: retired. Version 4.

Summary: Resolve agent trust once

Scope: adds or changes agent resolution, registry validation, runtime attestation, or an agent preflight step

Deterministic check to pair with the development gate: Runner tests prove one resolution per invocation and agent definitions contain no install-path fallback search.

Beads: anchor `pa-rxx`, plan questions `pa-rxx.1`, dev questions `pa-rxx.2`

Fixtures:
- pass: The runner resolves the registered agent path, version, model, and hash once before launching it.
- fail: Each agent searches several installation paths and validates its own version before starting.

## ANC-004

Anchor: Each plan-anchor agent invocation must receive one fenced JSON input object.

> is the agent getting passed fenced json input?

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: retired. Version 4.

Summary: Structured agent params

Scope: edits any Claude or Codex agent invocation example, runner payload, or agent Inputs contract

Deterministic check to pair with the development gate: A contract test parses exactly one fenced JSON input object for every registered agent and rejects missing required fields.

Beads: anchor `pa-0rb`, plan questions `pa-0rb.1`, dev questions `pa-0rb.2`

Fixtures:
- pass: The invocation contains one fenced JSON params object matching the registered agent input schema.
- fail: The invocation describes script, tracker, and item values as unstructured prose.

## ANC-005

Anchor: Plan-anchor must not read runtime configuration from environment variables other than TYPESAFE_API_KEY.

> My preference would be no environment variables are used outside of typesafe api key

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: locked. Version 5.

Summary: Only API-key environment variable

Scope: adds or changes configuration, command-line flags, defaults, installation instructions, or environment reads

Deterministic check to pair with the development gate: Static validation finds no plan-anchor-owned environment read other than TYPESAFE_API_KEY.

Beads: anchor `pa-j8m`, plan questions `pa-j8m.1`, dev questions `pa-j8m.2`

Fixtures:
- pass: The script reads TYPESAFE_API_KEY and receives model, endpoint, threshold, and limits through CLI arguments or defaults.
- fail: Users must export PLAN_ANCHOR_ALLOW_REMOTE_JUDGE and PLAN_ANCHOR_JEV_MODEL before running a gate.

## ANC-006

Anchor: Plan-anchor --dry-run execution must make zero network calls.

> yes, --dry-run is an arg that does the same thing and can be used in unit tests

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: retired. Version 4.

Summary: Offline modes never send

Scope: changes dry-run, fixture-answer, transport, rubric, tuning, or gate execution

Deterministic check to pair with the development gate: Unit tests fail if any transport is called during --dry-run or fixture-answer execution.

Beads: anchor `pa-dyx`, plan questions `pa-dyx.1`, dev questions `pa-dyx.2`

Fixtures:
- pass: The dry-run and fixture-answer tests use a transport spy that observes zero requests.
- fail: Dry-run validates the request and then sends it to Jev.

## ANC-007

Anchor: The plan-anchoring skill must support both bd and br.

> how large of a change would it be to make this skill work w/ bd and br ?

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: retired. Version 4.

Summary: Support bd and br

Scope: reads, creates, updates, lists children of, or comments on tracker issues

Deterministic check to pair with the development gate: Contract tests run the same normalized show, children, create, update, and comment cases against bd and br fixtures.

Beads: anchor `pa-dyw`, plan questions `pa-dyw.1`, dev questions `pa-dyw.2`

Fixtures:
- pass: The tracker layer selects br and normalizes show, children, create, update, and comment results.
- fail: The planning agent calls bd children directly and fails in a br repository.

## ANC-008

Anchor: Plan-anchor agent inputs must carry tracker operation data rather than shell command strings.

> so the bd/br commands would be passed in the fenced json?

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: retired. Version 4.

Summary: No shell commands in params

Scope: edits tracker selection, agent params, runner payloads, or tracker command construction

Deterministic check to pair with the development gate: Input-schema tests reject command-string fields and adapter tests construct argv from validated operation data.

Beads: anchor `pa-08k`, plan questions `pa-08k.1`, dev questions `pa-08k.2`

Fixtures:
- pass: Params identify tracker br and issue pa-123 while the trusted adapter constructs the argv list.
- fail: Params contain the interpolated command string br show pa-123 | jq .

## ANC-009

Anchor: Each plan-anchor agent definition must reside in its harness’s agent directory: .claude/agents or .codex/agents.

> I think we should have separate agents for codex and claude (in .codex/.claude folders so agent class sonnet/luna are specified per harness).

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: locked. Version 6.

Summary: Harness-specific agents

Scope: adds or changes an agent definition, registry entry, plugin manifest, or model assignment

Deterministic check to pair with the development gate: Repository validation proves every Claude agent definition resides under .claude/agents and every Codex agent definition resides under .codex/agents.

Beads: anchor `pa-nyp`, plan questions `pa-nyp.1`, dev questions `pa-nyp.2`

Fixtures:
- pass: Claude definitions live under .claude/agents while Codex definitions live under .codex/agents.
- fail: Both harnesses load one shared agent definition outside their harness agent directories.

## ANC-010

Anchor: Question tuning must translate approved intent and anchors into accurate Jev questions without optimizing for a favorable plan verdict.

> My feeling is that tuning should be done w/ an agent independent from the planner.  this should probably be a higher level agent i.e. opus or sol which has the responsibility for tuning against the intent/anchors w/out regard for 'getting the plan to pass'.  i.e. the tuning agent should loop over jev calls while modifying the question text and verifying the answers align with intent/anchors.  the tuning agent must exercise judgement..

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: locked. Version 6.

Summary: Unbiased question tuning

Scope: changes question-tuning objectives, normative inputs, oracle construction, fixtures, override acceptance, or tuner model selection

Deterministic check to pair with the development gate: Tuner contract tests prove intent and anchors are the only normative inputs, expected outcomes are fixed before Jev answers, and current plan passage is never an optimization target.

Beads: anchor `pa-waz`, plan questions `pa-waz.1`, dev questions `pa-waz.2`

Fixtures:
- pass: The tuner selects questions for accurate intent-and-anchor detection even when they expose a defect in the current plan.
- fail: The planner rewrites questions until Jev reports that the current plan is perfect.

## ANC-011

Anchor: The normal plan-anchoring workflow must require Jev.

> fix README and make sure documents are consistent (this skill requires jev)

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: locked. Version 5.

Summary: Jev remains required

Scope: edits README, SKILL.md, installation guidance, examples, or marketplace descriptions

Deterministic check to pair with the development gate: Documentation consistency validation finds the required-workflow statement and no claim that offline modes replace Jev.

Beads: anchor `pa-nwu`, plan questions `pa-nwu.1`, dev questions `pa-nwu.2`

Fixtures:
- pass: The README states that Jev is required for normal capture, tuning, and gate execution and labels offline modes as development aids.
- fail: The README presents dry-run as a complete replacement for Jev.

## ANC-012

Anchor: Plan-anchor script output must redact the TypeSafe API-key value.

> p2 - redact api key from script output

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: locked. Version 5.

Summary: Secrets stay redacted

Scope: changes transport errors, structured output, logging, reports, audit records, or run-file persistence

Deterministic check to pair with the development gate: Secret-canary tests scan stdout, stderr, errors, reports, audits, and run files for raw credential and authorization-header variants.

Beads: anchor `pa-buf`, plan questions `pa-buf.1`, dev questions `pa-buf.2`

Fixtures:
- pass: A transport failure returns a redacted credential marker and no run artifact contains the supplied secret.
- fail: A structured error echoes the supplied API key in its suggested action.

## ANC-013

Anchor: Plan-anchor examples must be executable using repository-valid paths, supported commands, and supported JSON schemas.

> p3 - update examples to be realistic

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: locked. Version 4.

Summary: Realistic examples

Scope: adds or changes README examples, reference snippets, fixtures, sample anchors, or agent invocation examples

Deterministic check to pair with the development gate: Example tests execute commands in a fixture repository and validate documented JSON against current schemas.

Beads: anchor `pa-2td`, plan questions `pa-2td.1`, dev questions `pa-2td.2`

Fixtures:
- pass: The br example uses docs/plans/phase-a, current flags, and the documented br JSON envelope.
- fail: The example uses an invented path, removed flag, and JSON shape no supported tracker emits.

## ANC-014

Anchor: The plan-anchor plugin must not define or invoke arch-qa or req-qa.

> where did arch-qa and req-qa come from?  these are agents on sc-lint, not part of this skill

Said by randlee, plan-anchor self-anchoring review, 2026-10-10. Status: locked. Version 6.

Summary: Exclude sc-lint agents

Scope: edits plan-anchor agent files, registries, manifests, skill delegation, or examples

Deterministic check to pair with the development gate: Repository search finds no arch-qa or req-qa reference under the plan-anchor plugin.

Beads: anchor `pa-9wl`, plan questions `pa-9wl.1`, dev questions `pa-9wl.2`

Fixtures:
- pass: The plan-anchor registries list only anchor-plan-review, anchor-sprint-review, and anchor-tuning.
- fail: The plan-anchor skill delegates requirement review to the sc-lint req-qa agent.

## ANC-015

Anchor: The Phase A index must link separate authoritative sprint-plan documents.

> I always break a plan into sprints.  see. /Users/randlee/github/raptor/docs/plans/phase-a/* for raptor project.  there is also a plan-hardening skill in that repo which has sprint-plan-guidelines for building your sprint

Said by randlee, plan-anchor Phase A dogfood correction; live rubric pending explicit TypeSafe payload approval, 2026-10-10. Status: locked. Version 6.

Summary: Authoritative sprint documents

Scope: creates or reviews a phase plan, sprint plan, phase index, or planning source

Deterministic check to pair with the development gate: Validate the phase index links separate sprint Markdown files and each sprint has one authoritative deliverables, acceptance, validation, and non-closure section.

Beads: anchor `pa-2zo`, plan questions `pa-2zo.1`, dev questions `pa-2zo.2`

Fixtures:
- pass: The phase index links eight separate sprint documents, each with authoritative deliverables, acceptance criteria, validation, and non-closure.
- fail: The phase plan keeps all sprint work as subsections in one monolithic Markdown file.

## ANC-016

Anchor: The plan-anchoring gate must accept both a Markdown plan and its copy in a br or bd tracker.

> You should be able to run the /plan-anchor skill both against the md plan and against a copy of the plan in br database

Said by randlee, plan-anchor Phase A dogfood correction; live rubric pending explicit TypeSafe payload approval, 2026-10-10. Status: locked. Version 7.

Summary: Dual plan sources

Scope: changes plan-source selection, sprint discovery, item composition, source digests, planning-gate invocation, or source parity tests

Deterministic check to pair with the development gate: Materialize the Phase A Markdown sprints and their br copies, assert identical ordered request digests, require both recorded-answer parity and independent live passing results, and classify differing live answers as model instability.

Beads: anchor `pa-bxu`, plan questions `pa-bxu.1`, dev questions `pa-bxu.2`

Fixtures:
- pass: The Markdown and br-copy adapters normalize Sprint A2 to the same request digest, pass independently, and reserve exact verdict equality for recorded-answer parity.
- fail: The skill can review only tracker issue bodies and rejects the equivalent Markdown sprint file.

## ANC-017

Anchor: Markdown plan review requires tracker records only for an anchor root and its plan-question and dev-question children.

> at that point the only beads dependency in the plan is for holding the anchoring info and questions which can be spun up in a br database quickly for any repo

Said by randlee, plan-anchor Phase A dogfood correction; live rubric pending explicit TypeSafe payload approval, 2026-10-10. Status: locked. Version 7.

Summary: Beads only stores anchors

Scope: changes tracker prerequisites, anchor storage, question storage, Markdown plan review, or required issue layout

Deterministic check to pair with the development gate: Complete Markdown-source dry-run review in a repository whose tracker contains only anchor roots with plan-question and dev-question children.

Beads: anchor `pa-885`, plan questions `pa-885.1`, dev questions `pa-885.2`

Fixtures:
- pass: Markdown review reads plan text from sprint files and uses br only for each anchor's question tree.
- fail: Markdown review requires the phase and every sprint to exist as br issues before it can run.

## ANC-018

Anchor: The skill must document br initialization with no prerequisite beyond a local Git repository.

> at that point the only beads dependency in the plan is for holding the anchoring info and questions which can be spun up in a br database quickly for any repo

Said by randlee, plan-anchor Phase A dogfood correction; live rubric pending explicit TypeSafe payload approval, 2026-10-10. Status: locked. Version 6.

Summary: Fast br anchor-store setup

Scope: changes br installation, local initialization prerequisites, command examples, or onboarding

Deterministic check to pair with the development gate: Run the documented br initialization sequence in a temporary local Git repository without a remote service or phase epic.

Beads: anchor `pa-c3t`, plan questions `pa-c3t.1`, dev questions `pa-c3t.2`

Fixtures:
- pass: In any local Git repository, the documented br initialization commands work without a remote tracker service or a phase epic.
- fail: Before br can initialize, every repository must connect to a shared tracker service and create a phase epic.

## ANC-019

Anchor: The harness-specific anchor-tuning agent must be a peer Opus/Sol agent that can invoke subagents while retaining tuning judgment.

> I would expect anchor-tuning.md agent to be a peer agent which can call subagents.

anchor-tuning would call jev w/ a set of questions in parallel (i.e. many more questions that the final calls would use), rank the questions and down-select.

Said by randlee, plan-anchor Phase A planning review, 2026-10-11. Status: retired. Version 3.

Summary: Peer tuning coordinator

Scope: changes tuning-agent hierarchy, harness model/tool access, or delegation authority

Deterministic check to pair with the development gate: Repository validation proves both harnesses register anchor-tuning.md as an Opus/Sol peer with Agent/subagent capability and reserve oracle interpretation and question-selection judgment for that coordinator.

Beads: anchor `pa-tnj`, plan questions `pa-tnj.1`, dev questions `pa-tnj.2`

Fixtures:
- pass: The Opus/Sol anchor-tuning peer invokes read-only Jev workers but alone freezes the oracle and selects questions.
- fail: A leaf tuner without Agent access performs every Jev call sequentially and cannot dispatch subagents.

## ANC-020

Anchor: Anchor-tuning must rank parallel Jev evaluations of a frozen-oracle candidate pool and down-select fewer questions for production review.

> anchor-tuning would call jev w/ a set of questions in parallel (i.e. many more questions that the final calls would use), rank the questions and down-select.

Said by randlee, plan-anchor Phase A planning review, 2026-10-11. Status: locked. Version 4.

Summary: Parallel candidate-question tournament

Scope: changes candidate-question generation, parallel Jev evaluation, ranking, down-selection, or production question payloads

Deterministic check to pair with the development gate: Tournament tests prove a larger candidate pool is evaluated by direct parallel Jev calls against identical frozen-oracle cases, ranking evidence and tuner rationales are retained, and production review receives only the down-selected questions.

Beads: anchor `pa-q30`, plan questions `pa-q30.1`, dev questions `pa-q30.2`

Fixtures:
- pass: The tuner runs a broad candidate pool in parallel on one frozen oracle, records the ranking, and sends only selected questions to plan review.
- fail: The production review sends every speculative tuning question because no ranked down-selection occurs.

## ANC-021

Anchor: Anchor-tuning must not modify authoritative plan sources.

> anchor-tuning ONLY makes the plan modifications on temporary copies of the plan and does NOT modify the original plan.

Said by randlee, plan-anchor Phase A planning review, 2026-10-11. Status: locked. Version 2.

Summary: Authoritative plans are read-only to tuning

Scope: changes tuning fixtures, mutation testing, plan-source writes, or authoritative Markdown/tracker content

Deterministic check to pair with the development gate: Mutation tests hash authoritative Markdown and tracker copies before and after tuning and prove both originals remain unchanged.

Beads: anchor `pa-7sq`, plan questions `pa-7sq.1`, dev questions `pa-7sq.2`

Fixtures:
- pass: The tuner leaves the Markdown plan and tracker copy byte-identical after calibration.
- fail: The tuner edits the authoritative sprint document to make Jev notice a requirement.

## ANC-022

Anchor: Anchor-tuning must test candidate questions on temporary plan copies with diagnostic additions and removals.

> anchor-tuning is allowed to modify proposed plan text w/ added ceremony to insure jev finds it, he may also remove important statements or deliverables so jev will flag the info missing.

Said by randlee, plan-anchor Phase A planning review, 2026-10-11. Status: locked. Version 2.

Summary: Diagnostic temporary plan mutations

Scope: changes tuning fixtures, candidate-question evaluation, mutation cases, or temporary workspace behavior

Deterministic check to pair with the development gate: Tuning tests create disposable positive-visibility and required-content-removal variants, derive their expected outcomes from intent and anchors, evaluate candidates against them, and delete the variants without source writes.

Beads: anchor `pa-yaz`, plan questions `pa-yaz.1`, dev questions `pa-yaz.2`

Fixtures:
- pass: The tuner adds explicit ceremony and removes a required deliverable only in disposable copies, then checks whether candidate questions distinguish both cases.
- fail: The tuner evaluates candidates only on the unchanged plan and never proves they detect missing required content.

## ANC-023

Anchor: Planning must run a named <team>-anchor-tuning subagent concurrently after the first draft and INTENT/ANC capture.

> planning agent puts together a first draft of the plan, launches named team-member <team>-anchor-tuning which starts refining jev questions based on intent + anchors defined in parallel w/ planner completing the plan.

Said by randlee, plan-anchor Phase A planning review, 2026-10-11. Status: locked. Version 3.

Summary: Concurrent named tuning subagent

Scope: changes planning workflow ordering, subagent naming, tuning startup, or review prerequisites

Deterministic check to pair with the development gate: Workflow tests prove a stable <team>-anchor-tuning subagent starts after the first draft and approved INTENT/ANC authority packet, overlaps continued plan authoring, and completes before leaf plan review consumes questions.

Beads: anchor `pa-51f`, plan questions `pa-51f.1`, dev questions `pa-51f.2`

Fixtures:
- pass: The planner launches team-a-anchor-tuning after the first draft and approved INTENT/ANC packet, then continues plan authoring while tuning runs.
- fail: The planner completes the plan before starting an unnamed tuning subagent.

## ANC-024

Anchor: Anchor-tuning may recommend clarity-only refinements or additions to INTENT and ANC records.

> Note:  anchor-tuning can also recommend refinements or additions to anchors or intent for clarity (not to change meaning).

Said by randlee, plan-anchor Phase A planning review, 2026-10-11. Status: locked. Version 2.

Summary: Clarity-only authority recommendations

Scope: changes tuner findings, intent or anchor clarification proposals, or authority-edit boundaries

Deterministic check to pair with the development gate: Contract tests permit a recommendation envelope for clarity-only INTENT/ANC edits, require a rationale and semantic-equivalence explanation, and forbid the tuner from applying or broadening them.

Beads: anchor `pa-sx5`, plan questions `pa-sx5.1`, dev questions `pa-sx5.2`

Fixtures:
- pass: The tuner proposes a wording clarification with a rationale showing that the INTENT/ANC meaning is unchanged.
- fail: The tuner proposes a new product constraint as a clarification to an existing anchor.

## ANC-025

Anchor: The user must approve every anchor-tuning recommendation before INTENT or ANC records are changed.

> user should be consulted w/ recommended refinements to ANC + INTENT.

Said by randlee, plan-anchor Phase A planning review, 2026-10-11. Status: locked. Version 2.

Summary: User approves authority refinements

Scope: changes approval handling, intent or anchor updates, oracle invalidation, or tuning restart behavior

Deterministic check to pair with the development gate: Workflow tests prove recommended authority edits remain proposals until explicit user approval; an approved version change invalidates and reruns affected oracles and candidate rankings.

Beads: anchor `pa-mqw`, plan questions `pa-mqw.1`, dev questions `pa-mqw.2`

Fixtures:
- pass: The tuner presents its clarification proposal to the user and waits; after approval, the affected authority version and tournament are refreshed.
- fail: The tuner directly edits INTENT and keeps using the old oracle without asking the user.

## ANC-026

Anchor: Anchor-tuning must run as a dedicated Opus/Sol subagent of the planner.

> I suppose anchor-tuning could simply be a sub-agent of planner (opus/sol minimum)

Said by randlee, plan-anchor Phase A planning review, 2026-10-11. Status: locked. Version 2.

Summary: Dedicated planner tuning subagent

Scope: changes tuning-agent hierarchy, launch ownership, or tuner model selection

Deterministic check to pair with the development gate: Harness contract tests prove the planner launches the dedicated anchor-tuning profile with Opus on Claude and Sol on Codex, using an isolated structured authority packet.

Beads: anchor `pa-fiz`, plan questions `pa-fiz.1`, dev questions `pa-fiz.2`

Fixtures:
- pass: The planner launches the isolated anchor-tuning profile with Opus or Sol and a structured INTENT/ANC authority packet.
- fail: The planner itself rewrites Jev questions in its own context.

## ANC-027

Anchor: Anchor-tuning must run its candidate-question Jev evaluations directly.

> he could run jev questions directly.

Said by randlee, plan-anchor Phase A planning review, 2026-10-11. Status: locked. Version 2.

Summary: Tuner calls Jev directly

Scope: changes candidate-question execution, Jev call ownership, or nested-agent delegation

Deterministic check to pair with the development gate: Execution traces prove anchor-tuning invokes Jev directly for its parallel candidate pool and does not require nested Agent delegation.

Beads: anchor `pa-tq0`, plan questions `pa-tq0.1`, dev questions `pa-tq0.2`

Fixtures:
- pass: Anchor-tuning directly launches parallel Jev calls for its candidate pool and records every result.
- fail: Anchor-tuning must spawn nested Agent workers before it can evaluate any candidate question.

## ANC-028

Anchor: After anchor-plan-review, the planner must fix genuine plan findings or send raw review evidence to anchor-tuning for question-defect triage.

> planner would then send results of anchor-plan-review to anchor-tuning and/or update his plan to fix issues found.

Said by randlee, plan-anchor Phase A planning review, 2026-10-11. Status: locked. Version 2.

Summary: Review-to-plan-or-tuner feedback loop

Scope: changes post-review triage, plan repair, question retuning, or review-result routing

Deterministic check to pair with the development gate: Workflow tests route genuine findings to planner-owned plan edits and suspected question defects as unmodified review evidence to anchor-tuning; tuner triage cannot receive a desired verdict.

Beads: anchor `pa-ys2`, plan questions `pa-ys2.1`, dev questions `pa-ys2.2`

Fixtures:
- pass: The planner fixes a confirmed missing deliverable, while a suspicious low-confidence role answer is sent unchanged to anchor-tuning for oracle-based triage.
- fail: The planner asks anchor-tuning to rewrite a question until a failing plan review passes.

## ANC-029

Anchor: Planner-to-anchor-tuning review feedback must be rendered from a checked-in sc-compose Jinja2 template.

> with this work model, it is important that the feedback sent to anchor-tuning be in a sc-compose j2 template which has strong wording that his job is NOT to fix jev failures that accurately point out issues w/ the current plan.

Said by user, planning session, 2026-10-11. Status: locked. Version 2.

Summary: Render planner feedback through checked-in sc-compose template

Scope: Planner-to-anchor-tuning review feedback transport.

Deterministic check to pair with the development gate: Validate the checked-in .j2 template with sc-compose --strict and prove the planner renders every review-feedback handoff from it.

Beads: anchor `pa-y78`, plan questions `pa-y78.1`, dev questions `pa-y78.2`

Fixtures:
- pass: The planner renders the raw review request and result through the checked-in anchor-tuning-review-feedback.md.j2 template with sc-compose --strict.
- fail: The planner writes a free-form message asking the tuner to fix questions.

## ANC-030

Anchor: Anchor-tuning must independently classify each disputed Jev failure as either a cited plan violation or a cited question defect.

> the anchor-tuning should respond w/ a) your plan violates ANC-XXX or INTENT-YYY. OR b) Yes, jev's response does not support ANC-XXX or INTENT-YYY, I will update the questions.

Said by user, planning session, 2026-10-11. Status: locked. Version 2.

Summary: Require binary evidence-backed tuner disposition

Scope: Anchor-tuning triage of planner-submitted Jev failures.

Deterministic check to pair with the development gate: Reject triage results unless disposition is plan_violation or question_defect and evidence cites at least one approved ANC or INTENT identifier.

Beads: anchor `pa-9n0`, plan questions `pa-9n0.1`, dev questions `pa-9n0.2`

Fixtures:
- pass: The tuner returns plan_violation, cites ANC-010, quotes the conflicting plan text, and leaves the sealed question digest unchanged.
- pass: The tuner returns question_defect, cites INTENT review policy, shows the frozen-oracle mismatch, and reopens the affected question tournament.
- fail: The tuner accepts the planner conclusion and edits the question without choosing a disposition or citing authority.

## ANC-031

Anchor: Anchor-tuning must not change an accurate Jev question merely because the planner asks it to make a failing plan pass.

> the feedback path from planner -> anchor-tuning has risk that planner would say 'jev is failing by plan, fix the questions'.

Said by user, planning session, 2026-10-11. Status: locked. Version 2.

Summary: Forbid pass-seeking retuning from planner pressure

Scope: Anchor-tuning triage and question updates after plan review.

Deterministic check to pair with the development gate: Mutation tests submit a planner request to fix questions for a known plan defect and require plan_violation with unchanged sealed question digest.

Beads: anchor `pa-y6o`, plan questions `pa-y6o.1`, dev questions `pa-y6o.2`

Fixtures:
- pass: A planner asks to fix a question for a known plan defect; the tuner rejects the request as plan_violation and preserves the sealed question digest.
- fail: A planner says the plan must pass, so the tuner weakens an accurate question until Jev returns pass.

## ANC-032

Anchor: A plan-anchor install rendered for one tracker must not name the other tracker as a whole word in any installed file except references/installation-and-troubleshooting.md.

> I expect that installing 'bd' will ONLY have 'bd' commands in md files and scripts.  alternatively installing 'br' will ONLY have 'br' in md and scripts.

bd and br should both be in installation & troubleshooting guide since  the install guide should explain how this switch works.

Said by randlee, plan-anchor 0.8.2 tracker-pure installs (operator, relayed by the coordinating agent), 2026-10-17. Status: locked. Version 2.

Summary: Install names only its tracker

Scope: changes install templates, the files install.py copies or renders, tracker-specific text or code in scripts, or the install guide

Deterministic check to pair with the development gate: Fresh install.py run per tracker with --target claude,codex,cursor; grep -rnwI <other tracker> over .claude .codex .cursor .sc finds lines only in references/installation-and-troubleshooting.md (test_install.py::RealInstallTests.test_each_install_names_only_its_tracker).

Fixtures:
- pass: The sprint renders jev_judge.py from jev_judge.py.j2 so a br install's help text says 'br show --json' and never names bd.
- fail: The sprint keeps scripts copied verbatim, so a br install's jev_judge.py still tells the user to run 'bd children'.

## ANC-033

Anchor: Rerunning install.py with the other --tracker over an existing install must leave a folder byte-identical to a fresh install of that tracker, in both directions.

> installing 'br' then installing 'bd' on top of it will look EXACTLY the same as just installing 'bd' in an empty location.  likewise for the opposite.

Said by randlee, plan-anchor 0.8.2 tracker-pure installs (operator, relayed by the coordinating agent), 2026-10-17. Status: locked. Version 2.

Summary: Tracker switch equals fresh install

Scope: changes tracker switching, the lock file, settings writes, file ownership or removal, or rendering in install.py

Deterministic check to pair with the development gate: Install br then bd (and bd then br) for every target and compare with a fresh install of the second tracker: identical file lists, bytes and modes, lock and settings included (test_install.py::RealInstallTests.test_switching_trackers_equals_a_fresh_install).

Fixtures:
- pass: The sprint checks that a br install switched to bd matches a fresh bd install byte for byte, lock and settings included, and the reverse.
- fail: After a switch the old tracker's rendered scripts and settings comments stay behind, so the folder differs from a fresh install.

## ANC-034

Anchor: Every Markdown file and Python script that install.py installs must be rendered at install time from a <file>.md.j2 or <script>.py.j2 template under install/templates/.

> I expect the markdown files and scripts are <file>.md.j2 and <script>.py.j2 and are rendered when installed.

Said by randlee, plan-anchor 0.8.2 tracker-pure installs (operator, relayed by the coordinating agent), 2026-10-17. Status: locked. Version 2.

Summary: Installed md and py rendered from .j2

Scope: adds, moves or copies an installed Markdown file or script, or changes how install.py renders or copies files

Deterministic check to pair with the development gate: Every installed .md and .py traces to an install template whose frontmatter name starts with sc-plan-anchor- (test_install.py::RealInstallTests.test_every_installed_md_and_py_is_rendered_from_a_template, RenderingTests.test_every_prompt_source_is_a_template).

Fixtures:
- pass: Each script moves to scripts/<name>.py.j2 and install.py renders it for the selected tracker like every reference.
- fail: The scripts stay plain .py files that install.py copies unchanged into every install.

## ANC-035

Anchor: The sc-plan-anchor plugin must expose only the plan-anchor-installer skill, with no loadable plan-anchoring skill and no agents.

> the ENTIRE reason we changed to ONLY advertising plan-anchor-installer and hiding plan anchor was what I outlined above.

Said by randlee, plan-anchor 0.8.2 tracker-pure installs (operator, relayed by the coordinating agent), 2026-10-17. Status: locked. Version 2.

Summary: Plugin exposes only the installer

Scope: changes the plugin's skills/ or agents directories, plugin or marketplace manifests, or what the marketplace plugin ships

Deterministic check to pair with the development gate: plugins/sc-plan-anchor/skills/ holds only plan-anchor-installer and no .claude, .codex, .cursor or skills/plan-anchoring tree exists in the plugin (test_install.py::RenderingTests.test_plugin_ships_only_the_installer_skill_and_no_rendered_tree).

Fixtures:
- pass: The marketplace plugin's skills/ directory holds only plan-anchor-installer; plan-anchoring and its agents exist only in per-folder installs.
- fail: The plugin advertises the plan-anchoring skill and its agents again so a marketplace install can run the gates directly.

## ANC-036

Anchor: install.py must refuse a --dest inside the global ~/.claude, ~/.codex, ~/.cursor or ~/.agents folders with INSTALL.DEST_GLOBAL and write nothing.

> we also block installing 'plan-anchor' in global .claude, .codex, .cursor, .agents folders

Said by randlee, plan-anchor 0.8.2 tracker-pure installs (operator, relayed by the coordinating agent), 2026-10-17. Status: locked. Version 2.

Summary: Global destinations refused

Scope: changes install.py destination checks, plan_anchor_paths.global_location, or the installer skill's destination handling

Deterministic check to pair with the development gate: install.py --dest ~/.claude (and .codex, .cursor, .agents and their subfolders) exits 2 with INSTALL.DEST_GLOBAL and leaves the tree unchanged (test_installer_skill.py::GlobalDestinationTests).

Fixtures:
- pass: install.py --dest ~/.codex exits 2 with INSTALL.DEST_GLOBAL and writes no file.
- fail: install.py accepts --dest ~/.claude and writes a shared plan-anchoring skill there for every repository.
