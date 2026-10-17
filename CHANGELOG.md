# Changelog

`VERSION` holds the release version. Contributors bump the patch of each artifact they edit and add a line under Unreleased; a release bumps the minor in unison and turns Unreleased into a dated section. `scripts/check_version_sync.py` enforces both (see CONTRIBUTING.md).

## Unreleased

- Route planning reviewers through complete Markdown or bd/br sprint descriptors, independently selecting bd/br anchor storage. Preserve legacy bead callers, validate normalized item digests, and align all harness prompts and invocation instructions (edited artifacts 0.5.0 → 0.5.1).
- Select the planning gate's anchor tracker with `scripts/anchor_tracker.py` instead of a hardcoded `ANCHOR_TRACKER=br`. An explicit `anchor_tracker` in the committed `.sc/plan-anchor/settings.yaml` (`schema_version: 1`, strict keys) wins and is checked against disk: `bd` only with a Dolt-backed `.beads/`, `br` only without one; otherwise a Dolt-backed `.beads/` detects `bd` and anything else `br`. `resolve` is read-only; `write` persists the choice for commit and `write --init` runs `br init` (fixed argv) when there is no `.beads/`. The skill never runs or recommends `bd init`; Dolt provisioning is outside its scope. New code uses a frozen-dataclass `Result[T, E]` (`scripts/result.py`) with typed errors and the `{success, data, error}` envelope. PyYAML (5.1+) is now required by `anchor_tracker.py` only; other scripts stay standard-library only. Document br install/bootstrap/sync, the selection rules, and the settings file; this repository pins `anchor_tracker: br`. Scope: planning gate (`anchor-plan-review`) only; the development gate (`anchor-sprint-review`) is unchanged and still uses `bd` (SKILL.md, planning-review-workflow, agent-delegation-workflow, anchor-plan-review 0.5.1 → 0.5.2; installation-and-troubleshooting, bead-layout 0.5.0 → 0.5.1).
- Harden anchor tracker selection from review: `anchor_tracker.py` reports an absolute `cli_path`, so `write --init` no longer breaks when `which` answers relative to the caller's directory (Windows current-directory search, relative PATH entries; the Windows CI failure). Every error now exits 2 with the typed error on stdout, matching `jev_judge.py`/`plan_source.py` (exit 1 stays reserved for a completed run with a negative result); argument errors are `VALIDATION.INPUT` envelopes, not argparse text; an unanswerable `git check-ignore` is reported instead of silently returning null. Tracker tests skip with a stated reason when PyYAML is absent, and CI adds a `dependency-floor` job that runs the suite without PyYAML and on PyYAML 5.1. Document that `item_path` holds one `data.sprints` element, not the discovery envelope, and correct the sc-compose minimum to 1.7.0 (SKILL.md, planning-review-workflow, agent-delegation-workflow 0.5.2 → 0.5.3; installation-and-troubleshooting 0.5.1 → 0.5.2).

## 0.5.0 — 2026-10-14

- Require predecessor objects for every protocol migration, including the
  first history event, in request/result schemas and the relational contract.
  Exercise real before/after histories in calibration regression tests.

- Accept initial tuning-history events without a predecessor and preserve existing evaluator authority IDs in calibration request and result contracts.
- Align the tuning result template and JSON schema with the shared runner's
  versioned response envelope, including failures. Add regression coverage
  across rendered testability, tuning, triage, and error responses.
- Clarify that the calibration descriptor and frozen corpus have independent
  schema versions, use the corpus's canonical JSON digest, and preserve its
  legacy `atomicity` labels as the `single_constraint` role.
- Publish the minor release with synchronized artifact and manifest versions.

- Package `sc-plan-anchor` for the Cursor marketplace. Gate subagents pin unversioned Composer; the independent tuner pins unversioned Grok at high effort (`grok[effort=high]`). Cursor launches them with the Task tool and does not fall back to the parent chat.
- Keep Claude, Codex, and Cursor agent bodies and registry comments identical. Harness differences stay in frontmatter and registry paths.
- Keep maintainer tests outside the marketplace plugin at
  `tests/sc-plan-anchor/`, so installing the skill does not redistribute the
  upstream unit suite or invite consumers to wire it into their own CI.
- Rebuild progressive disclosure from the current tested skill language: keep
  dependency verification, agent delegation, design positions, and hard stops
  in `SKILL.md`; move each operation's existing workflow text verbatim behind a
  role router without changing Jev, gate, tuning, tracker, or agent behavior.
- Pin CI and the skill baseline to the released `sc-compose` 1.7.0 CLI on
  Linux, macOS, and Windows, and declare the JSON Schema test dependency.
- Add one shared agent-runner contract that resolves a registered Claude or
  Codex agent once, validates a single typed fenced request/result, detects
  post-resolution definition changes, and writes only redacted attestations.
- Calibrate the five-question anchor-testability rubric against a frozen,
  plan-independent 17-case oracle: 85/85 semantic cells and 4/4 statement-only
  duplicate cases matched across byte-identical live Jev repeats. Requirement
  form is deterministic lint; low-confidence cells are inconclusive and
  competing confident answers are unstable.
