#!/usr/bin/env python3
"""Version discipline for the sc-plan-anchor plugin: VERSION is the single source of truth.

Default (consistency):
  VERSION holds X.Y.Z. Every version declared in shipped metadata equals it
  exactly: plugin manifests, marketplace manifests, SKILL.md, every
  references/*.md, every harness agent, every registry.yaml entry, and any
  other `version:` in a shipped .md frontmatter, .yaml/.yml or .json manifest.
  Files are discovered by globbing (see version_declarations), so a new agent
  or reference cannot escape. CHANGELOG.md has a "## X.Y.Z" entry. Agent
  model pins, registry paths, manifest identities and marketplace sources are
  checked too.

--base <ref> (pull-request rule):
  A PR that changes shipped content (plugins/ or a marketplace manifest) must
  raise VERSION above the base's VERSION (with everything above moving with
  it) and change CHANGELOG.md. A PR that touches only tests, scripts/ or docs
  needs no bump.

Not release metadata, so not checked: `schema_version` fields and the
`metadata.version` of templates/*.md.j2 (wire-contract versions pinned by the
JSON schemas' `const`), and integer document versions (question sets,
anchors, examples).

Exit 0 in sync, 1 drift (each on its own line), 2 missing files or bad input.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
SKILL = PLUGIN / "skills" / "plan-anchoring"
AGENT_DIRS = {
    "claude": PLUGIN / ".claude" / "agents",
    "codex": PLUGIN / ".codex" / "agents",
    "cursor": PLUGIN / ".cursor" / "agents",
}
FRONT_RE = re.compile(r"^---\n(.*?)\n---", re.S)
VER_RE = re.compile(r'^\s*version:\s*["\']?([0-9]+\.[0-9]+\.[0-9]+)["\']?\s*$', re.M)
MODEL_RE = re.compile(r"^model:\s*(\S+)\s*$", re.M)
SEMVER_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")

# Shipped content: what an install copies or a marketplace reads.
SHIPPED_PREFIXES = ("plugins/", ".claude-plugin/", ".agents/", ".cursor-plugin/")
# Every file matching these must declare a version.
REQUIRED_GLOBS = (
    "plugins/*/plugin.json",
    "plugins/*/.claude-plugin/plugin.json",
    "plugins/*/.codex-plugin/plugin.json",
    "plugins/*/.cursor-plugin/plugin.json",
    "plugins/*/skills/*/SKILL.md",
    "plugins/*/skills/*/references/*.md",
    "plugins/*/.claude/agents/*.md",
    "plugins/*/.codex/agents/*.md",
    "plugins/*/.cursor/agents/*.md",
    "plugins/*/.claude/agents/registry.yaml",
    "plugins/*/.codex/agents/registry.yaml",
    "plugins/*/.cursor/agents/registry.yaml",
)
# Any version these declare must equal VERSION (catch-all for new metadata).
SCANNED_GLOBS = (
    "plugins/**/*.md",
    "plugins/**/*.json",
    "plugins/**/*.yaml",
    "plugins/**/*.yml",
    ".claude-plugin/*.json",
    ".agents/plugins/*.json",
    ".cursor-plugin/*.json",
)


def _declared(path: pathlib.Path) -> list:
    """Semver versions a metadata file declares (frontmatter, YAML, or JSON manifest keys)."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        m = FRONT_RE.match(text)
        return VER_RE.findall(m.group(1)) if m else []
    if path.suffix in (".yaml", ".yml"):
        return VER_RE.findall(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ["<invalid JSON>"]
    if not isinstance(data, dict):
        return []
    values = [data.get("version")] + [p.get("version") for p in data.get("plugins", []) if isinstance(p, dict)]
    return [v for v in values if isinstance(v, str) and SEMVER_RE.fullmatch(v)]


def version_declarations(root: pathlib.Path) -> list:
    """[(relative path, [versions])] for every shipped metadata file; [] means a required file declares none."""
    found = {}
    for pattern in SCANNED_GLOBS:
        for f in root.glob(pattern):
            if f.is_file():
                versions = _declared(f)
                if versions:
                    found[f.relative_to(root).as_posix()] = versions
    for pattern in REQUIRED_GLOBS:
        for f in root.glob(pattern):
            found.setdefault(f.relative_to(root).as_posix(), _declared(f))
    return sorted(found.items())


def ssot_drift(root: pathlib.Path, want: str) -> list:
    """Every version declaration that does not equal VERSION, plus a missing CHANGELOG entry."""
    drift = []
    for pattern in REQUIRED_GLOBS:
        if not any(root.glob(pattern)):
            drift.append(f"{pattern}: no file matches (layout changed?)")
    for rel, versions in version_declarations(root):
        if not versions:
            drift.append(f"{rel}: declares no version (must be {want})")
        for v in versions:
            if v != want:
                drift.append(f"{rel}: {v} != VERSION {want}")
    changelog = root / "CHANGELOG.md"
    if not changelog.exists() or not re.search(rf"^## {re.escape(want)}\b", changelog.read_text(encoding="utf-8"), re.M):
        drift.append(f"CHANGELOG.md has no '## {want}' entry")
    return drift


def parse(v: str):
    return tuple(int(x) for x in v.split("."))


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout


def show(ref: str, rel: str):
    out = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=ROOT, capture_output=True, text=True, check=False)
    return out.stdout if out.returncode == 0 else None


