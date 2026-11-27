# sc-plan-anchor architecture decisions: frozen

ADR-015 is frozen, unconverted and unjudged, pending the owner's decision on a shared
installer kit (owner ruling 2026-11-26). It is moved here from
[architecture.md](architecture.md) unchanged, so that Raptor does not read it.

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

