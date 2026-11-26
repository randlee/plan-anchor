# sc-plan-anchor requirements

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

**REQ-001** The skill shall store every anchor in `anchors.json` with an immutable verbatim `quote` and a separately authored, user-approved testable `statement`.
Source: PRD "Provenance & reporting"; `design/data-model-and-gating.md` §2. Status: shipped.

**REQ-002** The script shall allocate `ANC-NNN` IDs as max plus one, never reuse them, and keep register IDs for REQ and ADR anchors.
Source: `design/data-model-and-gating.md` §2. Status: shipped.

**REQ-003** Only `locked` and `promoted` anchors shall be judged by `--all`, and an explicit `--anchor` on a proposed or retired anchor shall be refused (`ANCHOR.NOT_LOCKED`) unless `--include-unlocked` is given; no anchor to judge is `ANCHOR.NONE` and an unknown ID `ANCHOR.UNKNOWN`.
Source: `design/data-model-and-gating.md` §6. Status: shipped.

**REQ-004** Nothing shall be locked without user confirmation. `add` shall always refuse a statement that repeats the quote and a likely duplicate (word overlap ≥ 0.6, `ANCHOR.DUPLICATE_CANDIDATE`, unless `--allow-similar`; an existing REQ/ADR ID is `ANCHOR.DUPLICATE`); other lint findings are warnings unless `--strict` (`ANCHOR.LINT`); the testability rubric runs only with `--rubric` (`ANCHOR.NOT_TESTABLE` unless `--allow-untestable`).
Source: SKILL.md "Design positions" (Capture); `references/anchor-capture.md`. Status: shipped (lint and rubric are not mandatory in the script; the skill instructs running them).

**REQ-005** `anchors.md` shall be rendered from `anchors.json` and never hand-edited.
Source: `design/data-model-and-gating.md` §1. Status: shipped.

**REQ-006** An anchor shall be able to carry an `exclude` list of `{item, reason}` entries; `judge` shall skip each listed cell without calling Jev, report it as `excluded` (passing) with its reason in the run summary, report, coverage, diff and `anchors.md`, with no approval workflow and no other new verdict state.
Source: OPERATOR; `design/anchor-tuning-stand-ins.md` "Anchor exclusions". Status: shipped.

## Jev requests and gating

**REQ-007** Each Jev request shall contain exactly `state.anchor {id, statement, scope}`, `state.item {id, title, text}`, and the gate's question set, and shall not contain intent, source metadata, or a second anchor or item.
Source: OPERATOR; PRD "Keep the state small"; `design/data-model-and-gating.md` §3. Status: shipped.

**REQ-008** The planning gate shall send a bead whole, never shorten prose.
Source: OPERATOR; `experiments/2026-10-10-redact-only-when-oversize.md`. Status: shipped.

**REQ-009** The script shall turn independent answers into one verdict in code, first match wins. For a directive: relevance `no` at confidence ≥ 0.6 is `not_applicable`; a lower-confidence relevance `no` falls through and ends as `underspecified`; then `contradicted`, `underspecified`, `not_addressed`, and `asserted_only` or `satisfied` only when compliance is `yes` and conflict is a confident `no` (otherwise `underspecified`). A prohibition and a structural anchor gate differently (REQ-075).
Source: OPERATOR; `design/data-model-and-gating.md` §4. Status: shipped.

**REQ-010** Coverage across items and run-to-run differences shall be computed by the script from run files, never asked of Jev. Dry-run run files already on disk shall be skipped.
Source: PRD "Do the counting in code"; `design/data-model-and-gating.md` §5. Status: shipped.

**REQ-013** Each live run shall be written to its own run file that copies the statement, quote and provenance it judged. Each anchor result in a run file shall carry plan-anchor's own `anchor_id` and the `session_id` of every Jev query that produced it (two when the request was confirmed, REQ-076). A run file shall not contain Jev's answers, `model_answered` or `attempts`; they are read from the sc-agent session row with that `session_id`.
Source: `design/data-model-and-gating.md` §1–2; OPERATOR (phase j session-log ruling, 2026-11-24). Status: shipped for the copied statement, quote and provenance; planned for `session_id` in place of the answers, `model_answered` and `attempts` (phase j).

