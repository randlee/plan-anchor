"""plugins/sc-plan-anchor/install.py: rendering, ownership, upgrades, tracker switching, envelope.

Tests that render need the sc-compose wheel (CPython 3.11 wheels on PyPI) and
PyYAML; without them they skip with the reason. CI's installer job sets
PLAN_ANCHOR_REQUIRE_SC_COMPOSE=1, which turns those skips into failures.
"""

import contextlib
import fnmatch
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
SKILL = PLUGIN / "skills" / "plan-anchoring"
TEMPLATES = PLUGIN / "install" / "templates"
INSTALLER = PLUGIN / "install.py"
GENERATOR = ROOT / "scripts" / "gen_install_data.py"
VERSION = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))["version"]
REQUIRE = os.environ.get("PLAN_ANCHOR_REQUIRE_SC_COMPOSE") == "1"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


inst = _load("sc_plan_anchor_install", INSTALLER)
gen = _load("gen_install_data", GENERATOR)


def _missing_deps():
    missing = []
    for module in ("yaml", "sc_compose"):
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(module)
    if "sc_compose" not in missing and isinstance(inst.check_sc_compose(), inst.Err):
        missing.append("sc_compose (version outside >=1.7.0,<2)")
    return missing


MISSING = _missing_deps()
SKIP_REASON = (f"needs {', '.join(MISSING)}: pip install pyyaml 'sc-compose>=1.7.0,<2' "
               "(sc-compose publishes CPython 3.11 wheels); CI's installer job runs these")


def needs_wheel(cls):
    if MISSING and REQUIRE:
        raise RuntimeError(f"PLAN_ANCHOR_REQUIRE_SC_COMPOSE=1 but {SKIP_REASON}")
    return unittest.skipIf(bool(MISSING), SKIP_REASON)(cls)


def _git(*args, cwd=ROOT):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, check=True).stdout


def _has_commit(rev):
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"],
                          capture_output=True).returncode == 0


def sha(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- single-tracker text

# Whole-word tracker names, including example ids such as bd-42; a path segment
# (scripts/bd_x.py, .beads/) is not a mention.
BD_WORD = re.compile(r"(?<![\w./<-])bd(?!\w)")
BR_WORD = re.compile(r"(?<![\w./<-])br(?!\w)")
# Installed files that may name both trackers, each with its reason. Every
# other installed file (prompt text and data alike) names only the selected one.
MIXED_BY_DESIGN = {
    "references/installation-and-troubleshooting.md": "the install guide explains choosing and switching trackers",
    "scripts/*.py": "code, not prompt text: the scripts support both trackers at run time",
}


def mixed_by_design(rel):
    return any(fnmatch.fnmatchcase(rel, pattern) for pattern in MIXED_BY_DESIGN)


def other_tracker_mentions(text, tracker):
    """Lines of an installed .md that name the other tracker (allow-list applied)."""
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        if tracker == "br":
            if BD_WORD.search(line):
                hits.append((number, line))
        elif BR_WORD.search(line):
            hits.append((number, line))
    return hits


class TempRepo:
    """A git repository with an optional .beads/ workspace."""

    def __init__(self, test, beads=None):
        self.dir = tempfile.TemporaryDirectory()
        test.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        if beads is not None:
            self.beads(beads)

    def beads(self, backend):
        shutil.rmtree(self.root / ".beads", ignore_errors=True)
        if backend is None:
            return
        (self.root / ".beads").mkdir()
        (self.root / ".beads" / "metadata.json").write_text(json.dumps({"backend": backend}), encoding="utf-8")

    def path(self, rel):
        return self.root / rel

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file() and ".git" not in p.relative_to(self.root).parts}


def fake_which(name):
    return f"/fake/bin/{name}"


