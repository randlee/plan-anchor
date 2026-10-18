"""Settings for sc-plan-anchor: ``.sc/plan-anchor/settings.yaml``.

The file follows the Synaptic Canvas convention: one subfolder per package
under ``.sc/``, YAML with snake_case keys, committed to git, never secrets.

Lookup: the nearest settings file at or above the working directory wins
(``plan_anchor_paths.find_settings``: walk up, stop before the home directory).
A parent folder that holds many repositories can carry one file for all of
them, and a repository overrides it with its own. The nearest file wins as a
whole: keys are never merged across files, so an override that omits
``allow_remote_judge`` means nobody has answered for that repository. Validation is strict: ``schema_version`` must be 1 and
unknown or duplicate keys are rejected, so a typo never silently falls back to
a default.

This is the only plan-anchoring module that needs PyYAML
(``python3 -m pip install pyyaml``). PyYAML is imported lazily, so importing
this module never fails; a missing PyYAML is returned as
``DEPENDENCY.PYYAML``. Every expected failure is returned as
``Err(ToolError)`` (see ``result.py``), never raised.

Keys (all optional except ``schema_version``)
  anchor_tracker      ``br`` or ``bd``; written by ``anchor_tracker.py write``
  allow_remote_judge  ``true`` or ``false``: the user's answer to whether plan
                      text may be sent to TypeSafe (Jev). Absent means nobody
                      has asked yet, and live Jev calls are refused. Only the
                      user decides it; record the answer with ``set``.

Command line (the JSON envelope ``{success, data, error}``; exit 0, or 2 with a
typed error, including ``VALIDATION.INPUT`` for bad arguments)
  show [--repository-root PATH]
      read-only: the parsed settings and where they live
  set allow_remote_judge true|false [--repository-root PATH]
      record the user's answer, keeping every other key; commit the file
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import importlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
from types import ModuleType
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plan_anchor_paths import find_settings  # noqa: E402
from result import Err, Ok, Result, ToolError, err, utf8_stdio  # noqa: E402

SCHEMA_VERSION = 1
SETTINGS_RELPATH = ".sc/plan-anchor/settings.yaml"
TRACKERS = ("bd", "br")
ALLOWED_KEYS = ("schema_version", "anchor_tracker", "allow_remote_judge")
SETTABLE_KEYS = ("allow_remote_judge",)
PYYAML_INSTALL = "python3 -m pip install pyyaml"
ERROR_EXIT = 2

SETTINGS_HEADER = """\
# .sc/plan-anchor/settings.yaml
# Repository settings for the sc-plan-anchor plugin; commit this file, never put secrets in it.
schema_version: {schema_version}
"""
TRACKER_LINE = "anchor_tracker: {anchor_tracker}\n"
REMOTE_JUDGE_LINES = """\
# allow_remote_judge: may plan text be sent to TypeSafe (Jev) for judging? Only the user decides it.
allow_remote_judge: {value}
"""


@dataclass(frozen=True)
class Settings:
    schema_version: int
    anchor_tracker: Optional[str]
    allow_remote_judge: Optional[bool] = None


def load_yaml() -> Result[ModuleType, ToolError]:
    try:
        return Ok(importlib.import_module("yaml"))
    except ImportError:
        return err(
            "DEPENDENCY.PYYAML",
            "PyYAML is required to read .sc/plan-anchor/settings.yaml and is not installed",
            f"Install it: {PYYAML_INSTALL}",
        )


def _git_toplevel(start: Path) -> Optional[Path]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", check=False,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        return None
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out:
        return None
    return Path(out).resolve()


def find_repo_root(start: Path) -> Result[Path, ToolError]:
    """The git top level containing ``start``; walk up for ``.git`` when git cannot answer. Never cwd."""
    try:
        start = start.resolve(strict=True)
    except OSError:
        return err("REPO.NOT_FOUND", f"repository root hint {str(start)!r} does not exist",
                   "Pass --repository-root inside the git repository.")
    if start.is_file():
        start = start.parent
    top = _git_toplevel(start)
    if top is not None:
        return Ok(top)
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return Ok(candidate)
    return err("REPO.NOT_FOUND", f"{str(start)!r} is not inside a git repository",
               "Run from, or pass --repository-root inside, the repository that holds the plan.")


def settings_path(root: Path) -> Path:
    return root.joinpath(*SETTINGS_RELPATH.split("/"))


def _strict_loader(yaml: ModuleType) -> type:
    class StrictLoader(yaml.SafeLoader):  # type: ignore[name-defined, misc]
        def construct_mapping(self, node, deep=False):  # noqa: D401 - PyYAML hook
            seen = set()
            for key_node, _ in node.value:
                key = self.construct_object(key_node, deep=deep)
                try:
                    duplicate = key in seen
                except TypeError:
                    break  # unhashable key: PyYAML reports it below
                if duplicate:
                    raise yaml.constructor.ConstructorError(
                        None, None, f"duplicate key {key!r}", key_node.start_mark)
                seen.add(key)
            return super().construct_mapping(node, deep=deep)

    return StrictLoader


def parse_settings(text: str, yaml: ModuleType, *, path: str = SETTINGS_RELPATH) -> Result[Settings, ToolError]:
    fix = (f"Edit {path}: it must hold 'schema_version: {SCHEMA_VERSION}' and optionally "
           "'anchor_tracker: br' or 'anchor_tracker: bd' and 'allow_remote_judge: true' or 'allow_remote_judge: false'.")
    try:
        data: Any = yaml.load(text, Loader=_strict_loader(yaml))  # a SafeLoader subclass
    except yaml.YAMLError as exc:
        return err("SETTINGS.MALFORMED", f"{path} is not valid YAML: {exc}", fix)
    if not isinstance(data, dict):
        return err("SETTINGS.MALFORMED", f"{path} must be a YAML mapping, got {type(data).__name__}", fix)
    unknown = sorted(str(k) for k in data if k not in ALLOWED_KEYS)
    if unknown:
        return err("SETTINGS.UNKNOWN_KEY", f"{path} has unknown key(s): {', '.join(unknown)}",
                   f"Remove them; supported keys are {', '.join(ALLOWED_KEYS)}.",
                   data={"unknown_keys": unknown})
    version = data.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        return err("SETTINGS.SCHEMA_VERSION",
                   f"{path} schema_version is {version!r}; this plugin reads schema_version {SCHEMA_VERSION}",
                   fix, data={"schema_version": version if isinstance(version, (int, str)) else None})
    tracker = data.get("anchor_tracker")
    if "anchor_tracker" in data and tracker not in TRACKERS:
        return err("SETTINGS.INVALID_TRACKER",
                   f"{path} anchor_tracker is {tracker!r}; expected 'br' or 'bd'", fix)
    remote = data.get("allow_remote_judge")
    if "allow_remote_judge" in data and type(remote) is not bool:
        return err("SETTINGS.INVALID_REMOTE_JUDGE",
                   f"{path} allow_remote_judge is {remote!r}; expected true or false", fix)
    return Ok(Settings(schema_version=version, anchor_tracker=tracker, allow_remote_judge=remote))


def read_settings_file(path: Path, shown: Optional[str] = None) -> Result[Optional[Settings], ToolError]:
    """``Ok(None)`` when ``path`` is absent; the parsed settings, or a typed error.

    ``shown`` is how messages name the file (default: the path itself).
    """
    loaded = load_yaml()
    if isinstance(loaded, Err):
        return loaded
    shown = shown or str(path)
    if not path.exists() and not path.is_symlink():
        return Ok(None)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return err("SETTINGS.UNREADABLE", f"{shown} could not be read: {type(exc).__name__}",
                   f"Make {shown} a readable UTF-8 file.")
    return parse_settings(text, loaded.value, path=shown)


def read_settings(root: Path) -> Result[Optional[Settings], ToolError]:
    """The settings file exactly at ``root`` (no lookup): ``Ok(None)`` when it is absent."""
    return read_settings_file(settings_path(root), SETTINGS_RELPATH)


@dataclass(frozen=True)
class Effective:
    """The settings that apply at a location: the nearest file (``path`` None when there is none)."""
    settings: Optional[Settings]
    path: Optional[Path]


def effective_settings(start: Path) -> Result[Effective, ToolError]:
    """The nearest settings file at or above ``start`` (stopping before the home directory), parsed."""
    loaded = load_yaml()  # required even when no file exists: no silent fallback to defaults
    if isinstance(loaded, Err):
        return loaded
    path = find_settings(start)
    if path is None:
        return Ok(Effective(None, None))
    own = path == settings_path(Path(start).resolve()) or path == settings_path(Path(start))
    loaded = read_settings_file(path, SETTINGS_RELPATH if own else str(path))
    if isinstance(loaded, Err):
        return loaded
    return Ok(Effective(loaded.value, path))


def render_settings(settings: Settings) -> str:
    """The committed form: header comment, purpose line, one key per line (absent keys are omitted)."""
    if settings.anchor_tracker is not None and settings.anchor_tracker not in TRACKERS:
        raise ValueError(f"render_settings got tracker {settings.anchor_tracker!r}")  # caller bug
    if settings.allow_remote_judge is not None and type(settings.allow_remote_judge) is not bool:
        raise ValueError(f"render_settings got allow_remote_judge {settings.allow_remote_judge!r}")  # caller bug
    text = SETTINGS_HEADER.format(schema_version=settings.schema_version)
    if settings.anchor_tracker is not None:
        text += TRACKER_LINE.format(anchor_tracker=settings.anchor_tracker)
    if settings.allow_remote_judge is not None:
        text += REMOTE_JUDGE_LINES.format(value="true" if settings.allow_remote_judge else "false")
    return text


def write_settings(root: Path, settings: Settings) -> Result[Path, ToolError]:
    """Write ``root``'s own settings file (see ``write_settings_file``)."""
    return write_settings_file(settings_path(root), settings)