**REQ-014** A failing report shall name the anchor and show its statement next to the user's verbatim quote.
Source: PRD "Provenance & reporting". Status: shipped.

## Data leaving the machine and configuration

**REQ-019** Repository settings shall live in `.sc/plan-anchor/settings.yaml`: YAML with snake_case keys (`schema_version`, `anchor_tracker`, `allow_remote_judge`, `plan_dir` (REQ-088)), committed, no secrets, `schema_version: 1`, and strict validation that rejects unknown keys, duplicate keys and wrong types.
Source: OPERATOR. Status: shipped. Values are parsed with PyYAML's `SafeLoader` (YAML 1.1), so `allow_remote_judge: yes` reads as `true` and is accepted; `plan_anchor_settings.py set` writes only `true` or `false`. "Committed" is checked only as not git-ignored (`set` reports `settings_ignored_by_git`); tracking is not checked.

## Trackers

**REQ-021** Anchor and question storage, and both gates, shall work with either `br` or `bd`.
Source: OPERATOR; INTENT "Success"; retired ANC-007 (requirement retained). Status: shipped.

**REQ-022** Tracker selection shall be: an explicit `anchor_tracker` in the settings file in effect (the nearest, REQ-070) wins and is validated against disk; otherwise a Dolt-backed `.beads/` selects `bd`, any other `.beads/` selects `br`, and no `.beads/` selects `br`; a mismatch is an error, never a silent switch.
Source: OPERATOR. Status: shipped. Since 0.8.2 `install.py` applies these rules to both trackers; an installed `anchor_tracker.py` is rendered for one tracker (REQ-059) and refuses a setting naming the other (`SETTINGS.INVALID_TRACKER`) or a `.beads/` that does not fit it (`TRACKER.MISMATCH` in a `br` install, `TRACKER.DOLT_REQUIRED` in a `bd` install), with the installer's `--tracker` as the suggested action.

**REQ-023** The skill and the installer shall never run or recommend `bd init`; `br init` is the only bootstrap and runs only on `anchor_tracker.py write --init` or `install.py --init-br`, with fixed argv and no shell.
Source: OPERATOR. Status: shipped.

**REQ-025** Both gate reviewers shall take the tracker from `anchor_tracker.py resolve`, never from a default, and reject a mismatch with a supplied value.
Source: OPERATOR; SKILL.md Step 1. Status: shipped.

## Agents and runner

**REQ-031** Each agent definition shall be installed in its harness directory (`.claude/agents`, `.codex/agents`, `.cursor/agents`) from one body template plus per-harness frontmatter (`install/harness/<target>/agents/`), with bodies identical across harnesses after frontmatter and registries identical after the harness path.
Source: ANC-009. Status: shipped.

**REQ-032** The runner shall resolve the agent path, registry version, declared model and file hash once per invocation, so agents contain no registry trust logic. The gate agents do carry the `jev_judge.py` trust rule (REQ-069) as prompt text, which `agent-preflight` enforces.
Source: INTENT "Success"; retired ANC-003 (requirement retained). Status: shipped.

**REQ-033** Each agent invocation and result shall carry exactly one fenced JSON object, rejected at the boundary when malformed.
Source: INTENT "Success"; retired ANC-004 (requirement retained). Status: shipped.

**REQ-034** Agent inputs shall carry validated paths and identifiers confined to the Git workspace, never shell command strings.
Source: retired ANC-008 (requirement retained); `design/architecture-and-call-graphs.md` §5. Status: shipped.

**REQ-036** The planning gate and the code-review (development) gate shall be separate agents with separate Python entry points; plan review is production, code review is not.
Source: OPERATOR. Status: planned. The agents are separate; both run through `jev_judge.py judge --gate plan|dev`.

## Question tuning

**REQ-037** Question tuning shall translate approved INTENT and ANC records into accurate Jev questions without optimizing for a favorable plan verdict, and the tuning contracts shall reject a desired verdict as an input.
Source: ANC-010, ANC-031. Status: shipped.

