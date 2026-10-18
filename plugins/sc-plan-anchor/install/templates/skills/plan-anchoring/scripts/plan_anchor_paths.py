#!/usr/bin/env python3
"""Where a plan-anchor install lives, and which locations are global.

One rule, shared by the installer, the gates and the settings lookup: walk up
from the working directory, nearest first, and stop before the home directory.

  - ``ancestors(start)``: ``start`` and its parents, nearest first. When
    ``start`` is under the home directory the walk stops before it (the home
    directory itself is never visited); otherwise it ends at the filesystem
    root. ``start`` equal to the home directory visits nothing.
  - ``find_installs(start)``: the nearest directory holding
    ``<dir>/<harness dir>/skills/plan-anchoring/scripts/jev_judge.py`` and every
    copy in it (one per harness directory: .claude, .codex, .cursor, .agents).
  - ``find_settings(start)`` / ``find_lock(start)``: the nearest
    ``.sc/plan-anchor/settings.yaml`` / ``install-lock.json``.
  - ``global_location(path)``: why ``path`` is a global (user-wide or
    machine-wide) harness location, or None. The home directory itself, and
    anything inside ``~/.claude``, ``~/.codex``, ``~/.cursor``, ``~/.agents``,
    ``/etc/codex`` (Codex admin skills) and the Claude Code managed-settings
    directories, is global; that covers every plugin cache
    under them. A plan-anchor install is per folder, never global.

Standard library only; importing it has no side effects.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

SKILL_NAME = "plan-anchoring"
HARNESS_DIRS = (".claude", ".codex", ".cursor", ".agents")
SETTINGS_RELPATH = ".sc/plan-anchor/settings.yaml"
LOCK_RELPATH = ".sc/plan-anchor/install-lock.json"
SCRIPT_RELPATH = f"skills/{SKILL_NAME}/scripts/jev_judge.py"
# Machine-wide skill/config directories (Codex admin skills; Claude Code managed settings).
SYSTEM_GLOBALS = (
    "/etc/codex",
    "/etc/claude-code",
    "/Library/Application Support/ClaudeCode",
    "C:/ProgramData/ClaudeCode",
)


def _resolve(path: Path) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return Path(os.path.abspath(str(Path(path).expanduser())))


def home_dir() -> Path:
    """The user's home directory (``$HOME`` / ``%USERPROFILE%``), resolved."""
    return _resolve(Path(os.path.expanduser("~")))


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def global_roots(home: Optional[Path] = None) -> List[Path]:
    home = _resolve(home) if home is not None else home_dir()
    roots = [home / name for name in HARNESS_DIRS]
    roots += [_resolve(Path(p)) for p in SYSTEM_GLOBALS]
    return roots


def global_location(path: Path, home: Optional[Path] = None) -> Optional[str]:
    """Why ``path`` is a global location (a short reason), or None when it is a per-folder location."""
    home = _resolve(home) if home is not None else home_dir()
    target = _resolve(path)
    if target == home:
        return f"{home} is the home directory"
    for root in global_roots(home):
        if _within(target, root):
            return f"{target} is inside the global location {root}"
    return None


def ancestors(start: Path, home: Optional[Path] = None) -> Iterator[Path]:
    """``start`` and its parents, nearest first, stopping before the home directory."""
    home = _resolve(home) if home is not None else home_dir()
    current = _resolve(start)
    if current.is_file():
        current = current.parent
    under_home = home in current.parents
    if current == home:
        return
    while True:
        yield current
        parent = current.parent
        if parent == current or (under_home and parent == home):
            return
        current = parent


def find_installs(start: Path, home: Optional[Path] = None) -> Optional[Tuple[Path, List[Path]]]:
    """(install root, [jev_judge.py per harness dir]) for the nearest install above ``start``, or None."""
    for directory in ancestors(start, home):
        found = [directory / harness / SCRIPT_RELPATH for harness in HARNESS_DIRS]
        found = [p for p in found if p.is_file()]
        if found:
            return directory, found
    return None


def _nearest(start: Path, rel: str, home: Optional[Path]) -> Optional[Path]:
    for directory in ancestors(start, home):
        candidate = directory.joinpath(*rel.split("/"))
        if candidate.exists() or candidate.is_symlink():
            return candidate
    return None


def find_settings(start: Path, home: Optional[Path] = None) -> Optional[Path]:
    """The nearest ``.sc/plan-anchor/settings.yaml`` at or above ``start`` (stopping before home)."""
    return _nearest(start, SETTINGS_RELPATH, home)


def find_lock(start: Path, home: Optional[Path] = None) -> Optional[Path]:
    """The nearest ``.sc/plan-anchor/install-lock.json`` at or above ``start`` (stopping before home)."""
    return _nearest(start, LOCK_RELPATH, home)


def trusted_script(script: Path, start: Path, home: Optional[Path] = None) -> Tuple[bool, str]:
    """Whether ``script`` is the jev_judge.py the trust rule selects from ``start``; (ok, reason)."""
    resolved = _resolve(script)
    why = global_location(resolved, home)
    if why is not None:
        return False, f"the script is in a global location ({why}); plan-anchor is installed per folder"
    nearest = find_installs(start, home)
    if nearest is None:
        return False, (f"no {', '.join(HARNESS_DIRS)} install of {SKILL_NAME} at or above {_resolve(start)} "
                       "(the walk stops before the home directory)")
    root, copies = nearest
    if resolved not in {_resolve(p) for p in copies}:
        return False, f"the nearest install is {root}; {resolved} is not one of its copies"
    return True, f"nearest install {root}"
