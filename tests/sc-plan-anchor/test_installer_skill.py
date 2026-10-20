"""The plan-anchor-installer plugin: destinations, parent-folder installs, the hook, --status, upgrades.

The marketplace plugin ships one skill, ``plan-anchor-installer``, which runs
install.py into any folder except a global harness location. Gates trust the
nearest per-folder install walking up from the working directory (stopping
before the home directory) and use the nearest settings file. A SessionStart
hook prints one line when the nearest install is older than the plugin.

Tests that render need the sc-compose wheel and skip without it, unless
PLAN_ANCHOR_REQUIRE_SC_COMPOSE=1 (CI's installer job). No test calls Jev;
TYPESAFE_API_KEY is removed from every child environment.
"""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

from layout_support import PLUGIN, SCRIPTS, TARGETS
from test_install import (FakeRun, TempRepo, VERSION, _git, _has_commit, fake_which, inst, mixed_by_design,
                          needs_wheel, other_tracker_mentions, sha)

sys.path.insert(0, str(SCRIPTS))
import plan_anchor_paths as paths  # noqa: E402

HOOK = PLUGIN / "hooks" / "check_install.py"
INSTALLER_SKILL = PLUGIN / "skills" / "plan-anchor-installer" / "SKILL.md"
RELEASE_0_7_3 = "656bb30"  # feat/no-plugin-env-vars (PR #38): the last release with the marketplace layout
ERROR_KEYS = {"code", "message", "recoverable", "suggested_action"}


def child_env(home=None, path_prefix=None):
    environment = {k: v for k, v in os.environ.items() if k != "TYPESAFE_API_KEY"}
    if home is not None:
        environment["HOME"] = environment["USERPROFILE"] = str(home)
    if path_prefix is not None:
        environment["PATH"] = str(path_prefix) + os.pathsep + environment.get("PATH", "")
    return environment


@contextlib.contextmanager
def fake_home(home):
    """os.path.expanduser('~') answers ``home`` in this process (HOME on POSIX, USERPROFILE on Windows)."""
    with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
        yield


def call_main(argv, **kw):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = inst.main(argv, which=fake_which, run=kw.pop("run", FakeRun()), **kw)
    return code, json.loads(out.getvalue())


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}


def git_repo(path, backend=None, settings=None):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if backend is not None:
        (path / ".beads").mkdir()
        (path / ".beads" / "metadata.json").write_text(json.dumps({"backend": backend}), encoding="utf-8")
    if settings is not None:
        (path / ".sc" / "plan-anchor").mkdir(parents=True)
        (path / ".sc" / "plan-anchor" / "settings.yaml").write_text(settings, encoding="utf-8")
    return path


def installed_tracker(folder):
    """The anchor_tracker module of the install in ``folder`` (its .claude copy).

    Each install is rendered for one tracker, so the parent's br copy is imported
    on its own, without disturbing the modules the suite already loaded from SCRIPTS.
    """
    scripts = str(Path(folder) / ".claude" / "skills" / "plan-anchoring" / "scripts")
    names = ("result", "plan_anchor_paths", "plan_anchor_settings", "anchor_tracker")
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    sys.path.insert(0, scripts)
    try:
        import importlib
        return importlib.import_module("anchor_tracker")
    finally:
        sys.path.remove(scripts)
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def write_lock(folder, version, tracker_name="br", targets=("claude",)):
    lock = Path(folder) / ".sc" / "plan-anchor" / "install-lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"package": "sc-plan-anchor", "version": version, "tracker": tracker_name,
                                "targets": list(targets), "files": {}}), encoding="utf-8")
    return lock