**REQ-038** `anchor-tuning` shall run as a dedicated Opus/Sol (Cursor: Grok at high effort) subagent of the planner that judges a candidate pool larger than production in parallel, ranks it and seals a smaller production set. The tuner's Jev queries shall go only through `jev_judge.py tournament`, which sends each one through sc-agent `send` so that it gets a row in the sc-agent session log; the tuner shall not call Jev any other way.
Source: ANC-020, ANC-026, ANC-027; OPERATOR (phase j session-log ruling, 2026-11-24). Status: shipped (the tournament sends through the sc-decidr client).

**REQ-039** `anchor-tuning` shall test candidates only on temporary plan copies with diagnostic additions and removals and shall not modify authoritative plan sources.
Source: ANC-021, ANC-022. Status: shipped.

**REQ-040** The planner shall launch one named `anchor-tuning` subagent concurrently after the first draft and INTENT/ANC capture, and leaf plan review shall wait for the sealed question-set digest.
Source: ANC-023; INTENT "Review policy". Status: shipped.

**REQ-041** `anchor-tuning` may recommend clarity-only INTENT/ANC refinements but shall not apply them; the user approves each, and approval invalidates the affected oracles and rankings.
Source: ANC-024, ANC-025. Status: shipped.

**REQ-042** After plan review, disputed failures shall go to `anchor-tuning` only through a checked-in `sc-compose` Jinja2 template, and the tuner shall return exactly one of `plan_violation` (question digest unchanged) or `question_defect`.
Source: ANC-028, ANC-029, ANC-030. Status: shipped.

## Python and CLI contract

**REQ-049** Every error shall be printed as the JSON envelope `{success: false, data, error: {code, message, recoverable, suggested_action}}`, never a traceback.
Source: OPERATOR; ADR-007. Status: shipped; argparse usage errors are `VALIDATION.INPUT` envelopes on stdout in every CLI since 0.7.1 (`--help` still prints text, exit 0).

**REQ-050** Exit codes shall be 0 when a command ran, with negative results in `data` (`summary.pass`, `valid`, `clean`, `pass`, `mismatches`, `judged`, `likely_duplicates`, `added`/`updated` with `refused`, `changed`, `violation`, `state`); 2 with the typed error envelope when the tool could not do its job; 130 on interrupt; never 1. A Jev call that got no answer (any `judge` or `check-fixtures` cell, `dedupe --jev` pair, `rubric` or `add --rubric` candidate) shall be exit 2, never a negative result; the partial run is still written and named in `data`. Refusals (`data.refused`, `recoverable` included) and no-ops (`data.changed: false`) exit 0. The repository CI scripts' drift and staleness checks, and their failures, also exit 2.
Source: OPERATOR (0.7.2; 0.8.3: "jev API failure (or similar) should return an error"); ADR-007. Status: shipped (Jev failures were exit 0 with `verdict: error` until 0.8.3).

**REQ-051** Every agent launch shall report a typed failure reason, and failures shall never fall back silently.
Source: OPERATOR; `design/anchor-tuning-stand-ins.md` "Failures". Status: shipped for runner contract failures.

## Documentation and packaging

**REQ-057** Both gates shall judge the sprint text the calling agent supplies through `judge --item-file` (or stdin), read from wherever that agent wrote the plan, with no plan parsing or format requirement; anchor records shall use only the tracker `anchor_tracker.py` resolves, and installed skill and agent text shall name only the installed tracker's commands.
Source: OPERATOR (2026-10-17); INTENT "Success"; ADR-014; ANC-016; ANC-017. Status: shipped.

## Installer

**REQ-059** `install.py` shall run through `uv run` with PEP 723 metadata (PyYAML, `sc-compose` >=1.8.0,<2, Python 3.11 pin) and render every installed Markdown file (SKILL.md, each reference, the `.md` assets, each agent body) and every script from a `<file>.md.j2` or `<script>.py.j2` `sc-compose` template strictly for the selected tracker, so an install names only its tracker, as a whole word, in every file it writes (copied files, the lock and the settings file included), except `references/installation-and-troubleshooting.md`, which names both to explain switching. There shall be no neutral render and no committed rendered tree; only schemas, JSON assets, `registry.yaml` and the skill's runtime templates shall be copied verbatim, and no `.md` or `.py` file. `compose-item`, `shape` and `plan-items` help and errors shall use the selected tracker's command names.
Source: OPERATOR (0.8.2); ANC-032, ANC-034; ADR-015. Status: shipped (no neutral render since 0.8.0; scripts rendered since 0.8.2).

