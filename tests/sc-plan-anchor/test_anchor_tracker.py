"""Anchor tracker selection: .sc/plan-anchor/settings.yaml, detection, br init, CLI envelope."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "plugins" / "sc-plan-anchor" / "skills" / "plan-anchoring" / "scripts"
TRACKER_SCRIPT = SCRIPTS / "anchor_tracker.py"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


result = _load("result")
settings_mod = _load("plan_anchor_settings")
tracker = _load("anchor_tracker")

EXPECTED_FILE = (
    "# .sc/plan-anchor/settings.yaml\n"
    "# Repository settings for the sc-plan-anchor plugin; commit this file, never put secrets in it.\n"
    "schema_version: 1\n"
    "anchor_tracker: {tracker}\n"
)
GIT = shutil.which("git")
HAS_YAML = importlib.util.find_spec("yaml") is not None
NO_YAML_REASON = ("PyYAML is not installed (python3 -m pip install pyyaml); settings-backed tests need it. "
                  "Tests marked without_yaml still run and prove DEPENDENCY.PYYAML is returned.")


def without_yaml(test):
    """Mark a test that does not need PyYAML installed (it simulates its absence)."""
    test.runs_without_yaml = True
    return test


def skip_unless_yaml(case):
    if not HAS_YAML and not getattr(getattr(case, case._testMethodName), "runs_without_yaml", False):
        case.skipTest(NO_YAML_REASON)


def fake_which(*available):
    return lambda name: f"/fake/bin/{name}" if name in available else None


class Recorder:
    """A subprocess.run stand-in that records argv and can create .beads/."""

    def __init__(self, returncode=0, stderr="", create=True, raises=None):
        self.calls = []
        self.returncode = returncode
        self.stderr = stderr
        self.create = create
        self.raises = raises

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if self.raises is not None:
            raise self.raises
        if self.create and self.returncode == 0:
            beads = Path(kwargs["cwd"]) / ".beads"
            beads.mkdir()
            (beads / "metadata.json").write_text(
                json.dumps({"database": "beads.db", "jsonl_export": "issues.jsonl"}), encoding="utf-8")
        return subprocess.CompletedProcess(argv, self.returncode, stdout="", stderr=self.stderr)


class RepoCase(unittest.TestCase):
    def setUp(self):
        skip_unless_yaml(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "repo"
        self.root.mkdir()
        (self.root / ".git").mkdir()  # fallback marker; real git repos are tested separately
        patcher = mock.patch.object(settings_mod, "_git_toplevel", lambda start: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    # disk fixtures -------------------------------------------------------
    def beads(self, metadata=None, raw=None):
        beads = self.root / ".beads"
        beads.mkdir(exist_ok=True)
        if raw is not None:
            (beads / "metadata.json").write_bytes(raw)
        elif metadata is not None:
            (beads / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        return beads

    def dolt(self):
        return self.beads({"backend": "dolt", "database": "dolt"})

    def br_workspace(self):
        return self.beads({"database": "beads.db", "jsonl_export": "issues.jsonl"})

    def setting(self, text):
        path = self.root / ".sc" / "plan-anchor" / "settings.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")
        return path

    def pin(self, value):
        return self.setting(f"schema_version: 1\nanchor_tracker: {value}\n")

    @property
    def settings_file(self):
        return self.root / ".sc" / "plan-anchor" / "settings.yaml"

    # assertions ----------------------------------------------------------
    def resolve(self, which=None, start=None):
        return tracker.resolve(start or self.root, which=which or fake_which("bd", "br"))

    def assertOk(self, outcome):
        self.assertIsInstance(outcome, result.Ok, getattr(outcome, "error", None))
        self.assertIs(outcome.ok, True)
        return outcome.value

    def assertErr(self, outcome, code):
        self.assertIsInstance(outcome, result.Err, f"expected {code}, got {outcome!r}")
        self.assertIs(outcome.ok, False)
        self.assertEqual(outcome.error.code, code, outcome.error.message)
        self.assertTrue(outcome.error.message)
        return outcome.error


class ResultTypeTests(unittest.TestCase):
    def test_ok_and_err_are_frozen_discriminated_variants(self):
        ok = result.Ok(3)
        bad = result.err("X.Y", "broken", "fix it")
        self.assertIs(ok.ok, True)
        self.assertIs(bad.ok, False)
        self.assertEqual(bad.error, result.ToolError("X.Y", "broken", "fix it"))
        with self.assertRaises(Exception):
            ok.value = 4  # frozen
        with self.assertRaises(TypeError):
            result.Ok(1, ok=False)  # the discriminant is not settable
        self.assertEqual(bad.error.to_json(), {
            "code": "X.Y", "message": "broken", "recoverable": False, "suggested_action": "fix it"})


class SelectionRuleTests(RepoCase):
    def test_setting_bd_with_dolt_backend_is_selected(self):
        self.dolt()
        self.pin("bd")
        sel = self.assertOk(self.resolve())
        self.assertEqual((sel.tracker, sel.source), ("bd", "setting"))
        self.assertTrue(sel.beads.dolt)

    def test_setting_bd_without_dolt_is_an_error_naming_scope(self):
        for prepare in (lambda: None, self.br_workspace, lambda: self.beads({"backend": "sqlite"})):
            with self.subTest(prepare=prepare):
                shutil.rmtree(self.root / ".beads", ignore_errors=True)
                prepare()
                self.pin("bd")
                error = self.assertErr(self.resolve(), "TRACKER.DOLT_REQUIRED")
                self.assertIn("outside this skill", error.message)
                self.assertNotIn("bd init", f"{error.message} {error.action}")

    def test_setting_br_with_dolt_backend_is_a_mismatch(self):
        self.dolt()
        self.pin("br")
        error = self.assertErr(self.resolve(), "TRACKER.MISMATCH")
        self.assertEqual(error.data["evidence"]["backend"], "dolt")

    def test_setting_br_with_br_workspace_or_none(self):
        self.pin("br")
        sel = self.assertOk(self.resolve())
        self.assertEqual((sel.tracker, sel.source, sel.beads.exists), ("br", "setting", False))
        self.br_workspace()
        sel = self.assertOk(self.resolve())
        self.assertEqual((sel.tracker, sel.source, sel.beads.exists), ("br", "setting", True))

    def test_no_setting_with_dolt_detects_bd(self):
        self.dolt()
        sel = self.assertOk(self.resolve())
        self.assertEqual((sel.tracker, sel.source), ("bd", "detected"))

    def test_no_setting_with_non_dolt_beads_detects_br(self):
        cases = (None, {"database": "beads.db"}, {"backend": "sqlite"}, {"backend": "Dolt "})
        for metadata in cases:
            with self.subTest(metadata=metadata):
                shutil.rmtree(self.root / ".beads", ignore_errors=True)
                self.beads(metadata)
                sel = self.assertOk(self.resolve())
                self.assertEqual((sel.tracker, sel.source), ("br", "detected"))

    def test_no_beads_detects_br_without_initializing(self):
        sel = self.assertOk(self.resolve())
        self.assertEqual((sel.tracker, sel.source, sel.beads.exists), ("br", "detected", False))
        self.assertFalse((self.root / ".beads").exists())
        self.assertFalse(self.settings_file.exists(), "resolve is read-only")

    def test_settings_without_tracker_key_falls_back_to_detection(self):
        self.setting("schema_version: 1\n")
        self.dolt()
        sel = self.assertOk(self.resolve())
        self.assertEqual((sel.tracker, sel.source), ("bd", "detected"))

    def test_selected_cli_must_be_on_path(self):
        self.assertErr(self.resolve(which=fake_which("bd")), "TRACKER.CLI_MISSING")
        self.dolt()
        error = self.assertErr(self.resolve(which=fake_which("br")), "TRACKER.CLI_MISSING")
        self.assertIn("'bd'", error.message)
        self.assertEqual(error.data, {"tracker": "bd"})
        sel = self.assertOk(self.resolve(which=fake_which("bd")))
        self.assertEqual(sel.cli_path, "/fake/bin/bd")

    def test_selection_never_switches_to_the_other_cli(self):
        self.dolt()
        self.pin("br")
        # Even with only br installed, a br pin on a Dolt workspace is an error, not a switch.
        self.assertErr(self.resolve(which=fake_which("br")), "TRACKER.MISMATCH")


class MalformedInputTests(RepoCase):
    def test_malformed_metadata(self):
        cases = {
            b"{not json": "not valid JSON",
            b"[1, 2]": "JSON object",
            json.dumps({"backend": 7}).encode(): "string",
            b"\xff\xfe\x00bad": "could not be read",
        }
        for raw, fragment in cases.items():
            with self.subTest(raw=raw):
                shutil.rmtree(self.root / ".beads", ignore_errors=True)
                self.beads(raw=raw)
                error = self.assertErr(self.resolve(), "BEADS.METADATA_INVALID")
                self.assertIn(fragment, error.message)

    def test_beads_file_instead_of_directory(self):
        (self.root / ".beads").write_text("x", encoding="utf-8")
        self.assertErr(self.resolve(), "BEADS.NOT_DIRECTORY")

    def test_malformed_settings(self):
        cases = {
            "schema_version: [1\n": "SETTINGS.MALFORMED",
            "- schema_version: 1\n": "SETTINGS.MALFORMED",
            "": "SETTINGS.MALFORMED",
            "just a string\n": "SETTINGS.MALFORMED",
            "schema_version: 1\nschema_version: 1\nanchor_tracker: br\n": "SETTINGS.MALFORMED",
            "schema_version: 1\nanchor_tracker: br\nanchor_tracker: bd\n": "SETTINGS.MALFORMED",
            b"schema_version: 1\nanchor_tracker: \xff\n": "SETTINGS.UNREADABLE",
        }
        for text, code in cases.items():
            with self.subTest(text=text):
                self.setting(text)
                self.assertErr(self.resolve(), code)

    def test_unknown_keys_are_rejected(self):
        for text in ("schema_version: 1\nanchor_tracker: br\nfast_agents: [a]\n",
                     "schema_version: 1\nanchor-tracker: br\n",
                     "schema_version: 1\nAnchor_Tracker: br\n"):
            with self.subTest(text=text):
                self.setting(text)
                error = self.assertErr(self.resolve(), "SETTINGS.UNKNOWN_KEY")
                self.assertTrue(error.data["unknown_keys"])

    def test_schema_version_must_be_integer_one(self):
        for value in ("2", "0", "'1'", "true", "1.0", "null"):
            with self.subTest(value=value):
                self.setting(f"schema_version: {value}\nanchor_tracker: br\n")
                self.assertErr(self.resolve(), "SETTINGS.SCHEMA_VERSION")
        self.setting("anchor_tracker: br\n")
        self.assertErr(self.resolve(), "SETTINGS.SCHEMA_VERSION")

    def test_tracker_value_must_be_bd_or_br(self):
        for value in ("bx", "BR", "no", "null", "[br]", "''"):
            with self.subTest(value=value):
                self.setting(f"schema_version: 1\nanchor_tracker: {value}\n")
                self.assertErr(self.resolve(), "SETTINGS.INVALID_TRACKER")

    @without_yaml
    def test_missing_pyyaml_is_a_typed_error_not_a_fallback(self):
        self.pin("br")
        with mock.patch.dict(sys.modules, {"yaml": None}):
            error = self.assertErr(self.resolve(), "DEPENDENCY.PYYAML")
            self.assertIn("python3 -m pip install pyyaml", error.action)
            # Even with no settings file, resolve does not silently skip validation.
            self.settings_file.unlink()
            self.assertErr(self.resolve(), "DEPENDENCY.PYYAML")
            self.assertErr(tracker.write(self.root, which=fake_which("br"), run=Recorder()), "DEPENDENCY.PYYAML")
        self.assertFalse(self.settings_file.exists())


class RepoRootTests(RepoCase):
    def test_subdirectory_resolves_to_repository_root_not_cwd(self):
        nested = self.root / "a" / "b"
        nested.mkdir(parents=True)
        self.pin("br")
        self.dolt()
        elsewhere = Path(self._tmp.name).resolve()
        cwd = os.getcwd()
        try:
            os.chdir(str(elsewhere))  # cwd has no settings; the root's settings must still be read
            self.assertErr(self.resolve(start=nested), "TRACKER.MISMATCH")
        finally:
            os.chdir(cwd)
        self.assertEqual(self.assertOk(settings_mod.find_repo_root(nested)), self.root)

    def test_outside_any_repository_is_fatal(self):
        outside = Path(self._tmp.name).resolve() / "elsewhere"
        outside.mkdir()
        if any((p / ".git").exists() for p in (outside, *outside.parents)):
            self.skipTest("temporary directory sits inside a git checkout")
        self.assertErr(tracker.resolve(outside, which=fake_which("br")), "REPO.NOT_FOUND")
        self.assertErr(tracker.resolve(self.root / "missing", which=fake_which("br")), "REPO.NOT_FOUND")

    @unittest.skipUnless(GIT, "git is not installed")
    def test_git_toplevel_is_used_when_available(self):
        real = Path(self._tmp.name).resolve() / "real"
        real.mkdir()
        subprocess.run([GIT, "init", "-q", str(real)], check=True)
        (real / "sub").mkdir()
        with mock.patch.object(settings_mod, "_git_toplevel", wraps=_REAL_GIT_TOPLEVEL) as spy:
            root = self.assertOk(settings_mod.find_repo_root(real / "sub"))
        self.assertEqual(root, real)
        spy.assert_called_once()


_REAL_GIT_TOPLEVEL = settings_mod._git_toplevel


class WriteAndInitTests(RepoCase):
    def write(self, **kwargs):
        kwargs.setdefault("which", fake_which("bd", "br"))
        kwargs.setdefault("run", Recorder())
        return tracker.write(self.root, **kwargs)

    def test_write_produces_committed_format(self):
        self.br_workspace()
        data = self.assertOk(self.write())
        self.assertTrue(data["written"])
        self.assertEqual(data["commit_paths"], [".sc/plan-anchor/settings.yaml"])
        self.assertTrue(any("Commit .sc/plan-anchor/settings.yaml" in a for a in data["next_actions"]))
        self.assertEqual(self.settings_file.read_bytes(), EXPECTED_FILE.format(tracker="br").encode("ascii"))
        sel = self.assertOk(self.resolve())
        self.assertEqual((sel.tracker, sel.source), ("br", "setting"))

    def test_write_detected_bd_on_dolt_and_never_initializes(self):
        self.dolt()
        run = Recorder()
        data = self.assertOk(self.write(init=True, run=run))
        self.assertEqual(data["tracker"], "bd")
        self.assertEqual(run.calls, [])
        self.assertEqual(self.settings_file.read_text(encoding="utf-8"), EXPECTED_FILE.format(tracker="bd"))

    def test_existing_setting_is_left_untouched(self):
        custom = "# my comment\nschema_version: 1\nanchor_tracker: br\n"
        self.setting(custom)
        data = self.assertOk(self.write())
        self.assertFalse(data["written"])
        self.assertEqual(data["commit_paths"], [])
        self.assertEqual(self.settings_file.read_text(encoding="utf-8"), custom)

    def test_pin_conflicting_with_setting_is_refused(self):
        self.pin("br")
        self.dolt()
        self.assertErr(self.write(pinned="bd"), "SETTINGS.CONFLICT")  # never rewrites a committed choice
        self.assertErr(self.write(), "TRACKER.MISMATCH")  # the file wins and is validated
        shutil.rmtree(self.root / ".beads")
        self.assertErr(self.write(pinned="bd"), "SETTINGS.CONFLICT")
        self.assertEqual(self.settings_file.read_text(encoding="utf-8"), "schema_version: 1\nanchor_tracker: br\n")

    def test_pin_is_checked_against_disk(self):
        self.br_workspace()
        self.assertErr(self.write(pinned="bd"), "TRACKER.DOLT_REQUIRED")
        self.assertFalse(self.settings_file.exists())
        data = self.assertOk(self.write(pinned="br"))
        self.assertEqual((data["tracker"], data["source"]), ("br", "setting"))

    def test_write_without_init_never_runs_br_init(self):
        run = Recorder()
        data = self.assertOk(self.write(run=run))
        self.assertEqual(run.calls, [])
        self.assertFalse(data["beads_initialized"])
        self.assertTrue(any("--init" in a for a in data["next_actions"]))
        self.assertEqual(self.settings_file.read_text(encoding="utf-8"), EXPECTED_FILE.format(tracker="br"))

    def test_init_runs_br_init_with_fixed_argv_and_no_shell(self):
        run = Recorder()
        data = self.assertOk(self.write(init=True, run=run))
        self.assertEqual(len(run.calls), 1)
        argv, kwargs = run.calls[0]
        self.assertEqual(argv, ["/fake/bin/br", "init"])
        self.assertEqual(Path(kwargs["cwd"]), self.root)
        self.assertFalse(kwargs.get("shell", False))
        self.assertTrue(data["initialized_now"])
        self.assertTrue(data["beads_initialized"])
        self.assertEqual(data["commit_paths"], [".sc/plan-anchor/settings.yaml", ".beads/"])
        self.assertTrue(any("br sync --flush-only" in a for a in data["next_actions"]))

    def test_init_skipped_when_beads_exists(self):
        self.br_workspace()
        run = Recorder()
        data = self.assertOk(self.write(init=True, run=run))
        self.assertEqual(run.calls, [])
        self.assertFalse(data["initialized_now"])

    def test_br_init_failure_surfaces_code_and_stderr(self):
        run = Recorder(returncode=3, stderr="error: cannot create database\n")
        error = self.assertErr(self.write(init=True, run=run), "TRACKER.INIT_FAILED")
        self.assertIn("exited 3", error.message)
        self.assertIn("cannot create database", error.message)
        self.assertEqual(error.data, {"returncode": 3, "stderr": "error: cannot create database"})
        self.assertFalse(self.settings_file.exists(), "nothing is persisted after a failed init")

    def test_br_init_that_creates_nothing_or_cannot_start(self):
        self.assertErr(self.write(init=True, run=Recorder(create=False)), "TRACKER.INIT_FAILED")
        self.assertErr(self.write(init=True, run=Recorder(raises=FileNotFoundError("br"))), "TRACKER.INIT_FAILED")
        timeout = subprocess.TimeoutExpired(["br", "init"], 120)
        self.assertErr(self.write(init=True, run=Recorder(raises=timeout)), "TRACKER.INIT_FAILED")
        self.assertFalse(self.settings_file.exists())

    def test_init_requires_br_on_path_before_running_anything(self):
        run = Recorder()
        self.assertErr(self.write(init=True, run=run, which=fake_which("bd")), "TRACKER.CLI_MISSING")
        self.assertEqual(run.calls, [])

    def test_bd_is_never_initialized(self):
        run = Recorder()
        error = self.assertErr(tracker.init_br("bd", "/fake/bin/bd", self.root, run), "TRACKER.INIT_REFUSED")
        self.assertIn("outside this skill", error.message)
        self.assertEqual(run.calls, [])
        # Every write path with --init: no recorded argv ever names bd.
        scenarios = (lambda: None, self.dolt, self.br_workspace, lambda: self.pin("bd"), lambda: self.pin("br"))
        for prepare in scenarios:
            with self.subTest(prepare=prepare):
                shutil.rmtree(self.root / ".beads", ignore_errors=True)
                shutil.rmtree(self.root / ".sc", ignore_errors=True)
                prepare()
                run = Recorder()
                tracker.write(self.root, init=True, which=fake_which("bd", "br"), run=run)
                for argv, _ in run.calls:
                    self.assertNotIn("bd", [Path(argv[0]).stem] + argv[1:])
                    self.assertEqual(argv, ["/fake/bin/br", "init"])


class CliTests(RepoCase):
    def main(self, *argv, which=None, run=None):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = tracker.main(list(argv) + ["--repository-root", str(self.root)],
                                which=which or fake_which("bd", "br"), run=run or Recorder())
        return code, json.loads(out.getvalue())

    def test_envelope_and_exit_codes(self):
        code, env = self.main("resolve")
        self.assertEqual(code, 0)
        self.assertEqual(set(env), {"success", "data", "error"})
        self.assertTrue(env["success"])
        self.assertIsNone(env["error"])
        self.assertEqual((env["data"]["tracker"], env["data"]["source"]), ("br", "detected"))
        self.assertEqual(env["data"]["settings_relpath"], ".sc/plan-anchor/settings.yaml")

        self.dolt()
        self.pin("br")
        code, env = self.main("resolve")
        self.assertEqual(code, 2)  # every error exits 2, as in jev_judge.py and plan_source.py
        self.assertFalse(env["success"])
        self.assertEqual(env["error"]["code"], "TRACKER.MISMATCH")
        self.assertEqual(set(env["error"]), {"code", "message", "recoverable", "suggested_action"})

    def test_fatal_codes_exit_two(self):
        code, env = self.main("write", "--init", run=Recorder(returncode=9, stderr="nope"))
        self.assertEqual((code, env["error"]["code"]), (2, "TRACKER.INIT_FAILED"))
        self.assertEqual(env["data"]["returncode"], 9)
        code, env = self.main("resolve", which=fake_which("bd"))
        self.assertEqual((code, env["error"]["code"]), (2, "TRACKER.CLI_MISSING"))

    @without_yaml
    def test_missing_pyyaml_exits_two(self):
        with mock.patch.dict(sys.modules, {"yaml": None}):
            code, env = self.main("resolve")
        self.assertEqual((code, env["error"]["code"]), (2, "DEPENDENCY.PYYAML"))

    @without_yaml
    def test_usage_errors_are_json(self):
        import contextlib
        import io
        for argv in ([], ["bogus"], ["write", "--tracker", "bx"], ["resolve", "--nope"]):
            with self.subTest(argv=argv):
                out, err_out = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err_out):
                    code = tracker.main(argv, which=fake_which("br"), run=Recorder())
                env = json.loads(out.getvalue())
                self.assertEqual((code, env["success"], env["error"]["code"]), (2, False, "VALIDATION.INPUT"))
                self.assertTrue(env["error"]["suggested_action"])
                self.assertEqual(err_out.getvalue(), "")

    def test_cli_path_is_absolute_even_when_which_answers_relative(self):
        code, env = self.main("resolve", which=lambda name: os.path.join(".", f"{name}.CMD"))
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isabs(env["data"]["cli_path"]), env["data"]["cli_path"])

    def test_unanswerable_gitignore_check_is_reported(self):
        def fail_git(argv, **kwargs):
            raise FileNotFoundError("git")
        with mock.patch.object(tracker.subprocess, "run", fail_git):
            code, env = self.main("write")
        self.assertEqual(code, 0)
        self.assertIsNone(env["data"]["settings_ignored_by_git"])
        self.assertIn("git could not start", env["data"]["settings_ignored_check_error"])
        self.assertTrue(any("git check-ignore -v" in a for a in env["data"]["next_actions"]))

    def test_unexpected_exception_becomes_script_internal(self):
        def broken(name):
            raise RuntimeError("bug")
        code, env = self.main("resolve", which=broken)
        self.assertEqual((code, env["error"]["code"]), (2, "SCRIPT.INTERNAL"))


def _write_fake_cli(bin_dir: Path, name: str, body: str) -> None:
    """A fake executable that works on POSIX (sh shim) and Windows (.cmd shim)."""
    impl = bin_dir / f"{name}_impl.py"
    impl.write_text(body, encoding="utf-8")
    if os.name == "nt":
        (bin_dir / f"{name}.cmd").write_text(
            f'@"{sys.executable}" "{impl}" %*\r\n@exit /b %errorlevel%\r\n', encoding="utf-8")
    else:
        shim = bin_dir / name
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)


FAKE_BR = textwrap.dedent("""\
    import json, os, pathlib, sys
    log = pathlib.Path(os.environ["FAKE_LOG"])
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(["br"] + sys.argv[1:]) + "\\n")
    if os.environ.get("FAKE_BR_FAIL"):
        sys.stderr.write("br: refusing for test\\n")
        sys.exit(5)
    if sys.argv[1:] == ["init"]:
        beads = pathlib.Path.cwd() / ".beads"
        beads.mkdir()
        (beads / "metadata.json").write_text(json.dumps({"database": "beads.db"}), encoding="utf-8")
    """)
FAKE_BD = textwrap.dedent("""\
    import json, os, pathlib, sys
    with pathlib.Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(["bd"] + sys.argv[1:]) + "\\n")
    sys.exit(42)
    """)


class FakeExecutableEndToEndTests(unittest.TestCase):
    """The real CLI as a subprocess, with fake br/bd first on PATH."""

    def setUp(self):
        skip_unless_yaml(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.root = base / "repo"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        self.bin = base / "bin"
        self.bin.mkdir()
        _write_fake_cli(self.bin, "br", FAKE_BR)
        _write_fake_cli(self.bin, "bd", FAKE_BD)
        self.log = base / "calls.log"
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
                        FAKE_LOG=str(self.log), GIT_CEILING_DIRECTORIES=str(base))

    def run_cli(self, *argv, env=None, prelude=""):
        code = (f"import runpy, sys{prelude}\n"
                f"sys.argv = {[str(TRACKER_SCRIPT), *argv, '--repository-root', str(self.root)]!r}\n"
                f"runpy.run_path({str(TRACKER_SCRIPT)!r}, run_name='__main__')\n")
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              env=env or self.env, cwd=str(self.bin))
        return proc.returncode, json.loads(proc.stdout), proc

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_write_init_invokes_fake_br_init_on_path(self):
        code, env, proc = self.run_cli("write", "--init")
        self.assertEqual(code, 0, proc.stdout + proc.stderr)
        self.assertTrue(env["data"]["initialized_now"])
        self.assertEqual(self.calls(), [["br", "init"]])
        self.assertTrue((self.root / ".beads" / "metadata.json").is_file())
        self.assertEqual((self.root / ".sc/plan-anchor/settings.yaml").read_text(encoding="utf-8"),
                         EXPECTED_FILE.format(tracker="br"))
        code, env, _ = self.run_cli("resolve")
        self.assertEqual((code, env["data"]["tracker"], env["data"]["source"]), (0, "br", "setting"))
        self.assertTrue(all(call[0] != "bd" for call in self.calls()))

    def test_fake_br_init_failure_surfaces_exit_code_and_stderr(self):
        code, env, _ = self.run_cli("write", "--init", env=dict(self.env, FAKE_BR_FAIL="1"))
        self.assertEqual(code, 2)
        self.assertEqual(env["error"]["code"], "TRACKER.INIT_FAILED")
        self.assertEqual(env["data"]["returncode"], 5)
        self.assertIn("refusing for test", env["data"]["stderr"])
        self.assertFalse((self.root / ".sc").exists())

    def test_dolt_workspace_never_calls_bd(self):
        (self.root / ".beads").mkdir()
        (self.root / ".beads" / "metadata.json").write_text('{"backend": "dolt"}', encoding="utf-8")
        code, env, _ = self.run_cli("write", "--init")
        self.assertEqual((code, env["data"]["tracker"]), (0, "bd"))
        self.assertEqual(self.calls(), [])

    def test_relative_path_entry_still_runs_br_init(self):
        # A relative PATH entry (and Windows' implicit current-directory search)
        # makes which() answer relative to the caller's cwd; br init runs in the
        # repository root, so the CLI path must be absolute (Windows CI regression).
        env = dict(self.env, PATH="." + os.pathsep + os.environ.get("PATH", ""))
        code, out, proc = self.run_cli("write", "--init", env=env)
        self.assertEqual(code, 0, proc.stdout + proc.stderr)
        self.assertTrue(os.path.isabs(out["data"]["cli_path"]))
        self.assertEqual(self.calls(), [["br", "init"]])

    @without_yaml
    def test_pyyaml_missing_through_the_cli(self):
        code, env, _ = self.run_cli("resolve", prelude="\nsys.modules['yaml'] = None")
        self.assertEqual((code, env["error"]["code"]), (2, "DEPENDENCY.PYYAML"))
        self.assertIn("python3 -m pip install pyyaml", env["error"]["suggested_action"])


class RepositoryContractTests(unittest.TestCase):
    @unittest.skipUnless(HAS_YAML, NO_YAML_REASON)
    def test_this_repository_pins_br(self):
        path = ROOT / ".sc" / "plan-anchor" / "settings.yaml"
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# .sc/plan-anchor/settings.yaml\n"))
        self.assertEqual(text, EXPECTED_FILE.format(tracker="br"))
        parsed = settings_mod.parse_settings(text, __import__("yaml"))
        self.assertEqual(parsed.value, settings_mod.Settings(1, "br"))

    @unittest.skipUnless(GIT, "git is not installed")
    def test_settings_file_is_not_gitignored(self):
        proc = subprocess.run([GIT, "-C", str(ROOT), "check-ignore", "-q", "--", ".sc/plan-anchor/settings.yaml"],
                              capture_output=True, text=True)
        if proc.returncode == 128:
            self.skipTest("not a git checkout")
        self.assertEqual(proc.returncode, 1, "settings.yaml must stay tracked")

    def test_other_scripts_stay_stdlib_only(self):
        allowed = {"plan_anchor_settings.py", "anchor_tracker.py"}
        for script in sorted(SCRIPTS.glob("*.py")):
            source = script.read_text(encoding="utf-8")
            if script.name not in allowed:
                with self.subTest(script=script.name):
                    self.assertNotIn("import yaml", source)
                    self.assertNotIn("plan_anchor_settings", source)
        self.assertNotIn("import yaml", (SCRIPTS / "plan_anchor_settings.py").read_text(encoding="utf-8"))
        for name in ("jev_judge.py", "plan_source.py", "anchor_runner_contract.py",
                     "anchor_tuning_contract.py", "anchor_tracker.py"):
            with self.subTest(help=name):
                code = ("import runpy, sys\nsys.modules['yaml'] = None\n"
                        f"sys.argv = ['{name}', '--help']\nrunpy.run_path({str(SCRIPTS / name)!r}, run_name='__main__')\n")
                proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_ci_installs_pyyaml(self):
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        self.assertIn("pyyaml", workflow.lower())


if __name__ == "__main__":
    unittest.main()
