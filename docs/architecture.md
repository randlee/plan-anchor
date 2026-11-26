# sc-plan-anchor architecture decisions

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

## ADR-001 Exact work in the script, judgment in the session and Jev

Status: accepted (amended for 0.12.1). Date: 2026-10-09.

Context: Facts stated during planning are lost as context compresses, and
language models cannot count, gate reliably, or keep a request byte-identical.

Decision: Three tiers. `scripts/jev_judge.py` owns IDs, request composition,
gating, run files, coverage, diffs and reports. Live calls use the lazily
imported `sc-decidr` wheel through the generated `decidr_client.py`.
The main session owns capture, approval and triage. Jev answers independent typed questions about one
anchor and one item. Agents run the script once and return its result. See
§1 of the call-graph document.

Consequences: Gating and coverage are reproducible and unit-tested offline.
Agents may not add retry loops or compute verdicts. Jev never sees more than
one anchor and one item. REQ-009, REQ-010.

## ADR-002 Jev payload: anchor, item, questions; intent is not sent

Status: accepted. Date: 2026-10-09.

Context: Jev accuracy degrades as unrelated text grows (a planted
contradiction 28k bytes deep scored 0.46 against 0.79 near the top). Cutting
prose to fit removed evidence Jev used
([experiment](experiments/2026-10-10-redact-only-when-oversize.md)).

Decision: The request is `state.anchor {id, statement, scope}`,
`state.item {id, title, text}` and the gate's question set. Intent and source
metadata are not sent, so each sprint must stand alone as a fresh developer
would read it. Prose is never cut.

Consequences: Missing cross-sprint context shows up as `not_addressed` or
`underspecified` and is fixed in the sprint text. REQ-007, REQ-008.

## ADR-003 Relevance gating threshold

Status: accepted. Date: 2026-10-09.

Context: Answers to the questions in one request are independent, so relevance
cannot gate the others inside Jev. A wavering relevance answer must not be
read as "does not apply".

Decision: `decide()` applies relevance first: `no` at confidence ≥ 0.6 is
`not_applicable`; anything weaker falls through and, without a confident
compliance `yes` and a confident conflict `no`, ends as `underspecified`.
Contradiction outranks underspecification. The anchor's `kind` changes which
roles gate: a `prohibition` ignores compliance, and a `structural` anchor is
not sent to Jev at the planning gate (`deterministic_only`, passing) and is
gated as a directive at the development gate. A live answer within 0.10 of the
threshold is asked again and must agree, else the cell is `underspecified`
(`unstable`); `--no-confirm` turns this off. The re-ask is sent with
`cache=False`, so it is a new Jev call and not a result-cache hit (ADR-017).
Full order in §4 of the data-model document.

Consequences: Cells near 0.6 on unrelated sprints can fail as
`underspecified`; REQ-006 adds an explicit exclusion for that case rather than
changing the threshold. REQ-009, REQ-075, REQ-076.

## ADR-004 Tracker: br or bd, selected once

Status: accepted. Date: 2026-10-17.

Context: Consumers use either `br` or `bd`, which do not share a storage
format, and `bd` needs a Dolt backend this skill cannot provision.

Decision: `anchor_tracker.py resolve` selects once per repository. An explicit
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

Consequences: Anchor storage and both gates are tracker-neutral. REQ-021 to
REQ-025.

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
strings. Which `jev_judge.py` an agent may run is ADR-015's trust rule (the
nearest per-folder install). See §5 of the call-graph document.

Consequences: Drift between harness copies (`install/harness/<target>/` and
the rendered agent bodies) fails CI. The registry and agent identity are
resolved by the runner, not the agents. REQ-031 to REQ-034.

## ADR-010 Independent question tuning

Status: accepted. Date: 2026-10-11.

Context: A planner that tunes its own questions tunes them toward a pass.

Decision: A dedicated `anchor-tuning` subagent of the planner, launched
concurrently after the first draft and INTENT/ANC capture, treats approved
INTENT and ANC as its only authority, freezes an oracle before seeing Jev
answers, judges a candidate pool larger than production in parallel, and
seals a smaller production set. Its Jev queries go only through
`jev_judge.py tournament`, which sends each one through sc-agent `send`, so
every query has a row in the sc-agent session log (ADR-017); the tuner never
calls Jev another way. It tests on temporary plan copies only and never
edits authoritative sources. It may recommend clarity-only INTENT/ANC changes;
the user approves each. Disputed review
failures reach it only through a checked-in `sc-compose` template, and it
returns exactly `plan_violation` or `question_defect`. No desired verdict is
an input; `anchor_tuning_contract.py` rejects one.

Consequences: Leaf plan review waits for the sealed digest. A planner's "the
plan is fine, fix the questions" is untrusted context. REQ-037 to REQ-042.

## ADR-014 The calling agent supplies the plan text; no gate parses plans

Status: accepted. Date: 2026-10-17.

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
tracker are independent choices. Markdown-versus-tracker-copy parity is no longer checked by
the skill; the plan's author owns it. `plan_source.py` and its contract are
not shipped. REQ-021, REQ-057.