def write_settings_file(path: Path, settings: Settings) -> Result[Path, ToolError]:
    """Write atomically, then read the file back through the strict parser."""
    loaded = load_yaml()
    if isinstance(loaded, Err):
        return loaded
    text = render_settings(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    except OSError as exc:
        return err("SETTINGS.WRITE_FAILED", f"could not write {SETTINGS_RELPATH}: {type(exc).__name__}: {exc}",
                   f"Check permissions on {path.parent}.")
    reread = parse_settings(text, loaded.value)
    if isinstance(reread, Err) or reread.value != settings:
        raise AssertionError("rendered settings do not round-trip")  # bug, not an expected failure
    return Ok(path)


def git_ignored(root: Path, rel: str) -> Result[bool, str]:
    """Whether git ignores ``rel``; ``Err(reason)`` when git cannot say (reported, not fatal)."""
    try:
        proc = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "--", rel],
                              capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL)
    except OSError as exc:
        return Err(f"git could not start: {type(exc).__name__}: {exc}")
    if proc.returncode in (0, 1):
        return Ok(proc.returncode == 0)
    stderr = (proc.stderr or "").strip()[-500:]
    return Err(f"git check-ignore exited {proc.returncode}: {stderr or '(no stderr)'}")


# ---------------------------------------------------------------- allow_remote_judge

