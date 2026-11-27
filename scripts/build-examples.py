#!/usr/bin/env python3
"""Build the site's generated examples from their checked-in inputs, offline.

Each example under site/examples/<name>/ keeps its real inputs in inputs/ and is regenerated here with the
scripts as an install renders them, so a change to the scripts or templates needs only a re-run. pages.yml
runs this at deploy, beside build-site.py; the generated report, sidecar, panels and trace are build
artifacts and are never committed (site/examples/.gitignore).

  record-cleanup  jev_judge.py trace --index --ids --anchors --answers-file (fixture answers: no network), then
                  change_report.py --trace --proposals --draft --out site/examples/record-cleanup/, with
                  --annotations inputs/annotations.json when that file exists. The inputs are copied
                  into the scratch repository root first, so the trace records them as inputs/<file>, never as
                  build-machine paths, and the rendered references/record-trace.md is written beside the report
                  as the target of its "Correcting duplicates" links.

Provenance: the trace reads each statement's git provenance from the records' repository at the commit in
inputs/source.json ({repository, commit}). --records-checkout DIR uses an existing checkout (HEAD must be that
commit); otherwise a partial clone (--filter=blob:none, full history, as git log -S needs) is made or reused under
--cache (default ~/.cache/plan-anchor-examples) and that commit is checked out. Every statement of the traced records
must be found in the files at that commit (git grep), else the build fails. --no-provenance builds offline (the tests).

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
from typing import NoReturn, Optional
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


def git(*argv: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=dict(os.environ, GIT_TERMINAL_PROMPT="0"), check=False)


def records_checkout(inputs: Path, given: str, cache: Path) -> Path:
    """The records' repository at inputs/source.json's commit: --records-checkout, else a cached partial clone."""
    try:
        source = json.loads((inputs / "source.json").read_text(encoding="utf-8"))
        url, commit = source["repository"], source["commit"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        die(f"{inputs / 'source.json'} must be {{repository, commit}}: {exc}")
    if given:
        repo = Path(given).resolve()
        head = git("rev-parse", "HEAD", cwd=repo)
        if head.returncode != 0 or head.stdout.strip() != commit:
            die(f"--records-checkout {repo} must have {commit} checked out (HEAD is {head.stdout.strip() or head.stderr.strip()})")
        return repo
    repo = cache / url.rstrip("/").rsplit("/", 1)[-1]
    if not (repo / ".git").exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        got = subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", url, str(repo)],
                             capture_output=True, text=True, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"), check=False)
        if got.returncode != 0:
            die(f"could not clone {url}: {got.stderr.strip()[-500:]}")
    if git("cat-file", "-e", f"{commit}^{{commit}}", cwd=repo).returncode != 0:
        git("fetch", "--quiet", "origin", commit, cwd=repo)
    got = git("checkout", "--quiet", "--detach", commit, cwd=repo)
    if got.returncode != 0:
        die(f"could not check out {commit} in {repo}: {got.stderr.strip()[-500:]}")
    return repo


def check_statements(trace: dict, repo: Path, commit: str) -> None:
    """Fail unless every traced record's statements are in the files at ``commit``: the index and the checkout agree."""
    missing = []
    for r in trace["records"]:
        listed = (r.get("obligations") or {}).get("statements") or []
        texts = [x.get("text", "") for x in listed if isinstance(x, dict)]
        if not texts:
            d = (r.get("raptor") or {}).get("decision")
            texts = [d.get("text") if isinstance(d, dict) else d] if d else []
        for t in texts:
            needle = (t or "").strip().splitlines()[0][:60] if (t or "").strip() else ""
            if needle and git("grep", "-q", "-F", "-e", needle, commit, "--", ".", cwd=repo).returncode != 0:
                missing.append(f"{r['id']}: {needle}")
    if missing:
        die(f"the Raptor index does not match {repo} at {commit}; not found:\n  " + "\n  ".join(missing))


