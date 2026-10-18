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

import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Optional, Tuple

PLUGIN_DIR = Path(__file__).resolve().parent.parent

VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def version_tuple(value: object) -> Optional[Tuple[int, int, int]]:
    match = VERSION_RE.fullmatch(value) if isinstance(value, str) else None
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def _json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def installer() -> ModuleType:
    """install.py, imported as a module: it loads plan_anchor_paths and result from their templates."""
    name = "sc_plan_anchor_install"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / "install.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    return sys.modules[name]


def start_dir(raw: str) -> Path:
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    return Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()


def message(start: Path) -> Optional[str]:
    find_lock = installer().find_lock

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
        installer().utf8_stdio()
    except Exception:  # never break the session over output encoding
        pass
    sys.exit(main())