REMOTE_JUDGE_SET_COMMAND = "plan_anchor_settings.py set allow_remote_judge true|false"


def remote_judge_consent(root: Path) -> Result[bool, ToolError]:
    """The recorded answer: ``Ok(True)``, ``Ok(False)``, or ``SETTINGS.REMOTE_JUDGE_UNSET`` when nobody has asked.

    Read from the nearest settings file at or above ``root``. No file needs no
    PyYAML; a present one is parsed strictly (``DEPENDENCY.PYYAML`` when PyYAML
    is missing: never a silent default).
    """
    unset = err("SETTINGS.REMOTE_JUDGE_UNSET", f"{SETTINGS_RELPATH} does not set allow_remote_judge")
    if find_settings(root) is None:
        return unset
    loaded = effective_settings(root)
    if not loaded.ok:
        return loaded
    s = loaded.value.settings
    value = s.allow_remote_judge if s is not None else None
    return unset if value is None else Ok(value)


def set_value(start: Path, key: str, value: Any) -> Result[dict, ToolError]:
    """Record ``key`` in the settings file, keeping every other key; read it back strictly."""
    if key not in SETTABLE_KEYS:
        return err("VALIDATION.INPUT", f"{key!r} cannot be set here; settable keys: {', '.join(SETTABLE_KEYS)}",
                   "Set anchor_tracker with 'anchor_tracker.py write'.")
    root = find_repo_root(start)
    if not root.ok:
        return root
    effective = effective_settings(root.value)
    if not effective.ok:
        return effective  # a malformed file is never overwritten
    # The answer goes into the file that applies here: the nearest one, else a new one at the repository root.
    path = effective.value.path or settings_path(root.value)
    current = Ok(effective.value.settings)
    before = current.value if current.value is not None else Settings(schema_version=SCHEMA_VERSION, anchor_tracker=None)
    previous = getattr(before, key)
    after = replace(before, **{key: value})
    written = current.value is None or after != current.value
    if written:
        saved = write_settings_file(path, after)
        if not saved.ok:
            return saved
    checked = git_ignored(path.parent.parent.parent, SETTINGS_RELPATH)
    ignored = checked.value if checked.ok else None
    actions = [f"Commit {SETTINGS_RELPATH} so every clone and every agent uses this answer."] if written else []
    if ignored:
        actions.append(f"{SETTINGS_RELPATH} is gitignored; un-ignore it so the answer is committed.")
    elif not checked.ok:
        actions.append(f"Could not check whether {SETTINGS_RELPATH} is gitignored ({checked.error}); "
                       "confirm with 'git check-ignore -v' before committing.")
    return Ok({
        "key": key,
        "value": value,
        "previous": previous,
        "written": written,
        "repository_root": str(root.value),
        "settings_path": str(path),
        "settings_relpath": SETTINGS_RELPATH,
        "settings_inherited": path != settings_path(root.value),
        "settings_ignored_by_git": ignored,
        "settings_ignored_check_error": None if checked.ok else checked.error,
        "commit_paths": [SETTINGS_RELPATH] if written else [],
        "next_actions": actions,
    })


