#!/usr/bin/env python3
"""SessionStart hook: one line when the nearest plan-anchor install is older than this plugin.

Reads the hook input (JSON on stdin; its ``cwd``, else the process working
directory), walks up to the nearest ``.sc/plan-anchor/install-lock.json``
(stopping before the home directory) and compares its ``version`` with this
plugin's. Prints nothing when there is no lock, when the lock is current or
newer, or when anything cannot be read; prints one line when it is older.
Never writes, never touches the network, always exits 0. Standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Optional, Tuple

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR / "install" / "templates" / "skills" / "plan-anchoring" / "scripts"))

VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def version_tuple(value: object) -> Optional[Tuple[int, int, int]]:
    match = VERSION_RE.fullmatch(value) if isinstance(value, str) else None
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def _json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def start_dir(raw: str) -> Path:
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    return Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()


def message(start: Path) -> Optional[str]:
    from plan_anchor_paths import find_lock

    plugin = _json(PLUGIN_DIR / "plugin.json")
    available = plugin.get("version") if isinstance(plugin, dict) else None
    lock_path = find_lock(start)
    if lock_path is None or version_tuple(available) is None:
        return None
    lock = _json(lock_path)
    installed = lock.get("version") if isinstance(lock, dict) else None
    have = version_tuple(installed)
    if have is None or have >= version_tuple(available):
        return None
    folder = lock_path.parent.parent.parent
    return f"plan-anchor {installed} installed, {available} available: run plan-anchor-installer ({folder})"


def main() -> int:
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        line = message(start_dir(raw))
    except Exception:  # a session-start notice must never break the session
        return 0
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    try:
        from result import utf8_stdio

        utf8_stdio()
    except Exception:  # never break the session over output encoding
        pass
    sys.exit(main())