class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, cwd=None, **kwargs):
        self.calls.append(list(argv))
        (Path(cwd) / ".beads").mkdir(exist_ok=True)
        (Path(cwd) / ".beads" / "metadata.json").write_text('{"backend": "sqlite"}', encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")


def run_install(repo, tracker=None, targets=("claude",), **kw):
    run = kw.pop("run", FakeRun())
    opts = inst.Options(dest=repo.root, tracker=tracker, targets=list(targets), **kw)
    return inst.install(opts, which=fake_which, run=run)


# ---------------------------------------------------------------- rendering


@needs_wheel
class RenderingTests(unittest.TestCase):
    def setUp(self):
        import sc_compose
        self.sc = sc_compose
        package = inst.load_package()
        self.assertIsInstance(package, inst.Ok, getattr(package, "error", None))
        self.package = package.value
        self.renderer = inst.Renderer(sc_compose, self.package)

    def render(self, template, tracker):
        out = inst.render_template(self.sc, template, tracker, VERSION)
        self.assertIsInstance(out, inst.Ok, getattr(out, "error", None))
        return out.value

    def test_committed_tree_is_the_neutral_render(self):
        for rel in sorted(self.package.skill_templates):
            text = self.render(TEMPLATES / "skills" / "plan-anchoring" / f"{rel}.j2", "neutral")
            self.assertEqual((SKILL / rel).read_text(encoding="utf-8"), text,
                             f"skills/plan-anchoring/{rel} differs from its template's neutral render")
        for name in sorted(self.package.agent_templates):
            body = self.render(TEMPLATES / "agents" / f"{name}.j2", "neutral")
            for target in inst.TARGETS:
                committed = (PLUGIN / f".{target}" / "agents" / name).read_text(encoding="utf-8")
                front, _ = inst._split_frontmatter(committed)
                self.assertEqual(committed, front + body, f".{target}/agents/{name} differs from the neutral render")

    def test_every_template_renders_strictly_for_each_tracker(self):
        for template in sorted(TEMPLATES.rglob("*.j2")):
            for tracker in inst.RENDERINGS:
                self.render(template, tracker)

    def test_br_and_bd_installs_name_one_tracker(self):
        for tracker in inst.TRACKERS:
            for target in inst.TARGETS:
                for rel in self.package.skill:
                    if mixed_by_design(rel):
                        continue
                    text = self.renderer.skill_file(rel, tracker).value.decode("utf-8")
                    self.assertEqual(other_tracker_mentions(text, tracker), [], f"{tracker} render of {rel}")
                for name in self.package.agents[target]:
                    text = self.renderer.agent_file(target, name, tracker).value.decode("utf-8")
                    self.assertEqual(other_tracker_mentions(text, tracker), [], f"{tracker} .{target}/agents/{name}")

    def test_both_gates_render_the_selected_tracker(self):
        for tracker in inst.TRACKERS:
            for target in inst.TARGETS:
                for name in ("anchor-plan-review.md", "anchor-sprint-review.md"):
                    with self.subTest(tracker=tracker, target=target, agent=name):
                        text = self.renderer.agent_file(target, name, tracker).value.decode("utf-8")
                        self.assertIn(f"`anchor_tracker` (string, optional): `{tracker}`, as the parent", text)
                        self.assertIn(f"or the resolved tracker is not `{tracker}` (this install is rendered for `{tracker}`", text)
                        self.assertIn('"$ANCHOR_TRACKER" show "$qb" --json', text)
                        self.assertIn('--item-file "$', text)
                        self.assertNotIn("PREREQ.TRACKER", text)

    def test_tracker_command_forms(self):
        br = self.renderer.skill_file("references/bead-layout.md", "br").value.decode("utf-8")
        bd = self.renderer.skill_file("references/bead-layout.md", "bd").value.decode("utf-8")
        self.assertIn("br create", br)
        self.assertIn("br update", br)
        self.assertIn("bd create", bd)
        for text in (br, bd):
            self.assertNotIn("bd init", text.replace("never run `bd init`", ""))

    def test_planted_negatives(self):
        self.assertTrue(other_tracker_mentions("run `bd show pa-1`\n", "br"))
        self.assertTrue(other_tracker_mentions("use bd here\n", "br"))
        self.assertTrue(other_tracker_mentions("run br ready\n", "bd"))
        self.assertTrue(other_tracker_mentions("the gate requires bd and a Dolt-backed `.beads/`\n", "br"))
        self.assertTrue(other_tracker_mentions("the item is bd-42\n", "br"))
        self.assertTrue(other_tracker_mentions("the item is br-42\n", "bd"))
        self.assertEqual(other_tracker_mentions("IDs look like ex-42 in scripts/bd_x.py and .beads/\n", "br"), [])
        self.assertTrue(mixed_by_design("scripts/jev_judge.py"))
        self.assertFalse(mixed_by_design("references/jev-api.md"))
        self.assertFalse(mixed_by_design("assets/schemas/anchor-tuning-request.schema.json"))
        # A drifted committed file is caught by the neutral comparison.
        rel = "references/bead-layout.md"
        text = self.render(TEMPLATES / "skills" / "plan-anchoring" / f"{rel}.j2", "neutral")
        self.assertNotEqual(text + "drift\n", (SKILL / rel).read_text(encoding="utf-8"))
        # Strict rendering refuses an undeclared variable.
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.md.j2"
            bad.write_text("---\nname: bad\nversion: 1.0.0\nformat: markdown\nrequired_variables:\n  - tracker\n---\n"
                           "{{ tracker }} {{ nope }}\n", encoding="utf-8")
            out = inst.render_template(self.sc, bad, "br", VERSION)
            self.assertIsInstance(out, inst.Err)
            self.assertEqual(out.error.code, "RENDER.FAILED")


# ---------------------------------------------------------------- generated data


class GeneratedDataTests(unittest.TestCase):
    def setUp(self):
        if not _has_commit(gen.BASE):
            self.skipTest(f"history commit {gen.BASE} absent (shallow clone); CI checks out with fetch-depth 0")

    def test_manifest_and_legacy_are_in_sync(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(gen.main(["--check"]), 0, err.getvalue())

    def test_stale_manifest_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "manifest.json"
            data = json.loads(gen.MANIFEST.read_text(encoding="utf-8"))
            data["skill"].remove("SKILL.md")
            stale.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(gen, "MANIFEST", stale), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gen.main(["--check"]), 1)

    def test_legacy_lacking_history_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "legacy.json"
            data = json.loads(gen.LEGACY.read_text(encoding="utf-8"))
            del data["agents"]["claude"]["anchor-question-tune.md"]
            stale.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(gen, "LEGACY", stale), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gen.main(["--check"]), 1)

    def test_legacy_covers_retired_files(self):
        legacy = json.loads(gen.LEGACY.read_text(encoding="utf-8"))
        self.assertIn("anchor-question-tune.md", legacy["agents"]["claude"])
        self.assertIn("tests/test_jev_judge.py", legacy["skill"])
        self.assertNotIn("registry.yaml", legacy["agents"]["claude"])
        manifest = json.loads(gen.MANIFEST.read_text(encoding="utf-8"))
        self.assertNotIn("anchor-question-tune.md", manifest["agents"]["claude"])
        self.assertFalse([p for p in manifest["skill"] if p.startswith("tests/")])