## ADR-015 Installer: per-folder, tracker-rendered copies with lock-file ownership

Status: accepted (0.7.0; rewritten for 0.8.0; amended for 0.8.2 and 0.12.1). Date: 2026-10-17.
Amended 2026-10-17 (0.8.2): scripts are rendered templates too; the
single-tracker rule, the install flow and switch equivalence are stated below.

Context: Consumers vendored the skill by copying files, so upgrades left
retired files behind, local edits were overwritten silently, and installed
text named both trackers. 0.7.0 added `install.py` but still shipped a
committed `neutral` render that marketplace installs read, and the gates
trusted a plugin-root copy of `jev_judge.py`. The operator's requirement is
that an install for one tracker names only that tracker. A copy that the
marketplace or a global harness folder shares across repositories cannot be
rendered for one repository's tracker, so that requirement is the reason the
plugin advertises only the installer, hides the plan-anchoring skill and
refuses global destinations. 0.8.0 still copied the seven scripts verbatim,
so at 0.8.1 a `br` install had 117 lines naming `bd` (and a `bd` install 90
naming `br`), all in `jev_judge.py`, `anchor_tracker.py` and
`plan_anchor_settings.py`.

Decision:

- **Single-tracker installs.** Every installed Markdown file and script is a
  `<file>.md.j2` or `<script>.py.j2` template rendered at install time for
  exactly one tracker. An install names only its tracker, as a whole word, in
  every file it writes (copied files and the lock and settings files
  included); the one exception is
  `references/installation-and-troubleshooting.md`, which explains choosing
  and switching trackers. Because every installed file is rendered for one
  tracker, the plugin ships only `plan-anchor-installer`, the plan-anchoring
  skill is not advertised, and global destinations are refused
  (`INSTALL.DEST_GLOBAL`): a marketplace or global copy cannot be rendered
  for one repository's tracker. The flow:
  1. plan-anchor-installer, the only advertised skill, runs `uv run install.py`.
  2. `install.py` renders every `.md.j2` and `.py.j2` with sc-compose for the
     chosen tracker.
  3. It copies the remaining files unchanged: the JSON schemas, the other
     JSON assets (question sets, examples, fixtures), each target's
     `registry.yaml` and the skill's runtime `templates/*.md.j2`. No `.md` or
     `.py` is copied verbatim.
  4. It writes everything to the destination and records each file in the
     lock file.

  Switching trackers (rerunning with the other `--tracker`) leaves a tree
  byte-identical to a fresh install of that tracker, lock and settings
  included, in both directions. `install.py` is the only code that knows
  both trackers: it carries its own selection and settings code and imports
  only the two scripts whose templates have no template syntax
  (`result.py`, `plan_anchor_paths.py`).
- **Plugin.** The marketplace plugin's only skill is `plan-anchor-installer`;
  it registers no agents (see Single-tracker installs for why). The skill runs `uv run
  "${CLAUDE_PLUGIN_ROOT}/install.py"`. The installer reads its package files
  from the plugin directory; at the destination and above it, the settings
  file, the install lock, `.beads/`, whether `.git` exists and the files
  already at the install paths; the home directory (to refuse global
  destinations and end the upward walks); and `PATH` (to find the tracker
  CLI). sc-compose and PyYAML run in-process; it never runs git and runs only
  `br init` (on `--init-br`). It first runs `install.py --dest <folder>
  --status` (read-only; `data.state` is `not_installed`, `older`, `current` or
  `newer`, and it stops on `newer`), asks the user once for a setting the
  folder does not record (tracker; remote-judge consent), never infers
  consent, and never runs or recommends `bd init`. Upgrading is rerunning it in
  each install folder.
- **Rendering.** Every prompt file (SKILL.md, each reference, the `.md`
  assets, each agent body) and every script is an `sc-compose` template under
  `install/templates/`, rendered strictly for `br` or `bd`; there is no neutral
  render and no committed rendered tree. Schemas, JSON assets, `registry.yaml`
  and the skill's runtime `templates/*.md.j2` are copied verbatim (0.8.2;
  until 0.8.1 the scripts were copied verbatim too). Agent frontmatter and
  registries live in `install/harness/<target>/`. The installer's PEP 723
  metadata declares PyYAML, sc-compose and Python 3.11 or newer; dependency
  bounds live in `install.py`. It does not install the live-call dependency:
  callers install the `sc-decidr` wheel separately, as documented in
  [README.md](../README.md). The generated `decidr_client.py` records its wheel
  version and imports it lazily only for live calls (ADR-006).