**REQ-060** An install shall record version, tracker, targets and a sha256 per file in `.sc/plan-anchor/install-lock.json`; a rerun of the same version shall change nothing, and an upgrade shall remove unchanged files the new version no longer ships while keeping files it does not own.
Source: OPERATOR; ADR-015. Status: shipped.

**REQ-061** The installer shall refuse, before writing anything, a modified, modified-retired, unowned or foreign file (`INSTALL.CONFLICT` naming each path), and `--overwrite` shall move each to `.backup/<UTC %Y%m%dT%H%M%SZ>/<path>` before replacing it, writing `.backup/.gitignore` (`*`) with the first backup.
Source: OPERATOR; ADR-015. Status: shipped.

**REQ-062** A repository vendored before the lock existed shall be adopted once: a file is owned only when its bytes match a file an earlier version shipped, as recorded in `install/legacy-owned.json`, which is generated from git history and checked in CI.
Source: OPERATOR; ADR-015. Status: shipped.

**REQ-063** Tracker switching shall follow ADR-004's rules: a detected tracker that differs from the installed one is `TRACKER.MISMATCH` until `--tracker` names it; a switch re-renders every locked target, updates `anchor_tracker`, and states that issue data is not migrated; `bd` requires a Dolt-backed `.beads/` (`TRACKER.DOLT_REQUIRED`), and no `.beads/` requires `--init-br` (`TRACKER.NOT_INITIALIZED`).
Source: OPERATOR; ADR-015. Status: shipped.

**REQ-064** `--dry-run` shall report the full plan and write nothing, run no `br init`, and change no file, including for a tracker switch.
Source: OPERATOR; ADR-015. Status: shipped.

## Remote-judge consent

**REQ-065** Consent to send plan text to TypeSafe shall be `allow_remote_judge: true|false` in the committed `.sc/plan-anchor/settings.yaml` (the nearest file), never an environment variable and never inferred from past runs; the answer recorded with `plan_anchor_settings.py set allow_remote_judge true|false`.
Source: OPERATOR (2026-10-17); OPERATOR (phase j plan-review ruling, 2026-11-24) (consent covers TypeSafe only). Status: shipped (0.7.1).

**REQ-066** The installer shall take `--allow-remote-judge` / `--no-remote-judge` and record the answer in the settings file; a rerun without either shall keep the recorded value.
Source: OPERATOR (2026-10-17); ADR-016. Status: shipped (0.7.1).

## Per-folder installs (0.8.0)

**REQ-067** The marketplace plugin shall ship one skill, `plan-anchor-installer`, and no agents, with no loadable plan-anchoring skill, because every installed file is rendered for one repository's tracker (REQ-059) and a marketplace copy cannot be; the skill and `install.py` shall read only the plugin's package files plus, at the destination and above it, the settings file, the install lock, `.beads/`, whether `.git` exists and the files already at the install paths, the home directory (to refuse global destinations and end the upward walks) and `PATH` (to find the tracker CLI); sc-compose and PyYAML run in-process, and the installer never runs git and runs only `br init`, on `--init-br`. The skill shall compare versions first (`install.py --dest <folder> --status`, read-only) and stop when the folder's install is newer, ask the user once for a setting the folder does not record (tracker; remote-judge consent), never infer consent, never run or recommend `bd init`, and upgrade by rerunning the same command in each install folder.
Source: OPERATOR; ANC-035; ADR-015 (Single-tracker installs). Status: shipped.

**REQ-068** `install.py --dest` shall accept any existing folder (a repository, a folder inside one, or a parent folder of repositories) and refuse global locations with `INSTALL.DEST_GLOBAL` and exit 2, because a copy shared across repositories cannot be rendered for one repository's tracker (REQ-059): the home directory, anything inside `~/.claude`, `~/.codex`, `~/.cursor` or `~/.agents` (plugin caches included), `/etc/codex`, Claude Code's managed-settings directories, and the plugin directory. A non-directory is `INSTALL.DEST`; a folder that is not a repository and has no `.beads/` needs `--tracker` or a settings file (`TRACKER.REQUIRED`).
Source: OPERATOR; ANC-036; ADR-015 (Single-tracker installs). Status: shipped.