- Separate question-tournament semantic calibration from the unchanged
  fail-closed production confidence gate, and carry source-neutral canonical
  tuning history across Markdown and `bd`/`br` plan sources.
- Install the Phase A `anchor-tuning` dogfood agent in both harness registries
  (Opus for Claude, Sol for Codex) and add schema-validated `sc-compose`
  templates for tune requests, review feedback, and Standard-envelope results.
- Package the fully qualified `sc-plan-anchor` plugin in Claude and Codex repository marketplaces. Claude declares its Sonnet/Opus agents in the plugin manifest; Codex discovers the shared skill and the skill launches its bundled Luna/Sol definitions explicitly through the Agent tool.

## 0.4.0 — 2026-10-10

- Split harness adapters: Claude Code gate agents use Sonnet and its independent question tuner uses Opus; Codex gate agents use Luna and its tuner uses Sol. Claude invocation now names the Agent tool, and both registries are version-checked.
- Made question tuning independent of the planner. The tuner derives and freezes an oracle from approved intent and anchors before its first Jev call, iterates wording against role-level expectations without a plan-pass objective, and returns the oracle digest, rationales, run IDs, and acceptance table.
- Added `agent-preflight` to canonicalize and confine agent inputs to the Git workspace, reject unsafe identifiers and PR numbers, and require the running judge to match the selected script. Agents validate harness-controlled script paths before execution.
- Redact the live TypeSafe key and bearer credentials recursively from all script output. Installation reads the key silently instead of placing it in a command line.
- `diff` now reports composed-item growth. Remediation defaults to cuts and replacements; a failing-to-passing edit may grow only when added text traces to a locked ANC/REQ/ADR that predates the failed run.
- Documentation consistently treats Jev as required for the normal capture, tuning, fixture, and gate workflow while preserving offline dry-run and fixture-answer support for development and CI. Examples now use measured, non-placeholder metadata.
- Planning gate sends a bead whole when it fits one Jev request (`--max-item-chars`, and `--max-request-bytes` for every anchor). Otherwise blocks longer than `--max-code-lines` are reduced to signatures one at a time, longest first, until it fits. `PLAN.TOO_LARGE` is unchanged. Measured on a 13-bead plan with 6 anchors: underspecified cells went from 15 to 8, and passing beads from 1 to 6 (`docs/experiments/2026-10-10-redact-only-when-oversize.md`).
- Planning gate is a quality loop: Jev's failing verdicts and low confidence are the planner's signal to fix the bead, then re-run. `underspecified` results carry `low_questions`, printed as `Low:` report lines. `anchor-plan-review` returns Jev's ruling unchanged plus `to_fix` per failing cell, resolves overrides deterministically, and can reuse a run after one timed-out or malformed agent response without another Jev call.
- Fixed directive gating so a low-confidence, `unclear`, or otherwise non-confident `no` conflict answer is `underspecified`; only a confident conflict `no` can reach `asserted_only` or `satisfied`.

## 0.3.0 — 2026-10-10

Shaped by first use on a real multi-sprint plan and 245 live Jev requests against it (`docs/experiments/2026-10-10-phase-h-jev-experiments.md`).

- Anchors: `statement` is a testable requirement; the user's exact words are a separate immutable `quote`. `add` refuses a statement equal to its quote and near-duplicates (`ANCHOR.DUPLICATE_CANDIDATE`); `update --statement` rewords with history; `retire` replaces hand edits.
- Anchor `kind`: `directive`, `prohibition` (judged on contradiction only), `structural` (deterministic check only, verdict `deterministic_only`).
- New subcommands: `lint` (testability rules), `rubric` (Jev-judged testability, six criteria), `dedupe` (lexical, optionally Jev), `shape` (per-bead size, code/prose, references, repeated paragraphs), `compose-item --for plan|dev`, `diff --expected`.
- Planning gate judges title, description and acceptance criteria; never shortens prose; long code goes to Jev as signatures; an oversized bead is `PLAN.TOO_LARGE` and triaged as a symptom (unapproved work, prose and ceremony, split last).
- Gate caps: plan 24,000 bytes (what Jev reads reliably), dev 64,000. Near-threshold cells are re-asked once; every result carries `leaning`.
- New agent `anchor-question-tune` (background): proves and refines per-anchor question wording against fixtures and known beads.
- New references: `planning-gate`, `development-gate`, `question-tuning`, `triage-and-iteration`, `plan-size-and-shape`, `measured-behaviour`.
- 134 offline tests; CI on Linux, macOS, Windows.

## 0.2.0 — 2026-10-10

- Script hardened from QA review: three attempts per anchor with backoff, context-window shortening at the development gate, response validation, exit codes 0/1/2, dry runs written to the run directory, `compose-item`, `update`, `check-fixtures`.
- Agents gain `script` input, Invocation sections and the Codex/Cursor inline fallback; `bd comment --file` fixed; per-gate references added.
- First live verification against `jev-1.13.0` on both gates. Installed in sc-lint (PR #207).

## 0.1.0 — 2026-10-09

- Initial skill: SKILL.md, nine references, `jev_judge.py`, question sets, templates, `anchor-plan-review` and `anchor-sprint-review` agents, registry.
