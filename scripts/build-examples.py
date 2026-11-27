#!/usr/bin/env python3
"""Build the site's generated examples from their checked-in inputs, offline.

Each example under site/examples/<name>/ keeps its real inputs in inputs/ and is regenerated here with the
scripts as an install renders them, so a change to the scripts or templates needs only a re-run. pages.yml
runs this at deploy, beside build-site.py; the generated report, sidecar, panels and trace are build
artifacts and are never committed (site/examples/.gitignore).

  record-cleanup  jev_judge.py trace --index --ids --anchors --answers-file (fixture answers: no network), with
                  --annotations inputs/annotations.json when that file exists, then
                  change_report.py --trace --proposals --out site/examples/record-cleanup/

Needs the sc-compose CLI on PATH (the scripts are rendered with it, and change_report renders the report with
it), as the tests do. Usage: python3 scripts/build-examples.py [--out DIR]
(--out writes <DIR>/<example>/ instead of site/examples/<example>/, and --inputs reads the record-cleanup inputs from
DIR instead of site/examples/record-cleanup/inputs/; the tests use both.)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import NoReturn
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
SKILL_SRC = PLUGIN / "install" / "templates" / "skills" / "plan-anchoring"
HARNESS = PLUGIN / "install" / "harness"
EXAMPLES = ROOT / "site" / "examples"
TRACKER = "br"   # the trace and its report read no tracker; br is the tests' default render


def die(message: str) -> NoReturn:
    """Exit 2 with a message, the repository CI scripts' convention (never 1, never a traceback)."""
    print(f"build-examples: {message}", file=sys.stderr)
    raise SystemExit(2)


def installer():
    spec = importlib.util.spec_from_file_location("sc_plan_anchor_install", PLUGIN / "install.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sc_compose() -> str:
    binary = shutil.which("sc-compose")
    if binary is None:
        die("the sc-compose CLI (1.8.0 or newer) must be on PATH (scripts/install_sc_compose_ci.py)")
    return binary


def render(binary: str, template: Path, out: Path, version: str) -> None:
    """One strict render, as tests/sc-plan-anchor/layout_support.py render_cli and install.py do."""
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([binary, "render", "--root", str(template.parent), "--strict", "--var", f"tracker={TRACKER}",
                           "--var", f"version={version}", "--file", str(template), "--output", str(out)],
                          cwd=out.parent, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if proc.returncode != 0:
        die(f"sc-compose render {template.name} failed: {proc.stderr[-2000:]}")
    data = out.read_bytes()
    if not data.endswith(b"\n"):
        out.write_bytes(data + b"\n")


def render_skill(dest: Path) -> Path:
    """The plan-anchoring skill as install.py lays it out for TRACKER; returns its scripts folder."""
    inst = installer()
    package = inst.load_package()
    if isinstance(package, inst.Err):
        die(f"{package.error.message}")
    binary = sc_compose()
    version = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))["version"]
    for rel in package.value.skill:
        src = HARNESS / "claude" / rel if rel == "registry.yaml" else SKILL_SRC / rel
        out = dest / rel
        if rel in package.value.rendered:
            render(binary, SKILL_SRC / f"{rel}.j2", out, version)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, out)
    return dest / "scripts"


def run(argv: list, cwd: Path) -> dict:
    proc = subprocess.run([sys.executable, *argv], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        envelope = None
    if proc.returncode != 0 or not isinstance(envelope, dict) or not envelope.get("success"):
        die(f"{Path(argv[0]).name} {argv[1] if len(argv) > 1 else ''} failed (exit {proc.returncode}):\n"
                 f"{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
    return envelope["data"]


def record_cleanup(scripts: Path, scratch: Path, out_root: Path, inputs: Path) -> dict:
    annotations = inputs / "annotations.json"
    example = out_root / "record-cleanup"
    example.mkdir(parents=True, exist_ok=True)
    runs = scratch / "record-cleanup-runs"
    trace = run([str(scripts / "jev_judge.py"), "trace", "--anchors", str(inputs / "anchors.json"),
                 "--index", str(inputs / "raptor-sc-agent.json"), "--ids", str(inputs / "ids.txt"),
                 "--answers-file", str(inputs / "answers.json"), "--out-dir", str(runs),
                 "--repository-root", str(scratch),
                 *(["--annotations", str(annotations)] if annotations.is_file() else [])], scratch)
    for stale in ("report.html", "report.json", "trace.json"):
        (example / stale).unlink(missing_ok=True)
    shutil.rmtree(example / "report", ignore_errors=True)
    shutil.copyfile(trace["trace_path"], example / "trace.json")
    report = run([str(scripts / "change_report.py"), "--trace", str(example / "trace.json"),
                  "--proposals", str(inputs / "proposals.json"), "--out", str(example), "--name", "report",
                  "--title", "Record cleanup example: sc-agent records against phase-j anchors",
                  "--repository-root", str(scratch)], scratch)
    return {"trace": trace, "report": report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(EXAMPLES), help="folder the examples are written under (default site/examples)")
    parser.add_argument("--inputs", default=str(EXAMPLES / "record-cleanup" / "inputs"),
                        help="folder holding the record-cleanup inputs (default site/examples/record-cleanup/inputs)")
    args = parser.parse_args()
    out_root, inputs = Path(args.out).resolve(), Path(args.inputs).resolve()
    with tempfile.TemporaryDirectory(prefix="build-examples-") as tmp:
        scratch = Path(tmp)
        scripts = render_skill(scratch / "skill" / ".claude" / "skills" / "plan-anchoring")
        built = record_cleanup(scripts, scratch, out_root, inputs)
    t, r = built["trace"], built["report"]
    print(f"record-cleanup: {t['cells']} cells, {t['overlap']} overlap statements, "
          f"{r.get('proposals')} proposals, {len(r.get('unannotated_cells') or [])} red or yellow cells without a reviewer "
          f"annotation -> {out_root / 'record-cleanup' / 'report.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