- **Destination.** `--dest` is any folder: a repository, a folder inside one,
  or a parent folder of many repositories (a non-repository with no `.beads/`
  needs `--tracker` or a settings file, else `TRACKER.REQUIRED`). Global
  locations are refused with `INSTALL.DEST_GLOBAL`, exit 2 (a shared copy
  cannot be rendered for one repository's tracker): the home
  directory, anything inside `~/.claude`, `~/.codex`, `~/.cursor`, `~/.agents`
  (plugin caches included), `/etc/codex`, Claude Code's managed-settings
  directories and the plugin directory. Each target writes
  `<dest>/.<target>/skills/plan-anchoring/` (with that target's
  `registry.yaml`, read by `anchor_runner_contract.py resolve --install-root`;
  `--plugin-root` is an alias) and `<dest>/.<target>/agents/`.
- **Trust rule.** `agent-preflight` and both gate agents accept only the
  canonical `jev_judge.py` of the nearest install, found by walking up from
  the working directory (from the repository root when the working directory is
  outside it) and stopping before the home directory
  (`plan_anchor_paths.py`), under `.claude`, `.codex` or `.cursor`, and only
  when that install's `.sc/plan-anchor/install-lock.json` lists the script
  (0.8.3). A copy in a global location, a farther install's copy, a copy the
  lock does not list (hand-copied, or no lock), a copy under `.agents/` or the
  source tree is `VALIDATION.PATH`. With no determinable home directory the walk ends at
  the filesystem root and the machine-wide directories are still refused.
- **Settings.** The nearest `.sc/plan-anchor/settings.yaml` walking up from
  the working directory wins whole, inside a repository too (0.8.3; it was
  looked up from the git top level); files are never merged. An install into
  a repository subfolder without `--tracker` takes the tracker from the
  nearest settings above it or the repository's `.beads/`. `resolve` reports
  `settings_path` and `settings_inherited`. The disk rule still applies to an
  inherited setting: `br` over a Dolt-backed `.beads/` is `TRACKER.MISMATCH`,
  and the message names the file in effect. An installed copy accepts only
  its own tracker: a setting naming the other is `SETTINGS.INVALID_TRACKER`.
- **Ownership.** `.sc/plan-anchor/install-lock.json` records version,
  tracker, targets and a sha256 per file. A rerun replaces or removes a file
  only when its bytes match the lock; files this version no longer ships are
  removed when unchanged; a modified, foreign or unowned file fails the whole
  install (`INSTALL.CONFLICT`) unless `--overwrite` moves it to
  `.backup/<UTC>/<path>` (`.backup/.gitignore` ignores the backups). A rerun
  keeps every locked target. A pre-lock vendored copy is adopted once by matching
  bytes against `install/legacy-owned.json`, generated from git history.
  Tracker choice uses ADR-004's rules; `bd` needs a Dolt-backed `.beads/`, a
  repository with no `.beads/` needs `--init-br`, and `bd init` is never run.
  Another `--tracker` re-renders every locked target and updates the setting
  without migrating issue data. Every check runs before anything is written;
  `--dry-run` stops there.
- **SessionStart hook.** `hooks/hooks.json` registers `hooks/check_install.py`
  (standard library) for SessionStart. Claude Code runs it; Codex and
  Cursor plugin hook discovery is untested. It prints one line when the nearest
  lock is older than the plugin (`plan-anchor <installed> installed,
  <available> available: run plan-anchor-installer (<folder>)`) and is
  otherwise silent (no lock, current or newer, unreadable). It writes nothing,
  uses no network and always exits 0.

Consequences: Upgrades are safe to rerun and remove `plan_source.py` and other
retired files. A drifted template version or a stale `legacy-owned.json` fails
CI. Known limitations:

- Claude Code and Codex document skill discovery only up to the git root, so a
  parent-folder install may not be visible from a session started inside a
  child repository. Not verified in a harness.
- Installed prompts and scripts name one tracker, so a `bd` repository under
  a `br` parent install needs its own install (nearest wins); otherwise the
  gate agents return `VALIDATION.TRACKER` or `resolve` returns
  `SETTINGS.INVALID_TRACKER` (a `bd` setting) or `TRACKER.MISMATCH` (a
  Dolt-backed `.beads/`).
- Open decision, not changed: Codex documents `.agents/skills` as its
  repository skill directory, while `--target codex` installs `.codex/skills`.
  Since 0.8.3 the trust rule does not accept a copy under `.agents/`.

REQ-059 to REQ-064, REQ-067 to REQ-072, REQ-074, REQ-080; ANC-032 to ANC-036.

## ADR-017 Jev queries are recorded once, in sc-agent's session log

Status: accepted at phase j plan review, 2026-11-24; binding on sprint j-4,
which builds it when it merges into plan-anchor's integrate/phase-j.
Date: 2026-11-24.

Context: Every Jev query from every tool goes through sc-agent `send` or
`send_batch` and gets one session-log row keyed by its ULID `session_id`
(owner ruling, 2026-11-24). Run files, result lines and the tournament log
copied the answers, `model_answered` and attempt counts that the row already
holds.

Decision: Plan-anchor's records hold only what it derives (verdicts, leaning,
rankings) and its own ids (`anchor_id`, `candidate_id`, repeat), and reference
the `session_id` of each query they used. They never copy the composed request body, Jev's
answers, `model_answered` or attempt counts.

Consequences: Reading an answer, or rescoring a tournament with `--results`,
needs the sc-agent session log. REQ-013, REQ-038, REQ-076, REQ-083.