def record_cleanup(scripts: Path, scratch: Path, out_root: Path, source_inputs: Path, history: Optional[Path] = None) -> dict:
    inputs = scratch / "inputs"
    shutil.copytree(source_inputs, inputs)
    annotations = inputs / "annotations.json"
    example = out_root / "record-cleanup"
    example.mkdir(parents=True, exist_ok=True)
    runs = scratch / "record-cleanup-runs"
    trace = run([str(scripts / "jev_judge.py"), "trace", "--anchors", str(inputs / "anchors.json"),
                 "--index", str(inputs / "raptor-sc-agent.json"), "--ids", str(inputs / "ids.txt"),
                 "--answers-file", str(inputs / "answers.json"), "--out-dir", str(runs),
                 "--repository-root", str(scratch),
                 *(["--history", str(history)] if history else ["--no-provenance"])], scratch)
    if history:
        check_statements(json.loads(Path(trace["trace_path"]).read_text(encoding="utf-8")), history,
                         json.loads((inputs / "source.json").read_text(encoding="utf-8"))["commit"])
    for stale in ("report.html", "report.json", "trace.json", "record-trace.md"):
        (example / stale).unlink(missing_ok=True)
    shutil.rmtree(example / "report", ignore_errors=True)
    shutil.copyfile(trace["trace_path"], example / "trace.json")
    shutil.copyfile(scripts.parent / "references" / "record-trace.md", example / "record-trace.md")
    report = run([str(scripts / "change_report.py"), "--trace", str(example / "trace.json"),
                  "--proposals", str(inputs / "proposals.json"), "--out", str(example), "--name", "report",
                  "--guidance-url", "record-trace.md#correcting-duplicates", "--draft",
                  *(["--annotations", str(annotations)] if annotations.is_file() else []),
                  "--title", "Record cleanup example: sc-agent records against phase-j anchors",
                  "--repository-root", str(scratch)], scratch)
    return {"trace": trace, "report": report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(EXAMPLES), help="folder the examples are written under (default site/examples)")
    parser.add_argument("--inputs", default=str(EXAMPLES / "record-cleanup" / "inputs"),
                        help="folder holding the record-cleanup inputs (default site/examples/record-cleanup/inputs)")
    parser.add_argument("--records-checkout", default="", help="an existing checkout of inputs/source.json's repository at its commit")
    parser.add_argument("--cache", default=str(Path.home() / ".cache" / "plan-anchor-examples"),
                        help="where the records' repository is cloned when --records-checkout is not given")
    parser.add_argument("--no-provenance", action="store_true", help="build offline: no clone, no git provenance")
    args = parser.parse_args()
    out_root, inputs = Path(args.out).resolve(), Path(args.inputs).resolve()
    with tempfile.TemporaryDirectory(prefix="build-examples-") as tmp:
        scratch = Path(tmp)
        scripts = render_skill(scratch / "skill" / ".claude" / "skills" / "plan-anchoring")
        history = None if args.no_provenance else records_checkout(inputs, args.records_checkout, Path(args.cache))
        built = record_cleanup(scripts, scratch, out_root, inputs, history)
    t, r = built["trace"], built["report"]
    rows = [x for rec in json.loads((out_root / "record-cleanup" / "trace.json").read_text(encoding="utf-8"))["records"]
            for x in rec.get("provenance") or []]
    found = sum(1 for x in rows if x.get("provenance"))
    print(f"record-cleanup provenance: {found} statements with a commit, {len(rows) - found} null"
          + ("" if rows else " (--no-provenance)"))
    print(f"record-cleanup: {t['cells']} cells, {t['overlap']} overlap statements, "
          f"{r.get('proposals')} proposals, {len(r.get('unannotated_cells') or [])} red or yellow cells and duplicates without "
          f"an annotation with git history -> {out_root / 'record-cleanup' / 'report.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