def show(start: Path) -> Result[dict, ToolError]:
    root = find_repo_root(start)
    if not root.ok:
        return root
    current = effective_settings(root.value)
    if not current.ok:
        return current
    s, path = current.value.settings, current.value.path
    return Ok({
        "repository_root": str(root.value),
        "settings_path": str(path) if path is not None else str(settings_path(root.value)),
        "settings_relpath": SETTINGS_RELPATH,
        "settings_present": s is not None,
        "settings_inherited": path is not None and path != settings_path(root.value),
        "schema_version": s.schema_version if s is not None else None,
        "anchor_tracker": s.anchor_tracker if s is not None else None,
        "allow_remote_judge": s.allow_remote_judge if s is not None else None,
    })


# ---------------------------------------------------------------- CLI


class _UsageError(Exception):
    pass


class _JsonArgumentParser(argparse.ArgumentParser):
    """Usage errors become a VALIDATION.INPUT envelope instead of argparse's text on stderr."""

    def error(self, message):  # argparse hook; never returns
        raise _UsageError(f"{self.prog}: {message}")


def _bool(text: str) -> bool:
    if text not in ("true", "false"):
        raise argparse.ArgumentTypeError(f"expected true or false, got {text!r}")
    return text == "true"


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="plan_anchor_settings.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_JsonArgumentParser)
    sh = sub.add_parser("show", help="read-only: the parsed settings")
    sh.add_argument("--repository-root", default=".", help="any path inside the repository (default: .)")
    st = sub.add_parser("set", help=f"record a value in {SETTINGS_RELPATH} (commit it)")
    st.add_argument("key", choices=SETTABLE_KEYS)
    st.add_argument("value", type=_bool, metavar="true|false")
    st.add_argument("--repository-root", default=".", help="any path inside the repository (default: .)")
    return parser


def _print(envelope: dict) -> None:
    print(json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False))


def main(argv: Optional[list] = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _UsageError as exc:
        _print({"success": False, "data": None, "error": ToolError(
            "VALIDATION.INPUT", str(exc), "Run 'plan_anchor_settings.py --help' for the accepted arguments.").to_json()})
        return ERROR_EXIT
    try:
        start = Path(args.repository_root)
        outcome = show(start) if args.command == "show" else set_value(start, args.key, args.value)
        if outcome.ok:
            envelope, code = {"success": True, "data": outcome.value, "error": None}, 0
        else:
            e = outcome.error
            envelope = {"success": False, "data": dict(e.data) if e.data is not None else None, "error": e.to_json()}
            code = ERROR_EXIT
    except Exception as exc:  # a bug, not an expected failure
        envelope = {"success": False, "data": None, "error": ToolError(
            "SCRIPT.INTERNAL", f"{type(exc).__name__}: {exc}",
            "Report this with the command line that produced it.").to_json()}
        code = ERROR_EXIT
    _print(envelope)
    return code


if __name__ == "__main__":
    utf8_stdio()
    sys.exit(main())
