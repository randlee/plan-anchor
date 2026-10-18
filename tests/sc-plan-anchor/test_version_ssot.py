"""VERSION is the single source of truth for every shipped version declaration.

Discovery is by glob (scripts/check_version_sync.py: REQUIRED_GLOBS must each
declare a version, SCANNED_GLOBS catch any other declaration), so a new agent,
reference, registry or manifest cannot escape the check.
"""
from pathlib import Path
import importlib.util
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


def _load_sync():
    spec = importlib.util.spec_from_file_location("check_version_sync", ROOT / "scripts" / "check_version_sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = _load_sync()


def _copy_shipped(dest: Path) -> None:
    for name in ("VERSION", "CHANGELOG.md"):
        shutil.copy2(ROOT / name, dest / name)
    for name in ("plugins", ".claude-plugin", ".agents", ".cursor-plugin"):
        if (ROOT / name).exists():
            shutil.copytree(ROOT / name, dest / name)


class VersionSingleSourceOfTruthTests(unittest.TestCase):
    def setUp(self):
        self.version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    def test_every_shipped_version_equals_version_file(self):
        drift = sync.ssot_drift(ROOT, self.version)
        self.assertEqual(drift, [], "drift from VERSION %s:\n  %s" % (self.version, "\n  ".join(drift)))

    def test_discovery_covers_every_required_class(self):
        found = dict(sync.version_declarations(ROOT))
        plugin = "plugins/sc-plan-anchor"
        expected = [
            f"{plugin}/plugin.json",
            f"{plugin}/.claude-plugin/plugin.json",
            f"{plugin}/.codex-plugin/plugin.json",
            f"{plugin}/.cursor-plugin/plugin.json",
            f"{plugin}/skills/plan-anchor-installer/SKILL.md",
            ".claude-plugin/marketplace.json",
        ]
        # The installed skill and references are templates rendered with plugin.json's version; the
        # agent frontmatter and registries are per-harness sources under install/harness/.
        for harness in ("claude", "codex", "cursor"):
            agents = ROOT / plugin / "install" / "harness" / harness / "agents"
            expected.append(f"{plugin}/install/harness/{harness}/registry.yaml")
            found_agents = sorted(agents.glob("*.md"))
            self.assertEqual(len(found_agents), 3, harness)
            expected.extend(f.relative_to(ROOT).as_posix() for f in found_agents)
        for rel in expected:
            self.assertIn(rel, found)
            self.assertTrue(found[rel], f"{rel} declares no version")

    def test_every_install_template_takes_the_version_from_the_render(self):
        templates = sorted((ROOT / "plugins/sc-plan-anchor/install/templates").rglob("*.md.j2"))
        self.assertTrue(templates)
        self.assertEqual(sync.template_drift(ROOT), [])

    def test_changelog_has_version_section(self):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertRegex(text, rf"(?m)^## {self.version.replace('.', r'[.]')}\b")

    def test_planted_drift_is_reported_by_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_shipped(root)
            self.assertEqual(sync.ssot_drift(root, self.version), [])
            rel = "plugins/sc-plan-anchor/install/harness/codex/agents/anchor-plan-review.md"
            target = root / rel
            text = target.read_text(encoding="utf-8")
            self.assertIn(f"version: {self.version}", text)
            target.write_text(text.replace(f"version: {self.version}", "version: 0.0.1", 1), encoding="utf-8")
            drift = sync.ssot_drift(root, self.version)
            self.assertEqual(drift, [f"{rel}: 0.0.1 != VERSION {self.version}"])

    def test_planted_literal_version_in_a_template_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_shipped(root)
            rel = "plugins/sc-plan-anchor/install/templates/skills/plan-anchoring/references/jev-api.md.j2"
            target = root / rel
            text = target.read_text(encoding="utf-8")
            self.assertIn("version: {{ version }}", text)
            target.write_text(text.replace("version: {{ version }}", f"version: {self.version}", 1), encoding="utf-8")
            self.assertEqual(sync.ssot_drift(root, self.version),
                             [f"{rel}: rendered version must be {{{{ version }}}}, not a literal"])

    def test_new_unversioned_agent_cannot_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_shipped(root)
            rel = "plugins/sc-plan-anchor/install/harness/codex/agents/anchor-new.md"
            (root / rel).write_text("---\nname: anchor-new\nmodel: luna\n---\n\nbody\n", encoding="utf-8")
            drift = sync.ssot_drift(root, self.version)
            self.assertIn(f"{rel}: declares no version (must be {self.version})", drift)

    def test_missing_changelog_section_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_shipped(root)
            (root / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n", encoding="utf-8")
            self.assertEqual(sync.ssot_drift(root, self.version), [f"CHANGELOG.md has no '## {self.version}' entry"])


if __name__ == "__main__":
    unittest.main()
