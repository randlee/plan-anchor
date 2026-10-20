---
name: plan-anchor-installer
description: Install or upgrade plan-anchor (the plan-anchoring skill and its anchor-plan-review, anchor-sprint-review and anchor-tuning agents) into a repository or a parent folder of repositories, rendered for one anchor tracker (br or bd). Use when the user asks to install, set up, upgrade, reinstall or switch the tracker of plan-anchor or plan anchoring, or when the session-start notice says a newer plan-anchor is available. Never installs globally.
metadata:
  version: "0.8.4"
---

# plan-anchor installer

This plugin ships only this skill. It installs plan-anchor into a folder the
user names by running `install.py`, which sits in this plugin's directory
(`${CLAUDE_PLUGIN_ROOT}`; in any harness, two levels above this file).

The installer reads its templates, harness frontmatter and verbatim assets from
the plugin directory. From the folder and the folders above it, it reads
`.sc/plan-anchor/settings.yaml` (the folder's own, else the nearest above), the
install lock `.sc/plan-anchor/install-lock.json`, `.beads/` (the tracker and
Dolt check), whether `.git` exists (to find the repository root; it never runs
git) and the files already at the install paths. It reads the home directory
only to refuse global folders and to stop its upward walks, and `PATH` to find
`br` or `bd`. It renders every Markdown file and script for the one tracker
you pass with `--tracker br|bd` (sc-compose runs in-process) and copies the verbatim assets.
It writes `.<target>/skills/plan-anchoring/` and `.<target>/agents/`, the lock,
the settings file and, with `--overwrite`, `.backup/<UTC>/` and
`.backup/.gitignore`. The only command it runs is `br init`, with `--init-br`.

## 1. Pick the folder and report versions

Ask which folder to install into when the user has not said: the current
repository, or a parent folder holding several repositories. Never the home
directory, `~/.claude`, `~/.codex`, `~/.cursor`, `~/.agents` or a plugin cache;
the installer refuses those with `INSTALL.DEST_GLOBAL`.

Before anything else, compare versions (read-only):

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/install.py" --dest <folder> --status
```

Report `data.message` to the user, for example "installed 0.7.3, installer
0.8.0" or "not installed in <folder>, installer 0.8.0". `data.state` is
`not_installed`, `older`, `current` or `newer` (exit 0 for each). When it is
`newer`, stop and tell the user this installer is older than what the folder
has; do not install.

## 2. Settings: ask once, only when missing

Read `<folder>/.sc/plan-anchor/settings.yaml` if it exists.

- `anchor_tracker`: when the file sets it, use it; when it does not, use the
  nearest settings file above the folder if that one sets it (the installer
  does the same). Otherwise ask the user once whether the folder's
  repositories use `br` or `bd`. Offer `bd` only when the
  repository already has a Dolt-backed `.beads/` (`.beads/metadata.json` with
  `"backend": "dolt"`). Never run or recommend `bd init`; provisioning Dolt is
  outside plan-anchor.
- `allow_remote_judge`: when the folder's own file sets it, keep it (pass
  neither flag); the installer never copies a parent folder's answer.
  Otherwise ask the user once whether plan text may be sent to TypeSafe (Jev)
  for judging, and pass `--allow-remote-judge` or `--no-remote-judge` with the
  answer. Never infer consent from earlier runs, run files, committed evidence
  or other folders.

## 3. Install, or upgrade by rerunning

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/install.py" --dest <folder> --tracker br|bd \
  --allow-remote-judge|--no-remote-judge [--target claude,codex,cursor] [--dry-run]
```

An upgrade is the same command rerun for that folder; each install folder is
upgraded on its own. Pass the targets the user works in (`claude` by default;
a rerun keeps the targets already installed). `--tracker` with the other value
switches the tracker: every installed copy is re-rendered and no issue data is
migrated. A repository with no `.beads/` needs `--init-br` (runs `br init`, the
only bootstrap the installer performs) or the user's own `br init`.

Output is the JSON envelope `{success, data, error}`: exit 0 when it ran
(negative results are in `data`), exit 2 with a typed `error.code` otherwise
(`INSTALL.DEST_GLOBAL` for a global folder), exit 130 when interrupted
(`CANCELED`). On `INSTALL.CONFLICT`, show
`data.problems` and ask before rerunning with `--overwrite` (it moves each
listed file to `<folder>/.backup/`). Relay `data.notes` and tell the user to
commit `data.commit_paths`.

For the full guide, the installed copy's
`.claude/skills/plan-anchoring/references/installation-and-troubleshooting.md`
(or `.codex/`, `.cursor/`) covers parent-folder installs, per-repository
overrides and troubleshooting.
