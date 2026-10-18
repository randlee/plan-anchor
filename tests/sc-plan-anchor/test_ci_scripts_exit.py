"""0.8.3: the repository CI scripts exit 2 with a message, never 1 and never a traceback.

check_version_sync.py runs as a real process: on the repository for a missing
``--base`` ref, and on a scratch copy of the repository for version drift and a
malformed manifest. gen_install_data.py and install_sc_compose_ci.py are driven
in-process with the failing call stubbed (a failing git command, a corrupt
legacy-owned.json, an unexpected exception), since provoking those for real needs a
broken clone or a network.
"""

import contextlib
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
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
        proc = subprocess.run([sys.executable, str(root / "scripts" / "check_version_sync.py"), *argv], cwd=str(root),
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
            return real(cmd, *args, **kwargs)

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


if __name__ == "__main__":
    unittest.main()
