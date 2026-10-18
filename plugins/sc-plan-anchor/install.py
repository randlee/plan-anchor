#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#   "pyyaml>=5.1",
#   "sc-compose>=1.7.0,<2",
# ]
# ///
"""Install plan-anchor (the plan-anchoring skill and its agents) into a folder, rendered for one tracker.

    uv run install.py --dest <folder> [--tracker br|bd]
        [--target claude,codex,cursor] [--init-br] [--overwrite] [--dry-run]
        [--allow-remote-judge | --no-remote-judge]
    uv run install.py --dest <folder> --status     # read-only: installed vs installer version

The marketplace plugin ships only the ``plan-anchor-installer`` skill; it runs
this script. Everything the script reads is inside this plugin directory.

The inline script metadata above lets ``uv run`` supply PyYAML and the
sc-compose wheel. sc-compose 1.7.0 publishes CPython 3.11 wheels only, so the
header pins 3.11 (uv downloads it when needed); the code itself runs on
Python 3.9+, so ``python3 install.py`` works wherever both packages import.

Destination. Any folder: a repository, or a parent folder holding many
repositories (they inherit it: the gates walk up from the working directory to
the nearest install, and the nearest settings file wins). Global harness
locations are refused with ``INSTALL.DEST_GLOBAL``: the home directory itself,
anything inside ``~/.claude``, ``~/.codex``, ``~/.cursor``, ``~/.agents``,
``/etc/codex`` or Claude Code's managed-settings directory
(which covers every plugin cache), and this plugin's own directory.

What it writes, per target (default ``claude``):
  <dest>/.<target>/skills/plan-anchoring/...   the skill (and registry.yaml for the agents)
  <dest>/.<target>/agents/anchor-*.md          the agents
  <dest>/.sc/plan-anchor/settings.yaml         ``anchor_tracker`` set to the tracker, and
                                               ``allow_remote_judge`` when a flag gives it
  <dest>/.sc/plan-anchor/install-lock.json     version, tracker, targets, sha256 per file

Tracker text. Every prompt file (SKILL.md, every reference, the .md assets and
every agent body) is an sc-compose template under ``install/templates/`` that
renders strictly for ``br`` or ``bd``, so an installed copy names one tracker.
Scripts, schemas, JSON assets and the runtime ``templates/*.md.j2`` are code
and data and are copied verbatim. A ``.j2`` file is an install-time template
when its frontmatter ``name`` starts with ``sc-plan-anchor-``. Agent
frontmatter per harness lives in ``install/harness/<target>/agents/``, the
agent registry in ``install/harness/<target>/registry.yaml``.

Tracker choice reuses ``anchor_tracker.py``'s rules: ``--tracker``, else the
destination's settings file, else detection (a Dolt-backed ``.beads/`` is bd,
anything else br). bd needs a Dolt-backed ``.beads/``; br needs one that is not.
A repository with no ``.beads/`` fails unless ``--init-br`` runs ``br init``;
it never runs bd's init. A folder that is not a repository and has no
``.beads/`` (a parent folder) needs ``--tracker`` (or its settings file); each
child repository's ``.beads/`` is checked against it when the gates resolve the
tracker there. Rerunning with another ``--tracker`` re-renders every installed
target and updates the setting; it never migrates issue data.

Remote judging. ``--allow-remote-judge`` / ``--no-remote-judge`` record the
user's answer to whether plan text may be sent to TypeSafe (Jev) as
``allow_remote_judge: true|false``; live Jev calls are refused until it is
``true``. Without either flag the existing value (or its absence) is kept.

Ownership. A rerun (the upgrade path) replaces a file only when its bytes are
what the lock says this installer wrote; it removes files this version no
longer ships when they are unchanged; it fails naming a modified or foreign
file unless ``--overwrite`` moves it to ``<dest>/.backup/<UTC>/<path>``. A
repository vendored before the lock existed is migrated once: a file is owned
when its bytes match something an earlier version shipped
(``install/legacy-owned.json``). Every check runs before anything is written;
``--dry-run`` stops there.

Output: the JSON envelope ``{success, data, error}``; exit 0 when the command
ran (``--status`` included, whatever it found), 2 on any error (an unexpected
exception is ``SCRIPT.INTERNAL``).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

PLUGIN_DIR = Path(__file__).resolve().parent
SKILL_NAME = "plan-anchoring"
INSTALL_DIR = PLUGIN_DIR / "install"
TEMPLATES_DIR = INSTALL_DIR / "templates"
SKILL_SRC = TEMPLATES_DIR / "skills" / SKILL_NAME
HARNESS_DIR = INSTALL_DIR / "harness"
SCRIPTS_DIR = SKILL_SRC / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import anchor_tracker as rules  # noqa: E402
from plan_anchor_paths import find_lock, global_location  # noqa: E402
from plan_anchor_settings import (  # noqa: E402
    SCHEMA_VERSION,
    SETTINGS_RELPATH,
    Settings,
    read_settings,
    write_settings,
)
from result import Err, Ok, Result, ToolError, err  # noqa: E402

PACKAGE = "sc-plan-anchor"
LEGACY_PATH = INSTALL_DIR / "legacy-owned.json"
LOCK_RELPATH = ".sc/plan-anchor/install-lock.json"
BACKUP_DIR = ".backup"
TARGETS = ("claude", "codex", "cursor")
TRACKERS = ("br", "bd")
RENDERINGS = TRACKERS
REGISTRY = "registry.yaml"   # per-target file installed in the skill directory
TEMPLATE_NAME_PREFIX = "name: sc-plan-anchor-"
SC_COMPOSE_FLOOR = (1, 7, 0)
SC_COMPOSE_CEILING_MAJOR = 2
SC_COMPOSE_SPEC = "sc-compose>=1.7.0,<2"
IGNORED = frozenset({"__pycache__", ".DS_Store"})
ERROR_EXIT = 2
NO_DATA_MIGRATION = (
    "Switching trackers does not migrate issue data: anchors, question beads and reports in the "
    "previous tracker stay there. Recreate the anchor tree in the new tracker "
    "(references/bead-layout.md) and update the bead IDs in anchors.json with set-beads."
)

Which = Callable[[str], Optional[str]]
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def version_tuple(version: Optional[str]) -> Optional[Tuple[int, int, int]]:
    m = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", version or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


# ---------------------------------------------------------------- package data


@dataclass(frozen=True)
class Package:
    version: str
    skill: Tuple[str, ...]                    # paths under .<target>/skills/plan-anchoring/
    rendered: frozenset                       # skill paths rendered from <rel>.j2
    agents: Tuple[str, ...]                   # agent file names, the same for every target
    legacy_skill: Dict[str, Set[str]]
    legacy_agents: Dict[str, Dict[str, Set[str]]]


def _read_json(path: Path, code: str) -> Result[Any, ToolError]:
    try:
        return Ok(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError) as exc:
        return err(code, f"{path} could not be read: {type(exc).__name__}: {exc}",
                   "Reinstall the plugin (or restore plugins/sc-plan-anchor in a source checkout).")
    except json.JSONDecodeError as exc:
        return err(code, f"{path} is not valid JSON: {exc.msg}",
                   "Reinstall the plugin, or regenerate it with scripts/gen_install_data.py in a source checkout.")


def is_install_template(path: Path) -> bool:
    """A ``.j2`` whose sc-compose frontmatter names it ``sc-plan-anchor-*`` (runtime templates are copied)."""
    if path.suffix != ".j2":
        return False
    try:
        with path.open(encoding="utf-8") as handle:
            first, second = handle.readline(), handle.readline()
    except (OSError, UnicodeError):
        return False
    return first == "---\n" and second.startswith(TEMPLATE_NAME_PREFIX)


def _tree(base: Path) -> List[Path]:
    return sorted(p for p in base.rglob("*") if p.is_file() and not IGNORED & set(p.relative_to(base).parts))


def load_package(plugin_dir: Path = PLUGIN_DIR) -> Result[Package, ToolError]:
    bad = "INSTALL.PACKAGE_INVALID"
    plugin = _read_json(plugin_dir / "plugin.json", bad)
    if isinstance(plugin, Err):
        return plugin
    version = plugin.value.get("version") if isinstance(plugin.value, dict) else None
    if not isinstance(version, str) or version_tuple(version) is None:
        return err(bad, f"{plugin_dir / 'plugin.json'} declares no X.Y.Z version")
    skill_src = plugin_dir / "install" / "templates" / "skills" / SKILL_NAME
    agents_src = plugin_dir / "install" / "templates" / "agents"
    harness = plugin_dir / "install" / "harness"
    if not skill_src.is_dir() or not agents_src.is_dir():
        return err(bad, f"{plugin_dir} has no install/templates/ tree", "Reinstall the plugin.")
    skill: List[str] = []
    rendered: Set[str] = set()
    for path in _tree(skill_src):
        rel = path.relative_to(skill_src).as_posix()
        if is_install_template(path):
            rel = rel[: -len(".j2")]
            rendered.add(rel)
        skill.append(rel)
    if "SKILL.md" not in rendered:
        return err(bad, "install/templates/skills/plan-anchoring/SKILL.md.j2 is missing")
    if REGISTRY in skill:
        return err(bad, f"install/templates/skills/plan-anchoring/{REGISTRY} would shadow the per-target registry")
    skill.append(REGISTRY)
    agents = []
    for path in _tree(agents_src):
        if not is_install_template(path) or path.parent != agents_src:
            return err(bad, f"{path.relative_to(plugin_dir).as_posix()} is not an agent template")
        agents.append(path.name[: -len(".j2")])
    for target in TARGETS:
        for name in [*(f"agents/{a}" for a in agents), REGISTRY]:
            if not (harness / target / name).is_file():
                return err(bad, f"install/harness/{target}/{name} is missing")
    legacy = _read_json(plugin_dir / "install" / "legacy-owned.json", bad)
    if isinstance(legacy, Err):
        return legacy
    lg = legacy.value
    try:
        legacy_skill = {rel: set(shas) for rel, shas in lg["skill"].items()}
        legacy_agents = {t: {n: set(s) for n, s in lg["agents"].get(t, {}).items()} for t in TARGETS}
    except (KeyError, TypeError, AttributeError) as exc:
        return err(bad, f"install/legacy-owned.json is malformed ({exc})", "Regenerate it with scripts/gen_install_data.py.")
    return Ok(Package(version, tuple(sorted(skill)), frozenset(rendered), tuple(agents), legacy_skill, legacy_agents))


# ---------------------------------------------------------------- dependencies


def check_sc_compose() -> Result[Any, ToolError]:
    action = (f"Run with `uv run {Path(__file__).name}` (it installs {SC_COMPOSE_SPEC} itself), or "
              f"python3 -m pip install '{SC_COMPOSE_SPEC}' (CPython 3.11 wheels).")
    try:
        module = importlib.import_module("sc_compose")
    except ImportError as exc:
        return err("DEPENDENCY.SC_COMPOSE", f"the sc-compose wheel is not importable: {exc}", action)
    try:
        from importlib import metadata
        version = metadata.version("sc-compose")
    except Exception as exc:  # metadata lookups raise several types; any means "unknown"
        return err("DEPENDENCY.SC_COMPOSE", f"the sc-compose wheel version is unknown: {type(exc).__name__}", action)
    parts = re.match(r"([0-9]+)\.([0-9]+)\.([0-9]+)", version)
    triple = tuple(int(p) for p in parts.groups()) if parts else None
    if triple is None or triple < SC_COMPOSE_FLOOR or triple[0] >= SC_COMPOSE_CEILING_MAJOR:
        return err("DEPENDENCY.SC_COMPOSE", f"the sc-compose wheel is {version}; this installer needs {SC_COMPOSE_SPEC}",
                   action, data={"version": version})
    return Ok(module)


# ---------------------------------------------------------------- rendering


def render_template(sc_compose: Any, template: Path, tracker: str, version: str) -> Result[str, ToolError]:
    """Strict sc-compose render of one install-time template for ``tracker`` (br or bd)."""
    if tracker not in TRACKERS:
        raise ValueError(f"render_template got tracker {tracker!r}")  # caller bug: there is no neutral render
    template = template.resolve()
    request = sc_compose.ComposeRequest(
        str(template.parent), sc_compose.ComposeMode.file(str(template)),
        vars_input={"tracker": tracker, "version": version},
        policy=sc_compose.ComposePolicy(strict_undeclared_variables=True))
    try:
        text = sc_compose.compose_file(request).rendered_text
    except sc_compose.ScComposeError as exc:
        detail = str(exc.args[0]) if exc.args else str(exc)
        return err("RENDER.FAILED", f"sc-compose could not render {template.name} for {tracker}: {detail}",
                   "Fix the template; tests/sc-plan-anchor/test_install.py renders every template.")
    if not text.endswith("\n"):
        text += "\n"
    return Ok(text)


class Renderer:
    """Renders and caches the installed bytes of one package and version."""

    def __init__(self, sc_compose: Any, package: Package, plugin_dir: Path = PLUGIN_DIR) -> None:
        self.sc_compose = sc_compose
        self.package = package
        self.plugin_dir = plugin_dir
        self.skill_src = plugin_dir / "install" / "templates" / "skills" / SKILL_NAME
        self.agents_src = plugin_dir / "install" / "templates" / "agents"
        self.harness = plugin_dir / "install" / "harness"
        self._cache: Dict[Tuple[str, str], str] = {}

    def _render(self, template: Path, tracker: str) -> Result[str, ToolError]:
        key = (str(template), tracker)
        if key not in self._cache:
            out = render_template(self.sc_compose, template, tracker, self.package.version)
            if isinstance(out, Err):
                return out
            self._cache[key] = out.value
        return Ok(self._cache[key])

    def skill_source(self, rel: str, target: str) -> Path:
        if rel == REGISTRY:
            return self.harness / target / REGISTRY
        return self.skill_src / (f"{rel}.j2" if rel in self.package.rendered else rel)

    def skill_file(self, rel: str, tracker: str, target: str) -> Result[bytes, ToolError]:
        src = self.skill_source(rel, target)
        if rel not in self.package.rendered:
            return Ok(src.read_bytes())
        out = self._render(src, tracker)
        return out if isinstance(out, Err) else Ok(out.value.encode("utf-8"))

    def agent_file(self, target: str, name: str, tracker: str) -> Result[bytes, ToolError]:
        front = (self.harness / target / "agents" / name).read_text(encoding="utf-8")
        out = self._render(self.agents_src / f"{name}.j2", tracker)
        return out if isinstance(out, Err) else Ok((front + out.value).encode("utf-8"))


# ---------------------------------------------------------------- lock file


@dataclass(frozen=True)
class Lock:
    version: str
    tracker: str
    targets: Tuple[str, ...]
    files: Dict[str, str]


def read_lock(root: Path) -> Result[Optional[Lock], ToolError]:
    path = root.joinpath(*LOCK_RELPATH.split("/"))
    if not path.exists():
        return Ok(None)
    fix = f"Restore {LOCK_RELPATH} from git; if it is lost, delete it and rerun (files are then recognized by their bytes)."
    loaded = _read_json(path, "INSTALL.LOCK_INVALID")
    if isinstance(loaded, Err):
        return err("INSTALL.LOCK_INVALID", loaded.error.message, fix)
    d = loaded.value
    if (not isinstance(d, dict) or d.get("package") != PACKAGE or not isinstance(d.get("files"), dict)
            or d.get("tracker") not in TRACKERS or not isinstance(d.get("targets"), list)
            or any(t not in TARGETS for t in d["targets"])
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in d["files"].items())):
        return err("INSTALL.LOCK_INVALID", f"{LOCK_RELPATH} is not an {PACKAGE} install record", fix)
    return Ok(Lock(str(d.get("version")), d["tracker"], tuple(d["targets"]), dict(d["files"])))


def lock_text(version: str, tracker: str, targets: List[str], files: Dict[str, str]) -> str:
    body = {"package": PACKAGE, "version": version, "tracker": tracker, "targets": targets,
            "files": dict(sorted(files.items()))}
    return json.dumps(body, indent=2) + "\n"


# ---------------------------------------------------------------- tracker choice


@dataclass(frozen=True)
class TrackerChoice:
    tracker: str
    origin: str               # "--tracker" | "settings" | "detected"
    settings: Optional[Settings]
    beads: Any                # anchor_tracker.BeadsState
    init_br: bool             # br init will run
    cli_path: str
    folder: bool = False      # not a repository and no .beads/: child repositories are checked at gate time


def is_repository(root: Path) -> bool:
    return (root / ".git").exists()


def choose_tracker(root: Path, requested: Optional[str], init_br: bool, which: Which) -> Result[TrackerChoice, ToolError]:
    settings = read_settings(root)  # the destination's own file: the one this install writes
    if isinstance(settings, Err):
        return settings
    beads = rules.inspect_beads(root)
    if isinstance(beads, Err):
        return beads
    configured = settings.value.anchor_tracker if settings.value is not None else None
    folder = not beads.value.exists and not is_repository(root)
    if requested:
        tracker, origin, label = requested, "--tracker", "--tracker"
    elif configured:
        tracker, origin, label = configured, "settings", f"{SETTINGS_RELPATH} anchor_tracker"
    elif folder:
        return err("TRACKER.REQUIRED",
                   f"{root} is not a repository and has no .beads/, so the anchor tracker cannot be detected",
                   "Ask the user which tracker the repositories under this folder use, then rerun with "
                   "--tracker br or --tracker bd.", data={"evidence": beads.value.to_json()})
    else:
        tracker, origin, label = rules.detect(beads.value), "detected", "detection"
    runs_init = False
    if not folder:
        checked = rules.check_against_disk(tracker, beads.value, label)
        if isinstance(checked, Err):
            error = checked.error
            if error.code == "TRACKER.DOLT_REQUIRED":
                error = ToolError(error.code, error.message,
                                  "Rerun with --tracker br. bd needs a Dolt-backed .beads/ that already exists; "
                                  "provisioning Dolt is outside this installer.", error.data)
            elif origin == "settings":
                error = ToolError(error.code, error.message,
                                  f"Rerun with --tracker {'bd' if tracker == 'br' else 'br'} to switch, or fix {SETTINGS_RELPATH}.",
                                  error.data)
            return Err(error)
        if not beads.value.exists:
            if not init_br:
                return err("TRACKER.NOT_INITIALIZED",
                           "the repository has no .beads/ workspace; br would be selected but is not initialized",
                           "Rerun with --init-br to run 'br init' (the only bootstrap this installer performs), "
                           "or run 'br init' in the repository root yourself.",
                           data={"tracker": tracker, "evidence": beads.value.to_json()})
            runs_init = True
    cli = rules.locate_cli(tracker, which)
    if isinstance(cli, Err):
        return cli
    return Ok(TrackerChoice(tracker, origin, settings.value, beads.value, runs_init, cli.value, folder))


# ---------------------------------------------------------------- plan


@dataclass
class Plan:
    root: Path
    version: str
    tracker: str
    targets: List[str]
    writes: Dict[str, Tuple[bytes, bool]] = field(default_factory=dict)  # key -> (bytes, executable)
    create: List[str] = field(default_factory=list)
    replace: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)
    remove: List[str] = field(default_factory=list)
    backup: List[str] = field(default_factory=list)
    problems: List[dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    lock_files: Dict[str, str] = field(default_factory=dict)
    settings_change: Optional[dict] = None
    remote_judge_change: Optional[dict] = None
    allow_remote_judge: Optional[bool] = None  # the value the settings file holds after the install
    br_init: bool = False


def _skill_prefix(target: str) -> str:
    return f".{target}/skills/{SKILL_NAME}/"


def _agents_prefix(target: str) -> str:
    return f".{target}/agents/"


def wanted_files(package: Package, renderer: Renderer, targets: List[str],
                 tracker: str) -> Result[Dict[str, Tuple[bytes, bool]], ToolError]:
    out: Dict[str, Tuple[bytes, bool]] = {}
    for target in targets:
        for rel in package.skill:
            data = renderer.skill_file(rel, tracker, target)
            if isinstance(data, Err):
                return data
            src = renderer.skill_source(rel, target)
            executable = rel not in package.rendered and bool(src.stat().st_mode & stat.S_IXUSR)
            out[_skill_prefix(target) + rel] = (data.value, executable)
        for name in package.agents:
            data = renderer.agent_file(target, name, tracker)
            if isinstance(data, Err):
                return data
            out[_agents_prefix(target) + name] = (data.value, False)
    return Ok(out)


def known_bytes(key: str, package: Package, renderer: Renderer) -> Result[Set[str], ToolError]:
    """sha256 of every byte string this package (any version, either tracker) shipped at ``key``."""
    shas: Set[str] = set()
    for target in TARGETS:
        if key.startswith(_skill_prefix(target)):
            rel = key[len(_skill_prefix(target)):]
            shas |= package.legacy_skill.get(rel, set())
            if rel in package.skill:
                for rendering in RENDERINGS:
                    data = renderer.skill_file(rel, rendering, target)
                    if isinstance(data, Err):
                        return data
                    shas.add(sha256(data.value))
        elif key.startswith(_agents_prefix(target)):
            name = key[len(_agents_prefix(target)):]
            shas |= package.legacy_agents[target].get(name, set())
            if name in package.agents:
                for rendering in RENDERINGS:
                    data = renderer.agent_file(target, name, rendering)
                    if isinstance(data, Err):
                        return data
                    shas.add(sha256(data.value))
    return Ok(shas)


def _legacy_keys(package: Package, target: str) -> List[str]:
    keys = [_skill_prefix(target) + rel for rel in package.legacy_skill]
    keys += [_agents_prefix(target) + name for name in package.legacy_agents[target]]
    return keys


def _problem(plan: Plan, code: str, key: str, message: str) -> None:
    plan.problems.append({"code": code, "path": key, "message": message})


def build_plan(root: Path, package: Package, renderer: Renderer, choice: TrackerChoice, lock: Optional[Lock],
               requested_targets: List[str], overwrite: bool) -> Result[Plan, ToolError]:
    """Everything the install would do. Reads the repository; writes nothing."""
    targets = [t for t in TARGETS if t in requested_targets or (lock is not None and t in lock.targets)]
    plan = Plan(root=root, version=package.version, tracker=choice.tracker, targets=targets, br_init=choice.init_br)
    wanted = wanted_files(package, renderer, targets, choice.tracker)
    if isinstance(wanted, Err):
        return wanted
    wanted_map = wanted.value
    locked = dict(lock.files) if lock is not None else {}
    hint = " (or rerun with --overwrite to move it to .backup/)"

    def owned(key: str, data: bytes) -> Result[Optional[bool], ToolError]:
        """True owned and unmodified; None recorded but modified; False not ours."""
        digest = sha256(data)
        if key in locked:
            return Ok(True if locked[key] == digest else None)
        shas = known_bytes(key, package, renderer)
        return shas if isinstance(shas, Err) else Ok(digest in shas.value)

    foreign: Set[str] = set()
    for target in targets:
        skill_dir = root / f".{target}" / "skills" / SKILL_NAME
        if skill_dir.is_symlink() or (skill_dir.exists() and not skill_dir.is_dir()):
            _problem(plan, "SKILL.NOT_A_DIRECTORY", _skill_prefix(target).rstrip("/"),
                     f"{_skill_prefix(target).rstrip('/')} exists and is not a directory; move it aside and rerun")
            foreign.add(target)
            continue
        if not skill_dir.is_dir() or any(k.startswith(_skill_prefix(target)) for k in locked):
            continue
        files = [p for p in skill_dir.rglob("*") if p.is_file() and not IGNORED & set(p.relative_to(skill_dir).parts)]
        if not files:
            continue
        mine = False
        for path in files:
            state = owned(path.relative_to(root).as_posix(), path.read_bytes())
            if isinstance(state, Err):
                return state
            if state.value is not False:
                mine = True
                break
        if not mine:
            foreign.add(target)
            _problem(plan, "SKILL.FOREIGN_DIR", _skill_prefix(target).rstrip("/"),
                     f"{_skill_prefix(target).rstrip('/')} exists and holds no file {PACKAGE} shipped; "
                     "move it aside and rerun")

    for key, (data, executable) in sorted(wanted_map.items()):
        if any(key.startswith(_skill_prefix(t)) for t in foreign):
            continue
        path = root / key
        if path.is_symlink() or (path.exists() and not path.is_file()):
            _problem(plan, "FILE.NOT_REGULAR", key, f"{key} exists and is not a regular file; move it aside and rerun")
            continue
        if path.is_file():
            current = path.read_bytes()
            state = owned(key, current)
            if isinstance(state, Err):
                return state
            if state.value is not True:
                if overwrite:
                    plan.backup.append(key)
                elif state.value is None:
                    _problem(plan, "FILE.MODIFIED", key, f"{key} was modified since {PACKAGE} installed it{hint}")
                    continue
                else:
                    _problem(plan, "FILE.UNOWNED", key, f"{key} exists and is not {PACKAGE}'s{hint}")
                    continue
            if current == data and key not in plan.backup:
                plan.unchanged.append(key)
            else:
                plan.replace.append(key)
        else:
            plan.create.append(key)
        plan.writes[key] = (data, executable)
        plan.lock_files[key] = sha256(data)

    # Files an earlier install placed that this version no longer ships.
    handled: Set[str] = set(wanted_map)
    for key, recorded in sorted(locked.items()):
        if key in wanted_map:
            continue
        handled.add(key)
        path = root / key
        if not path.is_file() or path.is_symlink():
            continue
        if sha256(path.read_bytes()) == recorded:
            plan.remove.append(key)
        elif overwrite:
            plan.backup.append(key)
            plan.remove.append(key)
        else:
            _problem(plan, "FILE.MODIFIED_RETIRED", key,
                     f"{key} was modified since {PACKAGE} installed it, and this version no longer ships it{hint}")
    if lock is None:
        for target in targets:
            if target in foreign:
                continue
            for key in sorted(_legacy_keys(package, target)):
                if key in handled:
                    continue
                handled.add(key)
                path = root / key
                if not path.is_file() or path.is_symlink():
                    continue
                state = owned(key, path.read_bytes())
                if isinstance(state, Err):
                    return state
                if state.value:
                    plan.remove.append(key)
                elif overwrite:
                    plan.backup.append(key)
                    plan.remove.append(key)
                else:
                    plan.warnings.append(f"{key}: an earlier {PACKAGE} version shipped this path, but these bytes are "
                                         "not one it shipped; left in place (move it aside, or rerun with --overwrite)")
    for target in targets:
        skill_dir = root / f".{target}" / "skills" / SKILL_NAME
        if target in foreign or not skill_dir.is_dir():
            continue
        for path in sorted(skill_dir.rglob("*")):
            key = path.relative_to(root).as_posix()
            if path.is_file() and key not in handled and not IGNORED & set(path.relative_to(skill_dir).parts):
                plan.warnings.append(f"{key}: not a {PACKAGE} file; left in place")

    # Records of other targets are rewritten above (targets include every locked one).
    configured = choice.settings.anchor_tracker if choice.settings is not None else None
    if configured != choice.tracker:
        plan.settings_change = {"path": SETTINGS_RELPATH, "from": configured, "to": choice.tracker}
    plan.allow_remote_judge = choice.settings.allow_remote_judge if choice.settings is not None else None
    plan.backup = sorted(set(plan.backup))
    plan.remove = sorted(set(plan.remove))
    return Ok(plan)


# ---------------------------------------------------------------- apply


def _prune(root: Path, start: Path, stop: Path) -> None:
    """Remove now-empty directories (ignoring __pycache__ residue) from ``start`` up to ``stop``."""
    current = start
    while current != stop and stop in current.parents and current.is_dir():
        entries = list(current.iterdir())
        if any(e.name not in IGNORED or (e.is_file() and e.name != ".DS_Store") for e in entries):
            if not all(e.is_dir() and e.name == "__pycache__" or e.name == ".DS_Store" for e in entries):
                return
        for e in entries:
            if e.is_dir():
                shutil.rmtree(e)
            else:
                e.unlink()
        current.rmdir()
        current = current.parent


def apply_plan(plan: Plan, choice: TrackerChoice, run: Runner) -> Result[List[str], ToolError]:
    """Write the plan. Returns the paths to commit."""
    root = plan.root
    if plan.br_init:
        initialized = rules.init_br("br", choice.cli_path, root, run)
        if isinstance(initialized, Err):
            return initialized
    try:
        if plan.backup:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            base = root / BACKUP_DIR / stamp
            for key in plan.backup:
                (base / key).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(root / key), str(base / key))
            ignore = root / BACKUP_DIR / ".gitignore"
            if not ignore.exists():
                ignore.write_text("*\n", encoding="utf-8")
        for key, (data, executable) in sorted(plan.writes.items()):
            path = root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.is_file() or path.read_bytes() != data:
                path.write_bytes(data)
            if executable and os.name != "nt":
                path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        for key in plan.remove:
            path = root / key
            if path.is_file():
                path.unlink()
            target_root = root / key.split("/", 1)[0]
            _prune(root, path.parent, target_root)
        lock_path = root.joinpath(*LOCK_RELPATH.split("/"))
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = lock_path.with_name(lock_path.name + ".tmp")
        tmp.write_text(lock_text(plan.version, plan.tracker, plan.targets, plan.lock_files), encoding="utf-8")
        os.replace(tmp, lock_path)
    except OSError as exc:
        return err("INSTALL.WRITE_FAILED", f"writing the install failed: {type(exc).__name__}: {exc}",
                   "Fix the reported path (permissions, disk space), then rerun; the lock file is written last.")
    if plan.settings_change is not None or plan.remote_judge_change is not None:
        saved = write_settings(root, Settings(schema_version=SCHEMA_VERSION, anchor_tracker=plan.tracker,
                                              allow_remote_judge=plan.allow_remote_judge))
        if isinstance(saved, Err):
            return saved
    changed = plan.create + plan.replace + plan.remove
    commit = sorted({k.split("/")[0] + "/" for k in changed})
    if changed or plan.backup:
        commit.append(LOCK_RELPATH)
    if plan.settings_change is not None or plan.remote_judge_change is not None:
        commit.append(SETTINGS_RELPATH)
    if plan.br_init:
        commit.append(".beads/")
    return Ok(commit)


# ---------------------------------------------------------------- orchestration


@dataclass(frozen=True)
class Options:
    dest: Path
    tracker: Optional[str]
    targets: List[str]
    init_br: bool = False
    overwrite: bool = False
    dry_run: bool = False
    allow_remote_judge: Optional[bool] = None  # None: keep what the settings file holds


def check_dest(dest: Path, plugin_dir: Path = PLUGIN_DIR) -> Result[Path, ToolError]:
    """The destination folder, resolved; a global harness location or the plugin itself is refused."""
    dest = dest.expanduser()
    if not dest.is_dir():
        return err("INSTALL.DEST", f"--dest {str(dest)!r} is not a directory",
                   "Pass an existing folder: a repository, or a parent folder holding repositories.")
    root = dest.resolve()
    why = global_location(root)
    plugin = plugin_dir.resolve()
    if why is None and (root == plugin or plugin in root.parents):
        why = f"{root} is inside the plugin directory {plugin}"
    if why is not None:
        return err("INSTALL.DEST_GLOBAL", f"--dest refused: {why}",
                   "plan-anchor installs per folder, never globally: pass a repository or a parent folder of "
                   "repositories (not the home directory, ~/.claude, ~/.codex, ~/.cursor, ~/.agents or a plugin cache).",
                   data={"dest": str(root)})
    return Ok(root)


def status(dest: Path, plugin_dir: Path = PLUGIN_DIR) -> Result[dict, ToolError]:
    """Read-only: the installer's version against the destination's lock (or the nearest lock above it)."""
    root = check_dest(dest, plugin_dir)
    if isinstance(root, Err):
        return root
    plugin = _read_json(plugin_dir / "plugin.json", "INSTALL.PACKAGE_INVALID")
    if isinstance(plugin, Err):
        return plugin
    mine = plugin.value.get("version") if isinstance(plugin.value, dict) else None
    lock = read_lock(root.value)
    if isinstance(lock, Err):
        return lock
    covering = None
    if lock.value is None:
        above = find_lock(root.value.parent) if root.value.parent != root.value else None
        if above is not None:
            parent_root = above.parent.parent.parent
            found = read_lock(parent_root)
            covering = {"root": str(parent_root), "version": found.value.version if isinstance(found, Ok) and found.value else None,
                        "valid": isinstance(found, Ok)}
    installed = lock.value.version if lock.value is not None else None
    have, want = version_tuple(installed), version_tuple(mine)
    if installed is None:
        state, message = "not_installed", f"not installed in {root.value}, installer {mine}"
        if covering is not None:
            message += f" (an install at {covering['root']} covers it: {covering['version']})"
    elif have is None or want is None or have < want:
        state, message = "older", f"installed {installed}, installer {mine}"
    elif have == want:
        state, message = "current", f"installed {installed}, installer {mine}"
    else:
        state, message = "newer", f"installed {installed} is newer than installer {mine}"
    return Ok({
        "package": PACKAGE,
        "dest": str(root.value),
        "installer_version": mine,
        "installed_version": installed,
        "installed_tracker": lock.value.tracker if lock.value is not None else None,
        "installed_targets": list(lock.value.targets) if lock.value is not None else [],
        "covering_install": covering,
        "state": state,
        "message": message,
    })


def install(opts: Options, *, which: Which = shutil.which, run: Runner = subprocess.run,
            plugin_dir: Path = PLUGIN_DIR) -> Result[dict, ToolError]:
    checked = check_dest(opts.dest, plugin_dir)
    if isinstance(checked, Err):
        return checked
    root = Ok(checked.value)
    package = load_package(plugin_dir)
    if isinstance(package, Err):
        return package
    choice = choose_tracker(root.value, opts.tracker, opts.init_br, which)
    if isinstance(choice, Err):
        return choice
    lock = read_lock(root.value)
    if isinstance(lock, Err):
        return lock
    sc_compose = check_sc_compose()
    if isinstance(sc_compose, Err):
        return sc_compose
    renderer = Renderer(sc_compose.value, package.value, plugin_dir)
    planned = build_plan(root.value, package.value, renderer, choice.value, lock.value, opts.targets, opts.overwrite)
    if isinstance(planned, Err):
        return planned
    plan = planned.value
    if opts.allow_remote_judge is not None and opts.allow_remote_judge != plan.allow_remote_judge:
        plan.remote_judge_change = {"path": SETTINGS_RELPATH, "from": plan.allow_remote_judge, "to": opts.allow_remote_judge}
        plan.allow_remote_judge = opts.allow_remote_judge
    if plan.problems:
        return err("INSTALL.CONFLICT",
                   f"{len(plan.problems)} file(s) are in the way; nothing was written: "
                   + "; ".join(p["message"] for p in plan.problems),
                   "Restore or move each listed file and rerun, or rerun with --overwrite to move them to .backup/.",
                   data={"problems": plan.problems})
    c = choice.value
    previous = lock.value.tracker if lock.value is not None else (c.settings.anchor_tracker if c.settings else None)
    switched = previous is not None and previous != c.tracker
    notes = []
    if switched:
        notes.append(f"Switching the anchor tracker from {previous} to {c.tracker}: every installed target is "
                     f"re-rendered and {SETTINGS_RELPATH} is updated. {NO_DATA_MIGRATION}")
    if plan.allow_remote_judge is None:
        notes.append(f"{SETTINGS_RELPATH} does not set allow_remote_judge, so live Jev calls are refused. Ask the user "
                     "once whether plan text may be sent to TypeSafe (Jev), then rerun with --allow-remote-judge or "
                     "--no-remote-judge (or run 'plan_anchor_settings.py set allow_remote_judge true|false') and commit it.")
    if c.folder:
        notes.append(f"{root.value} is not a repository: repositories below it inherit this install and its "
                     f"{SETTINGS_RELPATH} (the nearest settings file wins, so a repository can override it with its own). "
                     "Each repository keeps its own .beads/, anchors.json, plans and runs; its .beads/ is checked "
                     f"against anchor_tracker {c.tracker} when the gates resolve the tracker there.")
        if opts.init_br:
            notes.append("--init-br ignored: the destination is not a repository; run 'br init' in each repository.")
    elif opts.init_br and not c.init_br:
        notes.append("--init-br ignored: .beads/ already exists.")
    data: Dict[str, Any] = {
        "package": PACKAGE,
        "version": plan.version,
        "previous_version": lock.value.version if lock.value is not None else None,
        "install_root": str(root.value),
        "repository": is_repository(root.value),
        "tracker": c.tracker,
        "tracker_origin": c.origin,
        "previous_tracker": previous,
        "switched": switched,
        "allow_remote_judge": plan.allow_remote_judge,
        "targets": plan.targets,
        "dry_run": opts.dry_run,
        "migration": lock.value is None,
        "plan": {
            "create": plan.create,
            "replace": plan.replace,
            "unchanged": plan.unchanged,
            "remove": plan.remove,
            "backup": plan.backup,
            "settings": plan.settings_change,
            "allow_remote_judge": plan.remote_judge_change,
            "br_init": plan.br_init,
            "lock": LOCK_RELPATH,
        },
        "warnings": plan.warnings,
        "notes": notes,
    }
    if opts.dry_run:
        data["commit_paths"] = []
        return Ok(data)
    applied = apply_plan(plan, c, run)
    if isinstance(applied, Err):
        return applied
    data["commit_paths"] = applied.value
    return Ok(data)


# ---------------------------------------------------------------- CLI


class _UsageError(Exception):
    pass


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):  # argparse hook; never returns
        raise _UsageError(f"{self.prog}: {message}")


def _targets(value: str) -> List[str]:
    out = []
    for part in value.split(","):
        name = part.strip().lstrip(".")
        if name not in TARGETS:
            raise argparse.ArgumentTypeError(f"unknown target {part.strip()!r}; choose from {', '.join(TARGETS)}")
        out.append(name)
    return out


def _parser() -> argparse.ArgumentParser:
    p = _JsonArgumentParser(prog="install.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dest", required=True,
                   help="the folder to install into: a repository, or a parent folder holding repositories")
    p.add_argument("--status", action="store_true",
                   help="read-only: compare this installer's version with the destination's install lock")
    p.add_argument("--tracker", choices=TRACKERS,
                   help="render for this tracker and record it (default: the settings file, else detection)")
    p.add_argument("--target", type=_targets, action="append", default=None, metavar="claude,codex,cursor",
                   help="harness directories to install into (repeatable or comma-separated; default claude)")
    p.add_argument("--init-br", action="store_true", help="run 'br init' when the repository has no .beads/")
    p.add_argument("--overwrite", action="store_true",
                   help=f"move modified or foreign files in the way to {BACKUP_DIR}/<UTC>/ and install over them")
    p.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    remote = p.add_mutually_exclusive_group()
    remote.add_argument("--allow-remote-judge", dest="allow_remote_judge", action="store_const", const=True, default=None,
                        help="record allow_remote_judge: true (the user agreed plan text may be sent to TypeSafe)")
    remote.add_argument("--no-remote-judge", dest="allow_remote_judge", action="store_const", const=False,
                        help="record allow_remote_judge: false (live Jev calls stay refused)")
    return p


def _envelope(result: Result[Any, ToolError]) -> Tuple[dict, int]:
    if isinstance(result, Ok):
        return {"success": True, "data": result.value, "error": None}, 0
    e = result.error
    return {"success": False, "data": dict(e.data) if e.data is not None else None, "error": e.to_json()}, ERROR_EXIT


def main(argv: Optional[List[str]] = None, *, which: Which = shutil.which, run: Runner = subprocess.run,
         plugin_dir: Path = PLUGIN_DIR) -> int:
    try:
        args = _parser().parse_args(argv)
        targets = [t for group in (args.target or [["claude"]]) for t in group]
        opts = Options(dest=Path(args.dest), tracker=args.tracker, targets=list(dict.fromkeys(targets)),
                       init_br=args.init_br, overwrite=args.overwrite, dry_run=args.dry_run,
                       allow_remote_judge=args.allow_remote_judge)
        if args.status and (args.tracker or args.target or args.init_br or args.overwrite or args.dry_run
                            or args.allow_remote_judge is not None):
            raise _UsageError("install.py: --status takes only --dest")
    except _UsageError as exc:
        envelope = {"success": False, "data": None,
                    "error": ToolError("VALIDATION.INPUT", str(exc), "Run 'install.py --help'.").to_json()}
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return ERROR_EXIT
    try:
        if args.status:
            envelope, code = _envelope(status(opts.dest, plugin_dir))
        else:
            envelope, code = _envelope(install(opts, which=which, run=run, plugin_dir=plugin_dir))
    except Exception as exc:  # a bug, not an expected failure
        envelope = {"success": False, "data": None, "error": ToolError(
            "SCRIPT.INTERNAL", f"{type(exc).__name__}: {exc}", "Report this with the command line.").to_json()}
        code = ERROR_EXIT
    print(json.dumps(envelope, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