# ---------------------------------------------------------------- install


@needs_wheel
class InstallTests(unittest.TestCase):
    def ok(self, result):
        self.assertIsInstance(result, inst.Ok, getattr(result, "error", None) and result.error.to_json())
        return result.value

    def refused(self, result, code):
        self.assertIsInstance(result, inst.Err, result)
        self.assertEqual(result.error.code, code, result.error.to_json())
        return result.error

    def lock(self, repo):
        return json.loads(repo.path(inst.LOCK_RELPATH).read_text(encoding="utf-8"))

    def tracker_setting(self, repo):
        lines = repo.path(".sc/plan-anchor/settings.yaml").read_text(encoding="utf-8").splitlines()
        return next(line for line in lines if line.startswith("anchor_tracker:"))

    def remote_setting(self, repo):
        lines = repo.path(".sc/plan-anchor/settings.yaml").read_text(encoding="utf-8").splitlines()
        return [line for line in lines if line.startswith("allow_remote_judge:")]

    def assert_installed(self, repo, tracker, targets):
        lock = self.lock(repo)
        self.assertEqual((lock["version"], lock["tracker"], lock["targets"]), (VERSION, tracker, list(targets)))
        for key, digest in lock["files"].items():
            self.assertEqual(sha(repo.path(key).read_bytes()), digest, key)
        manifest = json.loads((PLUGIN / "install" / "manifest.json").read_text(encoding="utf-8"))
        for target in targets:
            for rel in manifest["skill"]:
                self.assertIn(f".{target}/skills/plan-anchoring/{rel}", lock["files"])
            for name in manifest["agents"][target]:
                self.assertIn(f".{target}/agents/{name}", lock["files"])
        self.assertEqual(self.tracker_setting(repo), f"anchor_tracker: {tracker}")
        layout = repo.path(".claude/skills/plan-anchoring/references/bead-layout.md").read_text(encoding="utf-8")
        self.assertIn(f"{tracker} create", layout)

    def test_fresh_install_br(self):
        repo = TempRepo(self, beads="sqlite")
        data = self.ok(run_install(repo))
        self.assertEqual((data["tracker"], data["tracker_origin"], data["switched"]), ("br", "detected", False))
        self.assert_installed(repo, "br", ["claude"])
        self.assertIn(".claude/", data["commit_paths"])
        self.assertTrue(os.access(repo.path(".claude/skills/plan-anchoring/scripts/jev_judge.py"), os.X_OK)
                        or os.name == "nt")

    def test_fresh_install_bd_all_targets(self):
        repo = TempRepo(self, beads="dolt")
        data = self.ok(run_install(repo, targets=("claude", "codex", "cursor")))
        self.assertEqual(data["tracker"], "bd")
        self.assert_installed(repo, "bd", ["claude", "codex", "cursor"])
        self.assertTrue(repo.path(".cursor/agents/anchor-tuning.md").is_file())
        self.assertFalse(repo.path(".claude/agents/registry.yaml").exists())

    def test_rerun_is_idempotent(self):
        repo = TempRepo(self, beads="sqlite")
        self.ok(run_install(repo))
        before = repo.snapshot()
        data = self.ok(run_install(repo))
        plan = data["plan"]
        self.assertEqual((plan["create"], plan["replace"], plan["remove"], plan["backup"]), ([], [], [], []))
        self.assertIsNone(plan["settings"])
        self.assertEqual(data["commit_paths"], [])
        self.assertEqual(repo.snapshot(), before)

    def test_upgrade_removes_retired_files_and_keeps_others(self):
        repo = TempRepo(self, beads="sqlite")
        self.ok(run_install(repo))
        lock = self.lock(repo)
        retired = {".claude/agents/anchor-question-tune.md": b"old agent\n",
                   ".claude/skills/plan-anchoring/tests/test_jev_judge.py": b"old test\n"}
        for key, data in retired.items():
            repo.path(key).parent.mkdir(parents=True, exist_ok=True)
            repo.path(key).write_bytes(data)
            lock["files"][key] = sha(data)
        (repo.path(".claude/skills/plan-anchoring/tests/__pycache__")).mkdir()
        repo.path(".claude/skills/plan-anchoring/tests/__pycache__/x.pyc").write_bytes(b"\0")
        lock["version"] = "0.6.0"
        repo.path(inst.LOCK_RELPATH).write_text(json.dumps(lock), encoding="utf-8")
        repo.path(".claude/agents/mine.md").write_text("consumer agent\n", encoding="utf-8")
        data = self.ok(run_install(repo))
        self.assertEqual(data["previous_version"], "0.6.0")
        self.assertEqual(sorted(data["plan"]["remove"]), sorted(retired))
        for key in retired:
            self.assertFalse(repo.path(key).exists(), key)
        self.assertFalse(repo.path(".claude/skills/plan-anchoring/tests").exists())
        self.assertEqual(repo.path(".claude/agents/mine.md").read_text(encoding="utf-8"), "consumer agent\n")
        self.assertNotIn(".claude/agents/anchor-question-tune.md", self.lock(repo)["files"])

    def test_modified_file_is_refused_then_backed_up_with_overwrite(self):
        repo = TempRepo(self, beads="sqlite")
        self.ok(run_install(repo))
        key = ".claude/agents/anchor-tuning.md"
        repo.path(key).write_text("local edit\n", encoding="utf-8")
        before = repo.snapshot()
        error = self.refused(run_install(repo), "INSTALL.CONFLICT")
        self.assertEqual([(p["code"], p["path"]) for p in error.data["problems"]], [("FILE.MODIFIED", key)])
        self.assertIn(key, error.message)
        self.assertEqual(repo.snapshot(), before)
        data = self.ok(run_install(repo, overwrite=True))
        self.assertEqual(data["plan"]["backup"], [key])
        backups = list(repo.path(".backup").glob(f"*/{key}"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "local edit\n")
        self.assertEqual(sha(repo.path(key).read_bytes()), self.lock(repo)["files"][key])

    def test_modified_retired_file_is_refused(self):
        repo = TempRepo(self, beads="sqlite")
        self.ok(run_install(repo))
        lock = self.lock(repo)
        key = ".claude/agents/anchor-question-tune.md"
        lock["files"][key] = sha(b"shipped\n")
        repo.path(inst.LOCK_RELPATH).write_text(json.dumps(lock), encoding="utf-8")
        repo.path(key).write_text("edited\n", encoding="utf-8")
        error = self.refused(run_install(repo), "INSTALL.CONFLICT")
        self.assertEqual(error.data["problems"][0]["code"], "FILE.MODIFIED_RETIRED")
        self.assertTrue(repo.path(key).exists())

    def test_unowned_file_is_never_overwritten(self):
        repo = TempRepo(self, beads="sqlite")
        key = ".claude/agents/anchor-tuning.md"
        repo.path(key).parent.mkdir(parents=True)
        repo.path(key).write_text("someone else's agent\n", encoding="utf-8")
        error = self.refused(run_install(repo), "INSTALL.CONFLICT")
        self.assertEqual([(p["code"], p["path"]) for p in error.data["problems"]], [("FILE.UNOWNED", key)])
        self.assertEqual(sorted(repo.snapshot()), [".beads/metadata.json", key])

    def test_foreign_skill_directory_is_refused(self):
        repo = TempRepo(self, beads="sqlite")
        repo.path(".claude/skills/plan-anchoring").mkdir(parents=True)
        repo.path(".claude/skills/plan-anchoring/SKILL.md").write_text("another skill\n", encoding="utf-8")
        error = self.refused(run_install(repo), "INSTALL.CONFLICT")
        self.assertEqual(error.data["problems"][0]["code"], "SKILL.FOREIGN_DIR")

    def test_switch_br_to_bd_with_dolt(self):
        repo = TempRepo(self, beads="sqlite")
        self.ok(run_install(repo, targets=("claude", "codex")))
        repo.beads("dolt")
        error = self.refused(run_install(repo), "TRACKER.MISMATCH")
        self.assertIn("--tracker bd", error.action)
        data = self.ok(run_install(repo, tracker="bd", targets=("claude",)))
        self.assertTrue(data["switched"])
        self.assertEqual((data["previous_tracker"], data["tracker"]), ("br", "bd"))
        self.assertEqual(data["targets"], ["claude", "codex"])  # every locked target is re-rendered
        self.assertEqual(data["plan"]["settings"], {"path": ".sc/plan-anchor/settings.yaml", "from": "br", "to": "bd"})
        self.assertTrue(any("does not migrate issue data" in n for n in data["notes"]))
        self.assert_installed(repo, "bd", ["claude", "codex"])
        sprint = repo.path(".codex/agents/anchor-sprint-review.md").read_text(encoding="utf-8")
        self.assertIn("this install is rendered for `bd`", sprint)

    def test_switch_bd_to_br(self):
        repo = TempRepo(self, beads="dolt")
        self.ok(run_install(repo))
        repo.beads("sqlite")
        data = self.ok(run_install(repo, tracker="br"))
        self.assertTrue(data["switched"])
        self.assert_installed(repo, "br", ["claude"])
        sprint = repo.path(".claude/agents/anchor-sprint-review.md").read_text(encoding="utf-8")
        self.assertIn("this install is rendered for `br`", sprint)

    def test_switch_to_br_without_beads_needs_init_flag(self):
        repo = TempRepo(self, beads="dolt")
        self.ok(run_install(repo))
        repo.beads(None)
        self.refused(run_install(repo, tracker="br"), "TRACKER.NOT_INITIALIZED")
        run = FakeRun()
        self.ok(run_install(repo, tracker="br", init_br=True, run=run))
        self.assertEqual(run.calls, [["/fake/bin/br", "init"]])

    def test_bd_refused_without_dolt(self):
        for backend in ("sqlite", None):
            repo = TempRepo(self, beads=backend)
            result = run_install(repo, tracker="bd", init_br=True)
            error = self.refused(result, "TRACKER.DOLT_REQUIRED")
            self.assertIn("--tracker br", error.action)
            self.assertNotIn("bd init", error.message + error.action)
            self.assertFalse(repo.path(".claude").exists())
            self.assertFalse(repo.path(".beads").exists() and backend is None)

    def test_no_beads_without_init_flag_is_typed_error(self):
        repo = TempRepo(self)
        run = FakeRun()
        error = self.refused(run_install(repo, run=run), "TRACKER.NOT_INITIALIZED")
        self.assertIn("--init-br", error.action)
        self.assertNotIn("bd init", error.message + error.action)
        self.assertEqual(run.calls, [])
        self.assertEqual(repo.snapshot(), {})
        data = self.ok(run_install(repo, init_br=True, run=run))
        self.assertTrue(data["plan"]["br_init"])
        self.assertEqual(run.calls, [["/fake/bin/br", "init"]])
        self.assertIn(".beads/", data["commit_paths"])

    def test_missing_cli_is_typed_error(self):
        repo = TempRepo(self, beads="dolt")
        result = inst.install(inst.Options(dest=repo.root, tracker=None, targets=["claude"]), which=lambda n: None)
        self.refused(result, "TRACKER.CLI_MISSING")

    def test_dry_run_writes_nothing(self):
        repo = TempRepo(self)
        run = FakeRun()
        data = self.ok(run_install(repo, init_br=True, dry_run=True, run=run))
        self.assertTrue(data["dry_run"])
        self.assertTrue(data["plan"]["create"])
        self.assertTrue(data["plan"]["br_init"])
        self.assertEqual(run.calls, [])
        self.assertEqual(repo.snapshot(), {})
        repo2 = TempRepo(self, beads="sqlite")
        self.ok(run_install(repo2))
        repo2.beads("dolt")
        before = repo2.snapshot()
        data = self.ok(run_install(repo2, tracker="bd", dry_run=True))
        self.assertTrue(data["switched"])
        self.assertTrue(data["plan"]["replace"])
        self.assertEqual(repo2.snapshot(), before)

    def test_dest_must_be_repository_root(self):
        repo = TempRepo(self, beads="sqlite")
        repo.path("sub").mkdir()
        result = inst.install(inst.Options(dest=repo.path("sub"), tracker=None, targets=["claude"]), which=fake_which)
        self.refused(result, "INSTALL.DEST")

    def test_invalid_lock_is_typed_error(self):
        repo = TempRepo(self, beads="sqlite")
        repo.path(".sc/plan-anchor").mkdir(parents=True)
        repo.path(inst.LOCK_RELPATH).write_text("{not json", encoding="utf-8")
        self.refused(run_install(repo), "INSTALL.LOCK_INVALID")

    def test_missing_sc_compose_is_typed_error(self):
        repo = TempRepo(self, beads="sqlite")
        real = importlib.import_module

        def fake(name, *a, **k):
            if name == "sc_compose":
                raise ImportError("No module named 'sc_compose'")
            return real(name, *a, **k)

        with mock.patch.object(inst.importlib, "import_module", side_effect=fake):
            error = self.refused(run_install(repo), "DEPENDENCY.SC_COMPOSE")
        self.assertIn("uv run", error.action)
        self.assertEqual(repo.snapshot(), {".beads/metadata.json": b'{"backend": "sqlite"}'})

    def test_cli_envelope_and_exit_codes(self):
        repo = TempRepo(self, beads="sqlite")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = inst.main(["--dest", str(repo.root), "--dry-run"], which=fake_which)
        envelope = json.loads(out.getvalue())
        self.assertEqual((code, envelope["success"], envelope["error"]), (0, True, None))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = inst.main(["--dest", str(repo.root), "--target", "vim"], which=fake_which)
        envelope = json.loads(out.getvalue())
        self.assertEqual((code, envelope["error"]["code"]), (2, "VALIDATION.INPUT"))
        out = io.StringIO()
        with mock.patch.object(inst, "install", side_effect=RuntimeError("boom")), contextlib.redirect_stdout(out):
            code = inst.main(["--dest", str(repo.root)], which=fake_which)
        envelope = json.loads(out.getvalue())
        self.assertEqual((code, envelope["success"], envelope["error"]["code"]), (2, False, "SCRIPT.INTERNAL"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = inst.main(["--dest", str(repo.root), "--tracker", "bd"], which=fake_which)
        self.assertEqual((code, json.loads(out.getvalue())["error"]["code"]), (2, "TRACKER.DOLT_REQUIRED"))

    def test_remote_judge_flags_write_the_setting_and_reruns_keep_it(self):
        repo = TempRepo(self, beads="sqlite")
        data = self.ok(run_install(repo))
        self.assertEqual((data["allow_remote_judge"], data["plan"]["allow_remote_judge"]), (None, None))
        self.assertEqual(self.remote_setting(repo), [])
        self.assertTrue(any("does not set allow_remote_judge" in n for n in data["notes"]))
        data = self.ok(run_install(repo, allow_remote_judge=True))
        self.assertEqual(data["plan"]["allow_remote_judge"],
                         {"path": ".sc/plan-anchor/settings.yaml", "from": None, "to": True})
        self.assertIn(".sc/plan-anchor/settings.yaml", data["commit_paths"])
        self.assertEqual(self.remote_setting(repo), ["allow_remote_judge: true"])
        self.assertEqual(self.tracker_setting(repo), "anchor_tracker: br")
        before = repo.snapshot()
        data = self.ok(run_install(repo))  # no flag: the recorded answer is kept, nothing is rewritten
        self.assertEqual((data["allow_remote_judge"], data["plan"]["allow_remote_judge"], data["commit_paths"]), (True, None, []))
        self.assertEqual(repo.snapshot(), before)
        data = self.ok(run_install(repo, allow_remote_judge=False))
        self.assertEqual(data["plan"]["allow_remote_judge"]["to"], False)
        self.assertEqual(self.remote_setting(repo), ["allow_remote_judge: false"])
        self.ok(run_install(repo, tracker="br"))  # a rerun that rewrites nothing else still keeps it
        self.assertEqual(self.remote_setting(repo), ["allow_remote_judge: false"])

    def test_switching_tracker_keeps_the_remote_judge_answer(self):
        repo = TempRepo(self, beads="sqlite")
        self.ok(run_install(repo, allow_remote_judge=True))
        repo.beads("dolt")
        data = self.ok(run_install(repo, tracker="bd"))
        self.assertTrue(data["switched"])
        self.assertEqual((self.tracker_setting(repo), self.remote_setting(repo)),
                         ("anchor_tracker: bd", ["allow_remote_judge: true"]))

    def test_remote_judge_dry_run_writes_nothing(self):
        repo = TempRepo(self, beads="sqlite")
        data = self.ok(run_install(repo, allow_remote_judge=True, dry_run=True))
        self.assertEqual(data["plan"]["allow_remote_judge"]["to"], True)
        self.assertFalse(repo.path(".sc/plan-anchor/settings.yaml").exists())

    def test_remote_judge_cli_flags(self):
        repo = TempRepo(self, beads="sqlite")
        for argv, expected in ((["--allow-remote-judge"], ["allow_remote_judge: true"]),
                               (["--no-remote-judge"], ["allow_remote_judge: false"]),
                               ([], ["allow_remote_judge: false"])):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = inst.main(["--dest", str(repo.root), *argv], which=fake_which, run=FakeRun())
            self.assertEqual(code, 0, out.getvalue())
            self.assertEqual(self.remote_setting(repo), expected)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = inst.main(["--dest", str(repo.root), "--allow-remote-judge", "--no-remote-judge"], which=fake_which)
        self.assertEqual((code, json.loads(out.getvalue())["error"]["code"]), (2, "VALIDATION.INPUT"))
        self.assertEqual(self.remote_setting(repo), ["allow_remote_judge: false"])

    def test_target_dot_form_is_accepted(self):
        self.assertEqual(inst._targets(".claude,codex"), ["claude", "codex"])


# ---------------------------------------------------------------- history fixtures


HISTORY = {
    "0.3.0": "7d2d839",   # pre-plugin layout: skills/.claude/...
    "0.4.0": "94c3215",   # ships anchor-question-tune.md and tests/
    "0.4.2": "8b33dd9",   # released from a commit no branch here contains
    "0.6.0": "79dd7a0",
    "0.6.1": "eba5b5a",
}
FIXTURE_LAYOUTS = (
    (re.compile(r"^skills/\.claude/skills/plan-anchoring/(.+)$"), ".claude/skills/plan-anchoring/{}"),
    (re.compile(r"^plugins/sc-plan-anchor/skills/plan-anchoring/(.+)$"), ".claude/skills/plan-anchoring/{}"),
    (re.compile(r"^skills/\.claude/agents/(anchor-[^/]+\.md)$"), ".claude/agents/{}"),
    (re.compile(r"^plugins/sc-plan-anchor/\.claude/agents/(anchor-[^/]+\.md)$"), ".claude/agents/{}"),
)


def vendor_from_history(commit, root):
    """Copy what a consumer vendored at ``commit`` (skill + .claude agents) into ``root``."""
    placed = {}
    for path in _git("ls-tree", "-r", "--name-only", commit).decode().splitlines():
        for pattern, dest in FIXTURE_LAYOUTS:
            m = pattern.match(path)
            if m:
                key = dest.format(m.group(1))
                data = _git("show", f"{commit}:{path}")
                (root / key).parent.mkdir(parents=True, exist_ok=True)
                (root / key).write_bytes(data)
                placed[key] = data
                break
    return placed


@needs_wheel
class HistoryMigrationTests(unittest.TestCase):
    def migrate(self, label):
        commit = HISTORY[label]
        if not _has_commit(commit):
            self.skipTest(f"{label} commit {commit} is not in this clone (it is on no branch; CI cannot fetch it)")
        repo = TempRepo(self, beads="dolt")
        placed = vendor_from_history(commit, repo.root)
        self.assertTrue(placed)
        registry = repo.path(".claude/agents/registry.yaml")
        registry.write_text("consumer: registry\n", encoding="utf-8")
        result = run_install(repo, tracker="bd")
        self.assertIsInstance(result, inst.Ok, getattr(result, "error", None) and result.error.to_json())
        data = result.value
        self.assertTrue(data["migration"])
        lock = json.loads(repo.path(inst.LOCK_RELPATH).read_text(encoding="utf-8"))
        installed = {p.relative_to(repo.root).as_posix() for p in repo.root.rglob("*")
                     if p.is_file() and p.relative_to(repo.root).parts[0] == ".claude"}
        self.assertEqual(installed, set(lock["files"]) | {".claude/agents/registry.yaml"}, label)
        for key in placed:
            if key not in lock["files"]:
                self.assertIn(key, data["plan"]["remove"], key)
        self.assertEqual(data["warnings"], [])
        self.assertEqual(registry.read_text(encoding="utf-8"), "consumer: registry\n")
        rerun = run_install(repo).value
        self.assertEqual((rerun["plan"]["create"], rerun["plan"]["replace"], rerun["plan"]["remove"]), ([], [], []))
        return data

    def test_migrate_0_3_0(self):
        self.migrate("0.3.0")

    def test_migrate_0_4_0_removes_retired_agent_and_tests(self):
        data = self.migrate("0.4.0")
        self.assertIn(".claude/agents/anchor-question-tune.md", data["plan"]["remove"])
        self.assertIn(".claude/skills/plan-anchoring/tests/test_jev_judge.py", data["plan"]["remove"])

    def test_migrate_0_4_2(self):
        data = self.migrate("0.4.2")
        self.assertTrue([k for k in data["plan"]["remove"] if "/tests/" in k])

    def test_migrate_0_6_0_removes_plan_source(self):
        data = self.migrate("0.6.0")
        self.assertTrue(data["plan"]["replace"])
        # ADR-014: the gates take the caller's sprint text; plan_source.py is no longer shipped.
        self.assertIn(".claude/skills/plan-anchoring/scripts/plan_source.py", data["plan"]["remove"])
        self.assertIn(".claude/skills/plan-anchoring/references/plan-source-contract.md", data["plan"]["remove"])

    def test_migrate_0_6_1(self):
        data = self.migrate("0.6.1")
        self.assertIn(".claude/skills/plan-anchoring/scripts/plan_source.py", data["plan"]["remove"])

    def test_edited_legacy_file_is_not_owned(self):
        commit = HISTORY["0.4.0"]
        if not _has_commit(commit):
            self.skipTest(f"0.4.0 commit {commit} is not in this clone")
        repo = TempRepo(self, beads="dolt")
        vendor_from_history(commit, repo.root)
        retired = repo.path(".claude/agents/anchor-question-tune.md")
        retired.write_text(retired.read_text(encoding="utf-8") + "local edit\n", encoding="utf-8")
        edited = repo.path(".claude/agents/anchor-tuning.md")
        edited.write_text(edited.read_text(encoding="utf-8") + "local edit\n", encoding="utf-8")
        result = run_install(repo, tracker="bd")
        self.assertIsInstance(result, inst.Err)
        self.assertEqual([(p["code"], p["path"]) for p in result.error.data["problems"]],
                         [("FILE.UNOWNED", ".claude/agents/anchor-tuning.md")])
        edited.write_text("restored by hand\n", encoding="utf-8")
        data = run_install(repo, tracker="bd", overwrite=True).value
        self.assertIn(".claude/agents/anchor-question-tune.md", data["plan"]["backup"])
        self.assertFalse(retired.exists())


if __name__ == "__main__":
    unittest.main()