def release_checks(want: str, drift: list) -> int:
    declarations = version_declarations(ROOT)
    drift.extend(ssot_drift(ROOT, want))
    wmaj = parse(want)[0]
    for harness, agent_dir in AGENT_DIRS.items():
        for f in sorted(agent_dir.glob("*.md")):
            front = FRONT_RE.match(f.read_text(encoding="utf-8"))
            model_match = MODEL_RE.search(front.group(1)) if front else None
            if harness == "cursor":
                expected = "grok[effort=high]" if f.name == "anchor-tuning.md" else "composer"
            elif f.name == "anchor-tuning.md":
                expected = "opus" if harness == "claude" else "sol"
            else:
                expected = "sonnet" if harness == "claude" else "luna"
            if not model_match or model_match.group(1) != expected:
                drift.append(f"{f.relative_to(ROOT)}: model must be {expected} for the {harness} harness")
    expected_agents = {f.stem for f in AGENT_DIRS["claude"].glob("*.md")}
    for harness, agent_dir in AGENT_DIRS.items():
        actual_agents = {f.stem for f in agent_dir.glob("*.md")}
        if actual_agents != expected_agents:
            drift.append(f"{agent_dir.relative_to(ROOT)}: agent files {sorted(actual_agents)} != {sorted(expected_agents)}")
        reg = agent_dir / "registry.yaml"
        if not reg.exists():
            drift.append(f"{reg.relative_to(ROOT)}: missing")
            continue
        text = reg.read_text(encoding="utf-8")
        registered = set()
        for m in re.finditer(r"^  ([a-z0-9-]+):\n    version:\s*([0-9.]+)\n    path:\s*(\S+)", text, re.M):
            name, _, path = m.groups()
            if name.startswith("anchor-"):
                registered.add(name)
            if not (PLUGIN / path.lstrip("/")).exists():
                drift.append(f"registry.yaml {name}: path {path} not found")
        if registered != expected_agents:
            drift.append(f"{reg.relative_to(ROOT)}: agents {sorted(registered)} != {sorted(expected_agents)}")
        dependencies = set()
        for m in re.finditer(r'(anchor-[a-z-]+):\s*"([^"]+)"', text):
            dependencies.add(m.group(1))
            if m.group(2) not in (want, f"{wmaj}.x"):
                drift.append(f"{reg.relative_to(ROOT)} depends_on {m.group(1)}: {m.group(2)} does not cover {want}")
        if dependencies != expected_agents:
            drift.append(f"{reg.relative_to(ROOT)}: depends_on {sorted(dependencies)} != {sorted(expected_agents)}")
    plugin_manifests = [
        PLUGIN / "plugin.json",
        PLUGIN / ".claude-plugin" / "plugin.json",
        PLUGIN / ".codex-plugin" / "plugin.json",
        PLUGIN / ".cursor-plugin" / "plugin.json",
    ]
    for manifest in plugin_manifests:
        if not manifest.exists():
            drift.append(f"{manifest.relative_to(ROOT)}: missing")
            continue
        data = json.loads(manifest.read_text())
        if data.get("name") != "sc-plan-anchor":
            drift.append(f"{manifest.relative_to(ROOT)}: name must be sc-plan-anchor")
    claude_manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    expected_claude_agents = {f"./.claude/agents/{name}.md" for name in expected_agents}
    if set(claude_manifest.get("agents", [])) != expected_claude_agents:
        drift.append("Claude manifest agents do not match .claude/agents")
    catalogs = [
        ROOT / ".claude-plugin" / "marketplace.json",
        ROOT / ".agents" / "plugins" / "marketplace.json",
        ROOT / ".cursor-plugin" / "marketplace.json",
    ]
    cursor_manifest = json.loads((PLUGIN / ".cursor-plugin" / "plugin.json").read_text())
    if cursor_manifest.get("skills") != "./skills/":
        drift.append("Cursor manifest skills must be ./skills/")
    if cursor_manifest.get("agents") != "./.cursor/agents":
        drift.append("Cursor manifest agents must be ./.cursor/agents")
    for catalog in catalogs:
        if not catalog.exists():
            drift.append(f"{catalog.relative_to(ROOT)}: missing")
            continue
        data = json.loads(catalog.read_text())
        entries = [p for p in data.get("plugins", []) if p.get("name") == "sc-plan-anchor"]
        if len(entries) != 1:
            drift.append(f"{catalog.relative_to(ROOT)}: expected one sc-plan-anchor entry")
            continue
        source = entries[0].get("source")
        source_path = source.get("path") if isinstance(source, dict) else source
        if source_path != "./plugins/sc-plan-anchor":
            drift.append(f"{catalog.relative_to(ROOT)}: source must be ./plugins/sc-plan-anchor")
        elif not (ROOT / source_path[2:]).is_dir():
            drift.append(f"{catalog.relative_to(ROOT)}: source path does not exist")
    return sum(len(v) or 1 for _, v in declarations)


