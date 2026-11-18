"""0.8.3: the repository CI scripts exit 2 with a message, never 1 and never a traceback.

check_version_sync.py runs as a real process: on the repository for a missing
``--base`` ref, and on a scratch copy of the repository for version drift and a
malformed manifest. gen_install_data.py and install_sc_compose_ci.py are driven
in-process with the failing call stubbed (a failing git command, a corrupt
legacy-owned.json, an unexpected exception), since provoking those for real needs a
broken clone or a network.
"""

import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
from child_support import run_test_child
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(f"ci_{name}", SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repo_copy(dest: Path) -> Path:
    """The repository's files (no .git, no caches) under ``dest``, for checks that must not touch the real tree."""
    shutil.copytree(ROOT, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", "node_modules"))
    return dest


class CheckVersionSync(unittest.TestCase):
    def run_check(self, root: Path, *argv):
        proc = run_test_child([sys.executable, str(root / "scripts" / "check_version_sync.py"), *argv], cwd=str(root),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertNotIn("Traceback", proc.stderr)
        return proc

    def test_a_missing_base_ref_exits_2(self):
        proc = self.run_check(ROOT, "--base", "refs/heads/no-such-branch-0-8-3")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("no-such-branch-0-8-3", proc.stderr)

    def test_version_drift_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            root = repo_copy(Path(td) / "repo")
            self.assertEqual(self.run_check(root).returncode, 0)  # the copy is in sync before the edit
            (root / "VERSION").write_text("99.0.0\n", encoding="utf-8")
            proc = self.run_check(root)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("99.0.0", proc.stdout + proc.stderr)

    def test_a_malformed_manifest_exits_2_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            root = repo_copy(Path(td) / "repo")
            for rel, text in (("plugins/sc-plan-anchor/plugin.json", "{"), (".claude-plugin/marketplace.json", "[1]")):
                with self.subTest(rel):
                    original = (root / rel).read_text(encoding="utf-8")
                    (root / rel).write_text(text, encoding="utf-8")
                    try:
                        proc = self.run_check(root)
                    finally:
                        (root / rel).write_text(original, encoding="utf-8")
                    self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                    self.assertIn(rel, proc.stderr)

    def test_git_timeout_is_a_typed_failure(self):
        check = load("check_version_sync")
        err = io.StringIO()
        with mock.patch.object(check.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(["git", "rev-parse"], 30)) as run, \
                mock.patch.object(check.sys, "argv", ["check_version_sync.py", "--base", "HEAD"]), \
                contextlib.redirect_stderr(err):
            code = check.main()
        self.assertEqual(code, 2)
        self.assertIn("git rev-parse --verify --quiet HEAD^{commit} timed out after 30 seconds", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["timeout"], check.GIT_TIMEOUT_SECONDS)


class GenInstallData(unittest.TestCase):
    def setUp(self):
        self.gen = load("gen_install_data")

    def main(self, *argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = self.gen.main(list(argv))
        return code, err.getvalue()

    def test_a_failing_git_command_exits_2(self):
        real = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if kwargs.get("check"):  # _git's calls; _has_commit's (check=False) still answer
                raise subprocess.CalledProcessError(128, cmd, output=b"", stderr=b"fatal: bad object")
            with mock.patch.object(self.gen.subprocess, "run", real):
                return run_test_child(cmd, *args, **kwargs)

        with mock.patch.object(self.gen.subprocess, "run", fake_run):
            code, err = self.main("--check")
        self.assertEqual(code, 2)
        self.assertIn("exited 128: fatal: bad object", err)

    def test_a_corrupt_legacy_owned_json_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            corrupt = Path(td) / "legacy-owned.json"
            for text, says in (("{", "is not valid JSON"), ("[]", "is not a legacy-ownership record")):
                with self.subTest(text=text):
                    corrupt.write_text(text, encoding="utf-8")
                    with mock.patch.object(self.gen, "LEGACY", corrupt), \
                            mock.patch.object(self.gen, "history_commits", return_value=([], [])), \
                            mock.patch.object(self.gen, "legacy", return_value={"skill": {}, "agents": {}}):
                        code, err = self.main("--check")
                    self.assertEqual(code, 2)
                    self.assertIn(says, err)

    def test_git_timeout_is_a_typed_failure(self):
        with mock.patch.object(self.gen.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(["git", "rev-parse"], 30)) as run:
            code, err = self.main("--check")
        self.assertEqual(code, 2)
        self.assertIn("git rev-parse timed out after 30 seconds", err)
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["timeout"], self.gen.GIT_TIMEOUT_SECONDS)

    def test_git_command_timeout_is_typed(self):
        with mock.patch.object(self.gen.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(["git", "status"], 30)):
            with self.assertRaisesRegex(self.gen.Failure, "git status timed out after 30 seconds"):
                self.gen._git("status")


class InstallScComposeCi(unittest.TestCase):
    def test_any_failure_exits_2_with_a_message(self):
        ci = load("install_sc_compose_ci")
        for exc in (RuntimeError("unsupported CI platform"), ValueError("bad digest field"), KeyError("assets")):
            with self.subTest(type(exc).__name__):
                def boom(exc=exc):
                    raise exc
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    code = ci.run(boom)
                self.assertEqual(code, 2)
                self.assertTrue(err.getvalue().startswith("install_sc_compose_ci: "), err.getvalue())

    def test_download_timeout_is_typed_and_child_is_bounded(self):
        ci = load("install_sc_compose_ci")
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(ci.sys, "platform", "darwin"), \
                mock.patch.object(ci.platform, "machine", return_value="arm64"), \
                mock.patch.dict(ci.os.environ, {"RUNNER_TEMP": temp}, clear=False), \
                mock.patch.object(ci.subprocess, "run",
                                  side_effect=subprocess.TimeoutExpired(["gh", "release"], 300)) as run, \
                contextlib.redirect_stderr(err):
            code = ci.run()
        self.assertEqual(code, 2)
        self.assertIn("timed out after 300 seconds", err.getvalue())
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["timeout"], ci.DOWNLOAD_TIMEOUT_SECONDS)
        self.assertNotIn("Traceback", err.getvalue())

    def test_version_probe_timeout_is_typed_and_uses_platform_executable_name(self):
        ci = load("install_sc_compose_ci")
        content = b"controlled archive"
        asset = "sc-compose-controlled.tar.gz"
        key = ("darwin", "aarch64")
        calls = []

        def controlled_run(command, **options):
            calls.append((command, options))
            if command[0] == "gh":
                destination = Path(command[command.index("--dir") + 1])
                (destination / asset).write_bytes(content)
                return subprocess.CompletedProcess(command, 0)
            raise subprocess.TimeoutExpired(command, ci.VERSION_TIMEOUT_SECONDS)

        def extract(_archive, destination):
            (destination / "sc-compose").write_text("controlled executable", encoding="utf-8")

        err = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(ci.sys, "platform", "darwin"), \
                mock.patch.object(ci.platform, "machine", return_value="arm64"), \
                mock.patch.dict(ci.os.environ, {"RUNNER_TEMP": temp}, clear=False), \
                mock.patch.dict(ci.ASSETS, {key: (asset, hashlib.sha256(content).hexdigest())}), \
                mock.patch.object(ci, "extract", side_effect=extract), \
                mock.patch.object(ci.subprocess, "run", side_effect=controlled_run), \
                contextlib.redirect_stderr(err):
            code = ci.run()
        self.assertEqual(code, 2)
        self.assertIn("timed out after 30 seconds", err.getvalue())
        self.assertTrue(str(calls[1][0][0]).endswith("/sc-compose"))
        self.assertTrue(all(options["stdin"] == subprocess.DEVNULL for _, options in calls))
        self.assertEqual([options["timeout"] for _, options in calls],
                         [ci.DOWNLOAD_TIMEOUT_SECONDS, ci.VERSION_TIMEOUT_SECONDS])


if __name__ == "__main__":
    unittest.main()
