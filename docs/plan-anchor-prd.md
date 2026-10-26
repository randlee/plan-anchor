# plan-jev PRD

Oct 9, 2026 · @Rand Lee

A planning-orchestrator skill that turns the facts you state while planning into numbered, Jev-judged checks, so a plan — and the work built from it — can be verified against your intent across many iterations instead of drifting as context compresses.

## Problem & intent

When a planning agent builds a plan over a long conversation, the specific facts you state get compressed out of context. You ask for something concrete — "copy these crates from ATM as the starting point and strip the ATM-specific code" — because the ATM implementation is exactly what you want in a general-purpose form. The agent writes it down, but several rounds later that fact is gone from its working context, and it quietly writes a new implementation from scratch that doesn't match what you expected.

The cost is repetition. Today you re-state the same facts every time you re-open a plan, because nothing enforces them. There's no mechanical check that the plan still says what you said, and no check that the delivered work still matches the plan.

plan-jev makes those facts durable and enforceable. As you plan, your stated facts are captured verbatim, numbered, and turned into Jev questions. Jev then acts as an adversarial reviewer: run it against the plan and it reports which facts a given plan item forgot or contradicted, in your own words. The same facts are re-used during development to confirm the implementation didn't drift. You state a fact once; the skill holds you — and your agents — to it from then on.

## Core concepts

A plan is governed by four kinds of fact. The first is a guiding overview; the next three are the Jev-judged facts, each numbered and carrying a reference back to where it came from.

| Concept | ID prefix | What it is | Source |
| --- | --- | --- | --- |
| Intent | — | A short, high-level overview of what the plan is for — the "why" that guides everything beneath it. One per plan. | Written during planning |
| Anchor | ANC | A verbatim fact you state while planning that roots the plan and keeps it from drifting. Stores your exact words. | What you say while planning |
| Requirement | REQ | A numbered technical requirement already maintained in your process. | Existing requirement register |
| ADR | ADR | A numbered architectural decision record. | Existing ADR register |

The name "Anchor" was chosen over alternatives (tenet, stricture, lodestar, keystone) because it is phonetically distinct — it won't collide with "requirement" or "decision" in speech — and it names what the thing does: it holds the plan to your exact words. An anchor is the gap this skill fills, because requirements and ADRs are already written down, while the directives you state mid-planning are not.

All three fact types (ANC, REQ, ADR) become Jev questions. Intent is somewhat outside the Jev skill itself but sits at the top of the structure and feeds into it, giving every question a frame for what the plan is trying to achieve.

## Artifacts & layout

The plan produces two written documents and a tree of beads.

**Documents** land in the current phase folder, `docs/plans/phase-<current>/` (`plan_dir` in `.sc/plan-anchor/settings.yaml`), for reference:

- An **Intent document** — the high-level overview of the plan.
- An **Anchor document** — all anchors, numbered (ANC-001, ANC-002, …), each with its verbatim source statement.

**Beads** hold the Jev questions, so they live and version alongside the plan work. The structure is a small tree per fact:

1. An **Anchor bead** — represents the anchor itself.
   - A **Plan-questions bead** underneath it — the Jev questions for the planning gate.
   - A **Development-questions bead** underneath it — the Jev questions for the development gate.

This keeps the two question sets distinct but traceable to a single anchor, and it lets the planning gate and the development gate evolve their question wording independently while pointing at the same root fact. Requirements and ADRs follow the same bead pattern.

## Jev question design

Jev is used the way it works best: give it one context — a single plan bead — and ask several questions about it in parallel, in one request. Jev answers each independently, so the questions must be **orthogonal**: each isolates a different failure mode so the verdicts together pinpoint exactly what's going on, rather than collapsing into one pass/fail.

For a single anchor against a plan bead, a parallel set might be:

| # | Question | Type | Isolates |
| --- | --- | --- | --- |
| 1 | Is this anchor even relevant to this sprint/bead? | choice | Scope — gates the rest; an irrelevant anchor shouldn't register as a failure |
| 2 | Does the bead address this anchor at all? | choice | "Forgotten" — the compression failure |
| 3 | Does the bead contradict the anchor? | choice | "Drifted" — did something other than what was asked |

Because the questions in one request can't see each other's answers, relevance can't literally gate the others inside Jev; the gating is applied in code afterward, using Jev's constraint that extra questions add little latency or cost. Each question carries confidence, so a low-confidence verdict flags an anchor that may be underspecified.

Two constraints from how Jev behaves shape this:

- **Keep the state small.** Send one bead as context, not the whole plan — accuracy degrades when unrelated material sits in the state (context rot).
- **Do the counting in code.** Jev can't count or do math, so coverage across beads ("is ANC-012 satisfied anywhere?") is computed from the per-bead verdict matrix, not asked of Jev.

## The two gates

The same anchors are enforced at two points. You author them once; they're checked twice.

**Planning gate.** The planning-questions bead's questions run against each planning bead: did the plan actually capture this anchor? This catches the "you forgot the copy-from-ATM anchor" case before any code is written, and it's where you iterate on the plan repeatedly, re-running the check to confirm nothing drifted between revisions.

**Development gate.** The development-questions bead's questions are run by the quality-manager agent — the QA side of your dev/QA matrix — against the delivered work, to confirm the implementation didn't drift from the anchors. Enforcement becomes mechanical instead of a matter of the agent remembering.

The gates matter separately because they judge different things: the planning gate judges plan text, the development gate judges delivered work. An anchor that was faithfully planned but then abandoned in code passes the first gate and fails the second. The ATM example runs through both: the planning gate confirms the plan says "start from ATM's crates," and the development gate confirms the agent actually did, rather than rewriting from scratch.

One limitation to note: Jev judges the text it's given. The development gate confirms the work *describes* starting from ATM; confirming the code literally did (a diff against the source crates, or git history) is a separate deterministic check worth pairing with it.

## Provenance & reporting

Every Jev fact is numbered and carries its provenance — not just the question Jev was asked, but what you said that made it a fact. When a bead fails, the report names the fact and quotes the statement behind it, so the planning agent gets your intent back in your own words.

A failing verdict reads like:

> **bd-42 · ANC-012 · not addressed** You said (planning session, Oct 9): "copy the libraries from ATM as the starting point and remove the ATM-specific code." This bead proposes a new implementation.

Each fact record therefore holds: a stable ID, the source type (ANC / REQ / ADR) and reference, the verbatim user statement, the derived Jev question(s), pass/fail fixtures, a version, and lock status. The verbatim quote is the anchor point, because the paraphrase is exactly where meaning gets lost.

An anchor that proves durable can be promoted to an ADR; it keeps its ID and gains the ADR reference, so history stays intact. Verdicts are stored per run, so re-running a gate after a plan edit lets you diff against the last run and see what changed.

## Open questions

- **Anchor granularity.** One testable constraint per anchor, or can an anchor bundle a few related facts?
- **Anchor capture.** Does the orchestrator auto-detect candidate anchors from what you say and propose them for confirmation, or only record one when you explicitly say "lock this"?
- **Fast-model cross-check.** Which model runs the parallel sanity check — Haiku, a local Qwen — and is its role strictly ambiguity detection (disagreement flags an underspecified anchor), not a second verdict?
- **Relationship to existing skills.** Does plan-jev extend goal-jev / plan-hardening-solo, or stand alone?
- **Jev data handling (resolved for the skill).** Every live rubric, tuning, fixture, or gate call requires both a TypeSafe API key and a per-session `PLAN_ANCHOR_ALLOW_REMOTE_JUDGE=1` opt-in. The script sends one scoped item at a time, never the whole plan, and redacts credentials from output. Whether a particular proprietary plan may be sent remains the user's policy decision.
- **Fixture authorship.** Who writes the pass/fail fixtures that define "locked" — the requirement sub-agent, with your approval?