class Scratch(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()


# ---------------------------------------------------------------- destinations


class GlobalDestinationTests(Scratch):
    """--dest refuses only global locations, with a typed error and exit 2; nothing is written."""

    def global_dests(self):
        for rel in ("", ".claude", ".codex", ".cursor", ".agents", ".claude/skills",
                    ".claude/plugins/cache/plan-anchor/sc-plan-anchor/0.8.0", ".codex/plugins/cache/x"):
            dest = self.home / rel
            dest.mkdir(parents=True, exist_ok=True)
            yield rel or "~", dest

    def test_global_destinations_are_refused_with_exit_two(self):
        for label, dest in self.global_dests():
            before = tree(self.home)
            with self.subTest(dest=label), fake_home(self.home):
                code, out = call_main(["--dest", str(dest), "--tracker", "br", "--no-remote-judge",
                                       "--target", "claude,codex,cursor"])
                self.assertEqual((code, out["success"]), (2, False), out)
                self.assertEqual(set(out["error"]), ERROR_KEYS)
                self.assertEqual(out["error"]["code"], "INSTALL.DEST_GLOBAL")
                self.assertEqual(out["data"], {"dest": str(dest.resolve())})
                self.assertEqual(tree(self.home), before)  # nothing written
                code, out = call_main(["--dest", str(dest), "--status"])
                self.assertEqual((code, out["error"]["code"]), (2, "INSTALL.DEST_GLOBAL"))

    def test_the_plugin_directory_is_refused(self):
        code, out = call_main(["--dest", str(PLUGIN), "--tracker", "br", "--dry-run"])
        self.assertEqual((code, out["error"]["code"]), (2, "INSTALL.DEST_GLOBAL"))
        self.assertIn("inside the plugin directory", out["error"]["message"])

    def test_refusal_through_the_real_process(self):
        dest = self.home / ".claude"
        dest.mkdir()
        proc = subprocess.run([sys.executable, str(PLUGIN / "install.py"), "--dest", str(dest), "--tracker", "br"],
                              env=child_env(self.home), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertEqual((envelope["success"], envelope["error"]["code"]), (False, "INSTALL.DEST_GLOBAL"))
        self.assertEqual(list(dest.iterdir()), [])

    def test_a_folder_under_home_is_not_global(self):
        with fake_home(self.home):
            for rel in ("work", "work/repo", "src/.claude-notes"):
                with self.subTest(rel=rel):
                    self.assertIsNone(paths.global_location(self.home / rel))
            for rel in (".claude", ".codex/skills", ".cursor/plugins", ".agents/skills/x"):
                with self.subTest(rel=rel):
                    self.assertIsNotNone(paths.global_location(self.home / rel))
            self.assertIsNotNone(paths.global_location(self.home))


# ---------------------------------------------------------------- parent folder


@needs_wheel
class ParentFolderInstallTests(Scratch):
    """One install in a non-git parent folder serves child repositories; each keeps its own tracker data."""

    def setUp(self):
        super().setUp()
        self.parent = self.home / "work"            # not a repository, no .beads/
        self.parent.mkdir()
        self.br_child = git_repo(self.parent / "svc-br", backend="sqlite")
        self.bd_child = git_repo(self.parent / "svc-bd", backend="dolt",
                                 settings="schema_version: 1\nanchor_tracker: bd\n")
        self.mismatch = git_repo(self.parent / "svc-dolt-inherits-br", backend="dolt")
        (self.br_child / "src").mkdir()
        with fake_home(self.home):
            code, out = call_main(["--dest", str(self.parent), "--tracker", "br", "--no-remote-judge",
                                   "--target", "claude,codex,cursor"])
        self.assertEqual(code, 0, out)
        self.data = out["data"]

    def test_install_writes_the_parent_and_no_child(self):
        self.assertFalse(self.data["repository"])
        self.assertEqual((self.data["tracker"], self.data["targets"]), ("br", list(TARGETS)))
        self.assertTrue(any("is not a repository" in n for n in self.data["notes"]), self.data["notes"])
        for target in TARGETS:
            self.assertTrue((self.parent / f".{target}" / "skills" / "plan-anchoring" / "SKILL.md").is_file())
        for child in (self.br_child, self.bd_child, self.mismatch):
            self.assertFalse((child / ".claude").exists())
        self.assertFalse((self.br_child / ".sc").exists())

    def test_trust_lookup_finds_the_parent_copy_from_each_child(self):
        with fake_home(self.home):
            for child in (self.br_child / "src", self.bd_child):
                with self.subTest(child=child.name):
                    root, copies = paths.find_installs(child)
                    self.assertEqual(root, self.parent)
                    self.assertEqual(sorted(c.parent.parent.parent.parent.name for c in copies),
                                     [".claude", ".codex", ".cursor"])
        for child, cwd in ((self.br_child, self.br_child / "src"), (self.bd_child, self.bd_child)):
            anchors = child / "anchors.json"
            anchors.write_text(json.dumps({"schema": "plan-anchoring/anchors/1", "plan": "p", "intent_ref": "i.md",
                                           "anchors": []}), encoding="utf-8")
            script = self.parent / ".codex" / "skills" / "plan-anchoring" / "scripts" / "jev_judge.py"
            proc = subprocess.run([sys.executable, str(script), "agent-preflight", "--workspace-root", str(child),
                                   "--script", str(script), "--anchors", str(anchors)], cwd=str(cwd),
                                  env=child_env(self.home), capture_output=True, text=True, encoding="utf-8")
            with self.subTest(child=child.name):
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertTrue(json.loads(proc.stdout)["success"])

    def test_settings_lookup_picks_the_nearest_file(self):
        # The parent's install is rendered for br, so a child with its own file is a br child here;
        # the bd child's own file is still the nearest, and the br copy refuses it instead of using the parent's.
        installed = installed_tracker(self.parent)
        br_own = git_repo(self.parent / "svc-br-own", backend="sqlite", settings="schema_version: 1\nanchor_tracker: br\n")
        with fake_home(self.home):
            br = installed.resolve(self.br_child / "src", which=fake_which)
            mine = installed.resolve(br_own, which=fake_which)
            bd = installed.resolve(self.bd_child, which=fake_which)
        self.assertTrue(br.ok and mine.ok, (br, mine))
        parent_settings = self.parent / ".sc" / "plan-anchor" / "settings.yaml"
        self.assertEqual((br.value.tracker, br.value.settings_file), ("br", parent_settings))
        self.assertTrue(br.value.to_json()["settings_inherited"])
        self.assertIs(br.value.settings.allow_remote_judge, False)  # the parent's answer applies
        own = br_own / ".sc" / "plan-anchor" / "settings.yaml"
        self.assertEqual((mine.value.tracker, mine.value.settings_file), ("br", own))
        self.assertFalse(mine.value.to_json()["settings_inherited"])
        self.assertIsNone(mine.value.settings.allow_remote_judge)  # files are not merged: nearest wins whole
        self.assertFalse(bd.ok)
        self.assertEqual(bd.error.code, "SETTINGS.INVALID_TRACKER")
        # its own file (shown relative, as every repository's own file is), not the parent's
        self.assertTrue(bd.error.message.startswith(".sc/plan-anchor/settings.yaml anchor_tracker is 'bd'"),
                        bd.error.message)

    def test_br_setting_over_dolt_metadata_is_a_mismatch(self):
        installed = installed_tracker(self.parent)
        with fake_home(self.home):
            inherited = installed.resolve(self.mismatch, which=fake_which)
        self.assertFalse(inherited.ok)
        self.assertEqual(inherited.error.code, "TRACKER.MISMATCH")
        parent_settings = self.parent / ".sc" / "plan-anchor" / "settings.yaml"
        self.assertEqual(inherited.error.message,  # names the parent's file, the one in effect
                         f"{parent_settings} anchor_tracker selects br, but .beads/ is Dolt-backed; "
                         "this install is rendered for br")
        own = git_repo(self.parent / "svc-dolt-own-br", backend="dolt", settings="schema_version: 1\nanchor_tracker: br\n")
        with fake_home(self.home):
            explicit = installed.resolve(own, which=fake_which)
        self.assertEqual(explicit.error.code, "TRACKER.MISMATCH")
        self.assertTrue(explicit.error.message.startswith(".sc/plan-anchor/settings.yaml anchor_tracker selects br"))

    def test_rendered_files_name_only_their_tracker(self):
        checked = 0
        for path in sorted(self.parent.rglob("*")):
            rel = path.relative_to(self.parent).as_posix()
            if not path.is_file() or rel.split("/", 1)[0] not in {f".{t}" for t in TARGETS}:
                continue  # only what the installer wrote (child repositories hold test fixtures)
            skill_rel = rel.split("/skills/plan-anchoring/", 1)[-1]
            if mixed_by_design(skill_rel):
                continue
            with self.subTest(path=rel):
                self.assertEqual(other_tracker_mentions(path.read_text(encoding="utf-8"), "br"), [])
            checked += 1
        self.assertGreater(checked, 100)

    def test_a_child_install_overrides_the_parent(self):
        with fake_home(self.home):
            code, out = call_main(["--dest", str(self.bd_child), "--tracker", "bd", "--no-remote-judge"])
            self.assertEqual(code, 0, out)
            root, _ = paths.find_installs(self.bd_child)
            self.assertEqual(root, self.bd_child)
            self.assertEqual(paths.find_installs(self.br_child)[0], self.parent)
        sprint = (self.bd_child / ".claude" / "agents" / "anchor-sprint-review.md").read_text(encoding="utf-8")
        self.assertIn("this install is rendered for `bd`", sprint)

    def test_a_parent_folder_needs_a_tracker(self):
        bare = self.home / "other"
        bare.mkdir()
        with fake_home(self.home):
            code, out = call_main(["--dest", str(bare), "--no-remote-judge"])
        self.assertEqual((code, out["error"]["code"]), (2, "TRACKER.REQUIRED"))
        self.assertEqual(list(bare.iterdir()), [])


# ---------------------------------------------------------------- hook


class SessionStartHookTests(Scratch):
    def run_hook(self, cwd):
        proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"cwd": str(cwd), "hook_event_name": "SessionStart"}),
                              env=child_env(self.home), capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        return proc.stdout

    def folder(self):
        repo = self.home / "work" / "repo"
        (repo / "src").mkdir(parents=True)
        return repo

    def test_silent_without_a_lock(self):
        repo = self.folder()
        before = tree(self.tmp)
        self.assertEqual(self.run_hook(repo / "src"), "")
        self.assertEqual(tree(self.tmp), before)

    def test_silent_when_current_or_newer(self):
        repo = self.folder()
        for version in (VERSION, "99.0.0"):
            with self.subTest(version=version):
                write_lock(repo, version)
                before = tree(self.tmp)
                self.assertEqual(self.run_hook(repo / "src"), "")
                self.assertEqual(tree(self.tmp), before)

    def test_one_line_when_older(self):
        repo = self.folder()
        write_lock(repo.parent, "0.7.3")  # a parent-folder install covers the repository
        before = tree(self.tmp)
        out = self.run_hook(repo / "src")
        self.assertEqual(out, f"plan-anchor 0.7.3 installed, {VERSION} available: run plan-anchor-installer ({repo.parent})\n")
        self.assertEqual(tree(self.tmp), before)

    def test_nearest_lock_wins_and_the_walk_stops_before_home(self):
        repo = self.folder()
        write_lock(repo.parent, "0.7.3")
        write_lock(repo, VERSION)
        self.assertEqual(self.run_hook(repo / "src"), "")
        stray = self.home / "elsewhere"
        stray.mkdir()
        write_lock(self.home, "0.1.0")  # a lock in the home directory itself is never visited
        self.assertEqual(self.run_hook(stray), "")

    def test_unreadable_lock_or_input_is_silent(self):
        repo = self.folder()
        lock = write_lock(repo, "0.7.3")
        lock.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.run_hook(repo), "")
        proc = subprocess.run([sys.executable, str(HOOK)], input="not json", cwd=str(repo), env=child_env(self.home),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_registered_for_session_start_and_offline(self):
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        [entry] = hooks["hooks"]["SessionStart"]
        [command] = entry["hooks"]
        self.assertEqual(command["type"], "command")
        self.assertEqual(command["command"], 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/check_install.py"')
        source = HOOK.read_text(encoding="utf-8")
        for forbidden in ("urllib", "socket", "http", "write_text", "write_bytes", "open("):
            self.assertNotIn(forbidden, source)


# ---------------------------------------------------------------- --status


class StatusTests(Scratch):
    def status(self, dest):
        with fake_home(self.home):
            code, out = call_main(["--dest", str(dest), "--status"])
        self.assertEqual(code, 0, out)
        return out["data"]

    def test_states_and_message(self):
        repo = self.home / "work" / "repo"
        repo.mkdir(parents=True)
        data = self.status(repo)
        self.assertEqual((data["state"], data["installed_version"], data["installer_version"]),
                         ("not_installed", None, VERSION))
        write_lock(repo.parent, "0.7.3")
        data = self.status(repo)
        self.assertEqual(data["state"], "not_installed")
        self.assertEqual(data["covering_install"], {"root": str(repo.parent), "version": "0.7.3", "valid": True})
        write_lock(repo, "0.7.3")
        data = self.status(repo)
        self.assertEqual((data["state"], data["message"]), ("older", f"installed 0.7.3, installer {VERSION}"))
        write_lock(repo, VERSION)
        self.assertEqual(self.status(repo)["state"], "current")
        write_lock(repo, "99.0.0")
        self.assertEqual(self.status(repo)["state"], "newer")
        before = tree(self.tmp)
        self.status(repo)
        self.assertEqual(tree(self.tmp), before)

    def test_status_takes_only_dest(self):
        with fake_home(self.home):
            code, out = call_main(["--dest", str(self.home / "x"), "--status", "--tracker", "br"])
        self.assertEqual((code, out["error"]["code"]), (2, "VALIDATION.INPUT"))


# ---------------------------------------------------------------- the installer skill


class InstallerSkillTextTests(unittest.TestCase):
    def setUp(self):
        self.text = INSTALLER_SKILL.read_text(encoding="utf-8")

    def test_frontmatter(self):
        front = self.text.split("---\n")[1]
        self.assertIn("name: plan-anchor-installer\n", front)
        self.assertIn(f'version: "{VERSION}"', front)

    def test_runs_the_installer_from_the_plugin_directory(self):
        self.assertIn('uv run "${CLAUDE_PLUGIN_ROOT}/install.py" --dest <folder> --tracker br|bd', self.text)
        self.assertIn("--allow-remote-judge|--no-remote-judge", self.text)
        self.assertIn('uv run "${CLAUDE_PLUGIN_ROOT}/install.py" --dest <folder> --status', self.text)
        self.assertNotIn("../", self.text)

    def test_compares_versions_first_and_upgrades_by_rerunning(self):
        flat = " ".join(self.text.split())
        self.assertLess(self.text.index("--status"), self.text.index("## 2. Settings"))
        self.assertIn('"installed 0.7.3, installer 0.8.0"', flat)
        self.assertIn("An upgrade is the same command rerun", flat)

    def test_asks_once_and_never_infers_consent(self):
        flat = " ".join(self.text.split())
        self.assertEqual(flat.count("ask the user once"), 2)  # tracker, then remote-judge consent
        self.assertIn("Never infer consent from earlier runs", flat)
        self.assertIn("Never run or recommend `bd init`", flat)


@needs_wheel
class SelfContainedPluginTests(Scratch):
    """Every package file install.py reads is inside the plugin directory: a lone copy of it installs the same bytes."""

    def test_a_copy_of_the_plugin_alone_installs(self):
        copy = self.tmp / "cache" / "sc-plan-anchor"
        shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("__pycache__"))
        repo = git_repo(self.tmp / "repo", backend="sqlite")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "br").write_text("#!/bin/sh\necho br 0.7.4\n", encoding="utf-8")
        (bin_dir / "br").chmod(0o755)
        if os.name == "nt":
            self.skipTest("the fake br is a POSIX shell script")
        proc = subprocess.run([sys.executable, "-I", str(copy / "install.py"), "--dest", str(repo), "--tracker", "br",
                               "--no-remote-judge", "--target", "claude,codex,cursor"], cwd=str(self.tmp),
                              env=child_env(self.home, bin_dir), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        mirror = git_repo(self.tmp / "mirror", backend="sqlite")
        code, out = call_main(["--dest", str(mirror), "--tracker", "br", "--no-remote-judge", "--target", "claude,codex,cursor"])
        self.assertEqual(code, 0, out)
        installed = {k: v for k, v in tree(repo).items() if not k.startswith(".git/")}
        expected = {k: v for k, v in tree(mirror).items() if not k.startswith(".git/")}
        self.assertEqual(sorted(installed), sorted(expected))
        lock_a = json.loads(installed.pop(".sc/plan-anchor/install-lock.json"))
        lock_b = json.loads(expected.pop(".sc/plan-anchor/install-lock.json"))
        self.assertEqual(lock_a["files"], lock_b["files"])
        self.assertEqual(installed, expected)


# ---------------------------------------------------------------- upgrade from 0.7.3


@needs_wheel
class UpgradeFromMarketplaceReleaseTests(Scratch):
    """Install with the real 0.7.3 installer (the marketplace layout), then rerun 0.8.0's."""

    def old_install(self, repo):
        if not _has_commit(RELEASE_0_7_3):
            self.skipTest(f"0.7.3 commit {RELEASE_0_7_3} is not in this clone")
        if os.name == "nt":
            self.skipTest("the fake br is a POSIX shell script")
        archive = self.tmp / "old.tar"
        archive.write_bytes(_git("archive", RELEASE_0_7_3, "plugins/sc-plan-anchor"))
        old = self.tmp / "old"
        with tarfile.open(archive) as tar:
            tar.extractall(old)
        self.assertEqual(json.loads((old / "plugins/sc-plan-anchor/plugin.json").read_text())["version"], "0.7.3")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "br").write_text("#!/bin/sh\necho br 0.7.4\n", encoding="utf-8")
        (bin_dir / "br").chmod(0o755)
        proc = subprocess.run([sys.executable, "-I", str(old / "plugins/sc-plan-anchor/install.py"), "--dest", str(repo),
                               "--no-remote-judge", "--target", "claude,codex"], cwd=str(self.tmp),
                              env=child_env(self.home, bin_dir), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)["data"]

    def test_rerun_upgrades_and_removes_retired_files_per_the_lock(self):
        repo = TempRepo(self, beads="sqlite")
        old = self.old_install(repo.root)
        self.assertEqual((old["version"], old["tracker"]), ("0.7.3", "br"))
        lock_path = repo.path(inst.LOCK_RELPATH)
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        # 0.8.0 retires none of 0.7.3's files, so one is planted as the lock would record it.
        retired = ".codex/skills/plan-anchoring/references/retired-reference.md"
        repo.path(retired).write_bytes(b"shipped by an older release\n")
        lock["files"][retired] = sha(b"shipped by an older release\n")
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        with fake_home(self.tmp / "nohome"):
            code, out = call_main(["--dest", str(repo.root), "--status"])
        self.assertEqual((out["data"]["state"], out["data"]["message"]), ("older", f"installed 0.7.3, installer {VERSION}"))

        data = self.ok(inst.install(inst.Options(dest=repo.root, tracker=None, targets=["claude"]),
                                    which=fake_which, run=FakeRun()))
        self.assertEqual((data["previous_version"], data["version"], data["tracker_origin"]), ("0.7.3", VERSION, "settings"))
        self.assertEqual(data["targets"], ["claude", "codex"])  # every locked target is upgraded
        self.assertEqual(data["plan"]["remove"], [retired])
        self.assertFalse(repo.path(retired).exists())
        self.assertEqual(data["plan"]["backup"], [])
        for target in ("claude", "codex"):
            self.assertIn(f".{target}/skills/plan-anchoring/registry.yaml", data["plan"]["create"])
            self.assertIn(f".{target}/skills/plan-anchoring/scripts/plan_anchor_paths.py", data["plan"]["create"])
        new_lock = json.loads(lock_path.read_text(encoding="utf-8"))
        self.assertEqual(new_lock["version"], VERSION)
        self.assertNotIn(retired, new_lock["files"])
        for key, digest in new_lock["files"].items():
            self.assertEqual(sha(repo.path(key).read_bytes()), digest, key)
        rerun = self.ok(inst.install(inst.Options(dest=repo.root, tracker=None, targets=["claude"]),
                                     which=fake_which, run=FakeRun()))
        self.assertEqual((rerun["plan"]["create"], rerun["plan"]["replace"], rerun["plan"]["remove"]), ([], [], []))

        repo.beads("dolt")  # the repository moved to a Dolt-backed bd workspace
        switched = self.ok(inst.install(inst.Options(dest=repo.root, tracker="bd", targets=["claude"]),
                                        which=fake_which, run=FakeRun()))
        self.assertTrue(switched["switched"])
        self.assertEqual((switched["previous_tracker"], switched["tracker"]), ("br", "bd"))
        self.assertEqual(json.loads(lock_path.read_text())["tracker"], "bd")
        for target in ("claude", "codex"):
            sprint = repo.path(f".{target}/agents/anchor-sprint-review.md").read_text(encoding="utf-8")
            self.assertIn("this install is rendered for `bd`", sprint)
        self.assertIn("anchor_tracker: bd", repo.path(".sc/plan-anchor/settings.yaml").read_text(encoding="utf-8"))

    def ok(self, result):
        self.assertIsInstance(result, inst.Ok, getattr(result, "error", None) and result.error.to_json())
        return result.value


if __name__ == "__main__":
    unittest.main()