**REQ-069** `agent-preflight` and both gate agents shall accept only the canonical `jev_judge.py` of the nearest install (under `.claude`, `.codex` or `.cursor`), walking up from the working directory and stopping before the home directory, and only when that install's `.sc/plan-anchor/install-lock.json` lists the script; a copy in a global location, a farther install's copy, a copy the lock does not list (hand-copied, or no lock), a copy under `.agents/` or the source tree shall be `VALIDATION.PATH`.
Source: OPERATOR; ADR-015 (supersedes the fallbacks in ADR-008's 0.7.0 form). Status: shipped; the lock requirement and the removal of `.agents/` are 0.8.3.

**REQ-070** The nearest `.sc/plan-anchor/settings.yaml` walking up from the working directory (inside a repository too) shall win whole, with no merging across files; `resolve` and `plan_anchor_settings.py show` shall report `settings_path` and `settings_inherited`. The disk rule shall still apply to an inherited setting, and `TRACKER.MISMATCH` shall name the file in effect.
Source: OPERATOR; ADR-015. Status: shipped.

**REQ-071** Each target's agent registry shall be installed at `<dest>/.<target>/skills/plan-anchoring/registry.yaml`, and `anchor_runner_contract.py resolve` shall read it through `--install-root` (`--plugin-root` accepted as an alias).
Source: OPERATOR; ADR-015. Status: shipped.

**REQ-072** A SessionStart hook (`hooks/hooks.json`; Claude Code runs it; Codex and Cursor plugin hook discovery is untested) shall print one line when the nearest install lock is older than the plugin and otherwise stay silent (no lock, current or newer, or anything unreadable); it shall write nothing, use no network and exit 0.
Source: OPERATOR; ADR-015. Status: shipped.

**REQ-073** Every plan-anchor CLI and the SessionStart hook shall read and write UTF-8 on stdin, stdout and stderr on every platform, and the nearest-install, settings and lock lookups, the global-location refusal and `install.py`'s destination check shall work when the home directory cannot be determined (the walk then ends at the filesystem root; a `--dest` starting with `~` is `INSTALL.DEST`).
Source: OPERATOR (0.8.1). Status: shipped.

**REQ-074** Rerunning `install.py` with the other `--tracker` over an install shall leave a folder byte-identical to a fresh install of that tracker into an empty folder, every target, the lock and settings files included, in both directions (`br` to `bd` and `bd` to `br`).
Source: OPERATOR (0.8.2); ANC-033; ADR-015. Status: shipped.

## Judging and installer details

**REQ-075** An anchor's `kind` shall be `directive` (the default, and the reading of a record without one), `prohibition` or `structural`, set by `add --kind` or `update --kind` and checked by `validate`. A prohibition ignores compliance: `not_applicable` on a confident relevance `no`, `contradicted` on a confident conflict `yes`, `underspecified` when relevance is unclear or below the threshold or conflict is not a confident `no`, `asserted_only` when the development gate's evidence is a confident `no`, else `satisfied`. A structural anchor is never sent to Jev at the planning gate (verdict `deterministic_only`, which passes, also in `check-fixtures`) and is gated as a directive at the development gate.
Source: CHANGELOG 0.3.0. Status: shipped.

**REQ-076** When a live answer to a gating role (not a prohibition's compliance) is within 0.10 of the threshold, `judge` and `check-fixtures` shall send the identical request once more with `cache=False`, so that the second send is a new Jev call with its own session row and not a result-cache hit: agreement sets `confirmed`; disagreement makes the cell `underspecified` with `unstable`, both verdicts and both `session_id`s; a second call with no answer keeps the first verdict, records `confirm_error` and exits 2 (REQ-050). It is on by default; `--no-confirm` turns it off and `--confirm-near-threshold` only states the default; fixture answers are never re-asked. Every judged result carries `leaning` (the verdict at threshold 0), and an `underspecified` one carries `low_questions`. When `--repeat` of `batch` or `bead-batch`, or the tournament request's `repeat_count`, is greater than 1, every repeat shall be sent with `cache=False`, all repeats in one call that keeps their order, so that each repeat is its own Jev call with its own `session_id`. The second and third testability confirmations of `rubric` and `add --rubric` shall also be sent with `cache=False`.
Source: CHANGELOG 0.3.0, 0.7.3; OPERATOR (phase j session-log ruling, 2026-11-24). Status: shipped; planned for `cache=False` and both `session_id`s in place of the second answers (phase j).
Source: OPERATOR (phase j session-log ruling, 2026-11-24); OPERATOR (phase j ruling, 2026-11-24); `skills/plan-anchoring/references/question-tuning.md` "Run". Status: planned (phase j; today `_rubric_judgement` in `jev_judge.py.j2` re-asks with the cache on).

**REQ-078** The record subcommands shall be `add` (`--status proposed|locked`, default `proposed`; `--stated-by` defaults to `USER`), `update`, `retire`, `exclude` (`--remove`), `set-beads`, `promote --adr` and `render`; `retire` and `promote` bump `version`, `exclude` and `set-beads` do not, and `promote` does not check the anchor's status. No subcommand moves `proposed` to `locked` or writes `question_overrides`, which `judge` still reads from the record before `--overrides-file`.
Source: CHANGELOG 0.2.0, 0.3.0; `design/data-model-and-gating.md` §2, §6. Status: shipped.

**REQ-079** `compose-item` shall build the item text from a tracker `show --json` (`--show-json`, `-` for stdin), optional `--children-json` and `--sections`; `--for plan` keeps the description and acceptance criteria and drops children. `shape` shall report size and shape metrics and never gate.
Source: CHANGELOG 0.3.0. Status: shipped.

**REQ-080** `install.py --status` shall be read-only and take only `--dest` (else `VALIDATION.INPUT`); it reports `state` (`not_installed`, `older`, `current`, `newer`; an unparseable version counts as `older`) and, when the folder has no lock, `covering_install {root, version, valid}` from the nearest lock above. An install shall report `previous_version`, `tracker_origin`, `switched`, `migration` (no lock before), the `plan`, `warnings`, `notes` and `commit_paths` (empty on a dry run), and a rerun shall keep every locked target and add any newly requested one (default `claude`).
Source: OPERATOR; ADR-015. Status: shipped.

**REQ-081** When a gate agent's question bead cannot be shown by the tracker, the agent shall stop with `TRACKER.SHOW_FAILED` rather than judge with the default questions.
Source: CHANGELOG 0.8.3. Status: shipped (prompt text in `anchor-plan-review` and `anchor-sprint-review`).

**REQ-088** The anchor record (`intent.md`, `anchors.json`, `anchors.md`, `anchor-runs/`) shall live in the current phase's plan folder, `docs/plans/phase-<current>/` with the phase id written out, named by `plan_dir` in `.sc/plan-anchor/settings.yaml`. `plan_anchor_settings.py set plan_dir` records it and `show` reports it; a value that is absolute, has an empty, `.` or `..` part, a backslash or a `<placeholder>` is `SETTINGS.INVALID_PLAN_DIR` in the file and `VALIDATION.INPUT` on `set`; the installer and `anchor_tracker.py write` keep it. The skill sets `A="$P/anchors.json"` from it and asks the user when it is unset; no shipped file names a literal folder. A new record's `plan` and `intent_ref` default to the folder holding `--anchors` and `intent.md` beside it.
Source: OPERATOR (issue #58, 0.8.6). Status: shipped.

## Session log and run records (phase j)

**REQ-083** A `--dry-run` shall only check that its input composes into valid requests and show the would-send requests, redacted, on stdout, or in the file named by `--out` (for `judge`, `--out` names the requests file on a dry run). A dry run shall write no file under `anchor-runs/`, no run file, no result line and no log event. A `--out` path inside `anchor-runs/` on a dry run shall be refused with `VALIDATION.INPUT`. `--dry-run` and `--answers-file` execution shall make zero network calls.
Source: OPERATOR (phase j session-log ruling, 2026-11-24); INTENT "Success"; retired ANC-006 (requirement retained). Status: planned (phase j; today a dry run writes a run file marked `dry_run`, and `tournament --dry-run` writes `requests.dry-run.jsonl` in `--out`).

