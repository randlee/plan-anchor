# Anchor tuning with fast-agent stand-ins (design draft)

Status: draft. Anchor exclusions and the `Result` conversion are built
(0.7.0); stand-ins, `follow-up` and the tuning prompt are not (ADR-011).

## Goal

Produce INTENT/ANC statements and Jev questions that are solid anchors for the
planned work. Jev returns choices and confidence but no text, so it cannot say
why a cell failed. Fast stand-ins (Claude `haiku`, Codex `luna`) get the
identical request and can be asked why.

Stand-in output is advisory. It never gates and never replaces a Jev re-run.
Divergence between models is a strong signal that the question and the data
are misaligned, or that one of them is unclear.

## What a stand-in sees

The request is unchanged from what `jev_judge.py` composes today and writes
with `--dry-run`:

- `state.anchor {id, statement, scope}`;
- `state.item {id, title, text}`;
- the gate's question set.

Intent is not sent. Jev's small context forces each sprint to stand alone,
which is exactly the context a fresh dev agent would have.

- **Turn 1** is built by the tool and never written by the agent. It is the
  exact request body plus one instruction: answer with fenced JSON in Jev's
  response schema. It runs with no tools, in an empty temp dir, with one
  session per cell per model. The answer is checked with the same
  `validate_response` that checks Jev's answers.
- **Turns 2..N** resume that same cell's session. The tuning agent writes the
  questions. A short list of suggested questions is offered but is not
  mandatory. The agent may send a dependency sprint's text and ask whether it
  closes the gap.

## The loop

The loop is empirical, with no recipe:

1. Run Jev and both stand-ins in parallel over the set (a matrix of sprints x
   ANC, or one sprint deep).
2. Drop the cells that are fine.
3. Discuss the rest with the stand-in that gave the answer. The follow-up
   turns are the point; never skip them.
4. Make one small change. It is usually `Prerequisites` or
   `Additional context` in the sprint, written for the dev agent and not for
   the judge.
5. Re-run and measure. Repeat.

Rules:

- **Neutral tuner.** Never favour the plan. Question or ANC wording changes go
  through the existing `anchor-tuning` oracle and tournament.
- **Prerequisites.** A deliverable of an earlier sprint is assumed to exist.
  quality-mgr catches gaps during plan review; tuning does not verify them.
  Where a sprint depends on content another sprint owns, copy that content in.
- **Edit and measure, don't predict.** Counterfactual answers from stand-ins
  proved unreliable.
- **Ask the agent that answered.** A follow-up goes to the agent that gave the
  answer, about its own answer.
- **Read run files**, not agent summaries.
- **Failures.** Never fall back silently. Report each failure together with a
  background root-cause or fix already under way. Stop only for judgment or
  credentials.
- **Proceed.** Running the follow-up turns is the job; the agent does not ask
  permission to run them.

## Ledger

The operator asked for this, for rollback and A/B comparison. Minimal form:

- each plan edit is its own commit, so rolling back is `git revert`;
- a notes table in the plan directory has one row per iteration: change,
  reason, run ids and before/after failing cells (as in atm-core
  `phase-bi/anchor-tuning-notes.md`);
- `jev_judge.py diff` compares runs.

No ledger CLI. It is retired if git plus the notes table proves insufficient
in practice.

## Anchor exclusions

The case: a sprint with unrelated work, where an anchor simply does not
apply. Today that cell can still fail as `underspecified` when Jev wavers
near 0.6, as bi-2 did.

Built in 0.7.0 (ADR-012, REQ-006). The anchor record (`anchors.json`) has an
optional list on the anchor, set with `jev_judge.py exclude`:

```json
"exclude": [{"item": "atm-bi-2", "reason": "data-only sprint; the skill CLI options belong to bi-3"}]
```

`judge` skips that cell and reports it as `excluded`, with the reason. It
shows in the run summary and in `anchors.md`, so it is easy to retrieve. That
is all: no approval workflow and no extra verdict states.

## Configuration

`.sc/plan-anchor/settings.yaml` gains `fast_agents`:

```yaml
fast_agents:
  profiles:
    - {name: haiku, tool: claude, model: haiku, timeout_seconds: 180}
    - {name: luna,  tool: codex,  model: luna,  timeout_seconds: 300}
```

Stand-ins run only when `--stand-ins` is passed. Session ids come from
sc-launchpad (synaptic-canvas#124).

## Contracts

All new Python returns `Result` (`scripts/result.py`), and every launch
reports a typed reason.

- **`judge --stand-ins <names|all>`**
  - Launches each profile through `sc_launchpad_task.py`, in parallel with
    Jev.
  - Each result entry gains
    `stand_ins: [{profile, ok, session_id, cwd, answers, agrees_with_jev} | {profile, ok: false, error}]`.
  - Gating is unchanged.
  - A stand-in error is an error, not a negative result: the run exits 2
    with a typed error envelope (ADR-007).
- **`follow-up --run <file> --cell <anchor>:<item> --profile <name> --question <text> [--attach-item <file>]`**
  - Resumes that cell's own session.
  - Appends the turn to the run's transcript file.
- **One tuning-agent prompt** with two modes, matrix and deep dive, and the
  rules above.

## Stack plan

Done: `Result<T,E>` conversion and the `exclude` field (0.7.0). What is left,
as the next layers:

| Layer | Content |
| --- | --- |
| next | `fast_agents` settings and `judge --stand-ins` |
| after | `follow-up`, the tuning-agent prompt and the worktree preflight fix |
