"""Where the plugin keeps its sources, and fresh per-tracker renders of what install.py installs.

The plugin ships only the plan-anchor-installer skill. The plan-anchoring skill,
its references, its scripts and the agents exist only as sources under
``install/``: ``install/templates/`` (sc-compose templates, ``<file>.md.j2`` and
``<script>.py.j2``, plus the verbatim schemas and data) and
``install/harness/<target>/`` (agent frontmatter and registry). Prompt tests
read a fresh render for ``br`` and for ``bd`` made by install.py's own renderer.

Script tests run the scripts as installed for one tracker: ``SCRIPTS`` is a
fresh strict render of every ``scripts/*.py.j2`` for ``TEST_TRACKER``
(``PLAN_ANCHOR_TEST_TRACKER``, default ``br``; CI runs the suite once per
tracker). It is made by install.py's renderer when the sc-compose wheel imports,
else by the sc-compose CLI (the same engine, which CI installs on every job;
test_install.py checks the two agree byte for byte). With neither, importing
this module fails: a script test never runs against unrendered sources.

``rendered(tracker)`` needs the sc-compose wheel. Without it the test is
skipped, unless ``PLAN_ANCHOR_REQUIRE_SC_COMPOSE=1`` (the CI installer job),
where a missing wheel is a failure.
"""
from __future__ import annotations

import atexit
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
INSTALL = PLUGIN / "install"
TEMPLATES = INSTALL / "templates"
HARNESS = INSTALL / "harness"
SKILL_SRC = TEMPLATES / "skills" / "plan-anchoring"
SCRIPT_TEMPLATES = SKILL_SRC / "scripts"   # the *.py.j2 sources; SCRIPTS (below) is their render
AGENT_TEMPLATES = TEMPLATES / "agents"
TARGETS = ("claude", "codex", "cursor")
TRACKERS = ("br", "bd")
AGENTS = ("anchor-plan-review.md", "anchor-sprint-review.md", "anchor-tuning.md")
REQUIRE_SC_COMPOSE = os.environ.get("PLAN_ANCHOR_REQUIRE_SC_COMPOSE") == "1"
TEST_TRACKER = os.environ.get("PLAN_ANCHOR_TEST_TRACKER", "br")
if TEST_TRACKER not in TRACKERS:
    raise RuntimeError(f"PLAN_ANCHOR_TEST_TRACKER must be br or bd, not {TEST_TRACKER!r}")

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
    if tracker not in _renders:
        inst = installer()
        package = inst.load_package()
        if isinstance(package, inst.Err):
            raise AssertionError(package.error.message)
        renderer = inst.Renderer(sc_compose(), package.value)
        files = inst.wanted_files(package.value, renderer, list(TARGETS), tracker)
        if isinstance(files, inst.Err):
            raise AssertionError(files.error.message)
        root = _scratch_dir() / tracker
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


def _scratch_dir() -> Path:
    global _scratch
    if _scratch is None:
        _scratch = Path(tempfile.mkdtemp(prefix="plan-anchor-render-"))
        atexit.register(shutil.rmtree, _scratch, True)
    return _scratch


def render_cli(template: Path, tracker: str, out: Path) -> None:
    """Render one install template for ``tracker`` into ``out`` with the sc-compose CLI.

    The same strict render and final-newline rule as install.py's render_template.
    """
    binary = shutil.which("sc-compose")
    if binary is None:
        raise RuntimeError("the script tests need a rendered install: the sc-compose wheel or the sc-compose CLI "
                           "(scripts/install_sc_compose_ci.py) must be available")
    version = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))["version"]
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([binary, "render", "--root", str(template.parent), "--strict", "--var", f"tracker={tracker}",
                           "--var", f"version={version}", "--file", str(template), "--output", str(out)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"sc-compose render {template.name} for {tracker} failed: {proc.stderr[-2000:]}")
    data = out.read_bytes()
    if not data.endswith(b"\n"):
        out.write_bytes(data + b"\n")


def render_skill_cli(tracker: str, dest: Path) -> None:
    """The plan-anchoring skill as install.py lays it out for ``tracker``, rendered with the sc-compose CLI."""
    inst = installer()
    package = inst.load_package()
    if isinstance(package, inst.Err):
        raise AssertionError(package.error.message)
    for rel in package.value.skill:
        src = HARNESS / "claude" / rel if rel == "registry.yaml" else SKILL_SRC / rel
        out = dest / rel
        if rel in package.value.rendered:
            src = SKILL_SRC / f"{rel}.j2"
            render_cli(src, tracker, out)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, out)
        if src.stat().st_mode & 0o100:
            out.chmod(0o755)


def render_scripts(tracker: str) -> Path:
    """The scripts directory of a plan-anchoring skill rendered for ``tracker`` (made once per test process)."""
    key = ("scripts", tracker)
    if key not in _renders:
        inst = installer()
        if isinstance(inst.check_sc_compose(), inst.Ok):
            skill = rendered_skill(tracker)
        else:
            skill = _scratch_dir() / f"cli-{tracker}" / ".claude" / "skills" / "plan-anchoring"
            render_skill_cli(tracker, skill)
        _renders[key] = skill / "scripts"
    return _renders[key]


SCRIPTS = render_scripts(TEST_TRACKER)


def installed_scripts(root: Path, target: str = "claude") -> Path:
    """Copy the rendered scripts into ``root`` in the installed layout; returns the scripts directory.

    jev_judge.py's agent-preflight trusts only a copy in the nearest per-folder install, so
    a test that runs preflight runs it from such a copy, as an installed agent does.
    """
    dest = root / f".{target}" / "skills" / "plan-anchoring" / "scripts"
    shutil.copytree(SCRIPTS, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return dest