def pr_checks(base: str, want: str, drift: list) -> str:
    changed = set(l for l in git("diff", "--name-only", f"{base}...HEAD").splitlines() if l.strip())
    changed |= set(l for l in git("diff", "--name-only", base).splitlines() if l.strip())          # working tree edits
    changed |= set(l for l in git("ls-files", "--others", "--exclude-standard").splitlines() if l.strip())  # new, uncommitted files
    shipped = sorted(rel for rel in changed if rel.startswith(SHIPPED_PREFIXES))
    base_version = (show(base, "VERSION") or "").strip()
    if not SEMVER_RE.fullmatch(base_version):
        return f"no VERSION at {base}; consistency checks only"
    raised = parse(want) > parse(base_version)
    if shipped and not raised:
        listed = ", ".join(shipped[:5]) + (f" (+{len(shipped) - 5} more)" if len(shipped) > 5 else "")
        drift.append(f"shipped content changed ({listed}) but VERSION is still {want}; raise VERSION above {base_version} and every version with it")
    if parse(want) < parse(base_version):
        drift.append(f"VERSION {want} is below {base}'s {base_version}")
    if raised and "CHANGELOG.md" not in changed:
        drift.append(f"VERSION changed {base_version} -> {want} but CHANGELOG.md did not")
    return f"pull-request rule against {base} (VERSION {base_version} -> {want}, {len(shipped)} shipped file(s) changed)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="", help="git ref of the PR base; enables the pull-request rule")
    args = ap.parse_args()
    vfile = ROOT / "VERSION"
    if not vfile.exists():
        print("check-version-sync: VERSION file missing", file=sys.stderr)
        return 2
    want = vfile.read_text().strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", want):
        print(f"check-version-sync: VERSION is not X.Y.Z: {want!r}", file=sys.stderr)
        return 2
    drift: list = []
    checked = release_checks(want, drift)
    mode = pr_checks(args.base, want, drift) if args.base else "consistency"
    if drift:
        print(f"check-version-sync [{mode}]: {len(drift)} drift(s) from VERSION {want}:")
        for d in drift:
            print(f"  {d}")
        return 1
    print(f"check-version-sync [{mode}]: {checked} version declarations equal {want}, CHANGELOG entry present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
