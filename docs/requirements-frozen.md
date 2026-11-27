# sc-plan-anchor requirements: frozen

These records are frozen, unconverted and unjudged, pending the owner's decision on
whether a shared installer kit (REQ-059 to REQ-074, REQ-080) or the shared CLI envelope
(REQ-049, REQ-050; REQ-JEV-0211) owns them (owner ruling 2026-11-26). They are moved here
from [requirements.md](requirements.md) unchanged, so that Raptor does not read them.

**REQ-049** Every error shall be printed as the JSON envelope `{success: false, data, error: {code, message, recoverable, suggested_action}}`, never a traceback.
Source: OPERATOR; ADR-007. Status: shipped; argparse usage errors are `VALIDATION.INPUT` envelopes on stdout in every CLI since 0.7.1 (`--help` still prints text, exit 0).

**REQ-050** Exit codes shall be 0 when a command ran, with negative results in `data` (`summary.pass`, `valid`, `clean`, `pass`, `mismatches`, `judged`, `likely_duplicates`, `added`/`updated` with `refused`, `changed`, `violation`, `state`); 2 with the typed error envelope when the tool could not do its job; 130 on interrupt; never 1. A Jev call that got no answer (any `judge` or `check-fixtures` cell, `dedupe --jev` pair, `rubric` or `add --rubric` candidate) shall be exit 2, never a negative result; the partial run is still written and named in `data`. Refusals (`data.refused`, `recoverable` included) and no-ops (`data.changed: false`) exit 0. The repository CI scripts' drift and staleness checks, and their failures, also exit 2.
Source: OPERATOR (0.7.2; 0.8.3: "jev API failure (or similar) should return an error"); ADR-007. Status: shipped (Jev failures were exit 0 with `verdict: error` until 0.8.3).

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

**REQ-066** The installer shall take `--allow-remote-judge` / `--no-remote-judge` and record the answer in the settings file; a rerun without either shall keep the recorded value.
Source: OPERATOR (2026-10-17); ADR-016. Status: shipped (0.7.1).

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

**REQ-080** `install.py --status` shall be read-only and take only `--dest` (else `VALIDATION.INPUT`); it reports `state` (`not_installed`, `older`, `current`, `newer`; an unparseable version counts as `older`) and, when the folder has no lock, `covering_install {root, version, valid}` from the nearest lock above. An install shall report `previous_version`, `tracker_origin`, `switched`, `migration` (no lock before), the `plan`, `warnings`, `notes` and `commit_paths` (empty on a dry run), and a rerun shall keep every locked target and add any newly requested one (default `claude`).
Source: OPERATOR; ADR-015. Status: shipped.
