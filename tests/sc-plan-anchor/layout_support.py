"""Where the plugin keeps its sources, and fresh per-tracker renders of what install.py installs.

The plugin ships only the plan-anchor-installer skill. The plan-anchoring skill,
its references and the agents exist only as sources under ``install/``:
``install/templates/`` (sc-compose templates plus the verbatim scripts, schemas
and data) and ``install/harness/<target>/`` (agent frontmatter and registry).
Prompt tests read a fresh render for ``br`` and for ``bd`` made by install.py's
own renderer; script tests import the scripts from their source directory.

``rendered(tracker)`` needs the sc-compose wheel (CPython 3.11). Without it the
test is skipped, unless ``PLAN_ANCHOR_REQUIRE_SC_COMPOSE=1`` (the CI installer
job), where a missing wheel is a failure.
"""
from __future__ import annotations

import atexit
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
INSTALL = PLUGIN / "install"
TEMPLATES = INSTALL / "templates"
HARNESS = INSTALL / "harness"
SKILL_SRC = TEMPLATES / "skills" / "plan-anchoring"
SCRIPTS = SKILL_SRC / "scripts"
AGENT_TEMPLATES = TEMPLATES / "agents"
TARGETS = ("claude", "codex", "cursor")
TRACKERS = ("br", "bd")
AGENTS = ("anchor-plan-review.md", "anchor-sprint-review.md", "anchor-tuning.md")
REQUIRE_SC_COMPOSE = os.environ.get("PLAN_ANCHOR_REQUIRE_SC_COMPOSE") == "1"

_installer = None
_renders = {}
_scratch = None


def installer():
    """install.py, imported once as a module."""
    global _installer
    if _installer is None:
        spec = importlib.util.spec_from_file_location("sc_plan_anchor_install", PLUGIN / "install.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _installer = module
    return _installer


def sc_compose():
    """The sc-compose module, or SkipTest (a failure under PLAN_ANCHOR_REQUIRE_SC_COMPOSE=1)."""
    inst = installer()
    found = inst.check_sc_compose()
    if isinstance(found, inst.Err):
        if REQUIRE_SC_COMPOSE:
            raise AssertionError(f"PLAN_ANCHOR_REQUIRE_SC_COMPOSE=1 but sc-compose is unavailable: {found.error.message}")
        raise unittest.SkipTest(f"sc-compose wheel not importable here ({found.error.message})")
    return found.value


def rendered(tracker: str) -> Path:
    """An install root holding every target rendered for ``tracker`` (made once per test process)."""
    global _scratch
    if tracker not in _renders:
        inst = installer()
        package = inst.load_package()
        if isinstance(package, inst.Err):
            raise AssertionError(package.error.message)
        renderer = inst.Renderer(sc_compose(), package.value)
        files = inst.wanted_files(package.value, renderer, list(TARGETS), tracker)
        if isinstance(files, inst.Err):
            raise AssertionError(files.error.message)
        if _scratch is None:
            _scratch = Path(tempfile.mkdtemp(prefix="plan-anchor-render-"))
            atexit.register(shutil.rmtree, _scratch, True)
        root = _scratch / tracker
        for key, (data, executable) in files.value.items():
            path = root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            if executable:
                path.chmod(0o755)
        _renders[tracker] = root
    return _renders[tracker]


def rendered_skill(tracker: str, target: str = "claude") -> Path:
    return rendered(tracker) / f".{target}" / "skills" / "plan-anchoring"


def rendered_agent(tracker: str, target: str, name: str) -> Path:
    return rendered(tracker) / f".{target}" / "agents" / name


def installed_scripts(root: Path, target: str = "claude") -> Path:
    """Copy the script sources into ``root`` in the installed layout; returns the scripts directory.

    jev_judge.py's agent-preflight trusts only a copy in the nearest per-folder install, so
    a test that runs preflight runs it from such a copy, as an installed agent does.
    """
    dest = root / f".{target}" / "skills" / "plan-anchoring" / "scripts"
    shutil.copytree(SCRIPTS, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return dest
