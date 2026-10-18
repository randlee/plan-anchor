"""0.8.3: installs in a repository subfolder, and the install-lock trust rule.

* The nearest ``.sc/plan-anchor/settings.yaml`` walking up from the working
  directory wins, even inside a repository: ``show`` and ``resolve`` run from a
  subfolder install read that subfolder's file.
* ``install.py --dest <repo>/sub`` without ``--tracker`` takes the tracker from the
  enclosing repository's ``.beads/`` or the nearest settings above, instead of
  failing with ``TRACKER.REQUIRED``.
* ``agent-preflight`` trusts only an install whose ``install-lock.json`` lists the
  script: a hand-copied (lock-less) copy and a copy under ``.agents/`` are
  ``VALIDATION.PATH``.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from layout_support import installed_scripts
from test_anchor_tracker import _write_fake_cli
from test_install import needs_wheel
from test_installer_skill import call_main, child_env, fake_home, git_repo

ANCHORS = {"schema": "plan-anchoring/anchors/1", "plan": "p", "intent_ref": "i.md", "anchors": []}
FAKE_BR = textwrap.dedent("""\
    import sys
    print("br 0.0.0-test")
""")


class Scratch(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()


class TrustNeedsTheInstallLock(Scratch):
    def preflight(self, scripts: Path, cwd: Path):
        (cwd / "anchors.json").write_text(json.dumps(ANCHORS), encoding="utf-8")
        script = scripts / "jev_judge.py"
        proc = subprocess.run([sys.executable, str(script), "agent-preflight", "--workspace-root", str(cwd),
                               "--script", str(script), "--anchors", "anchors.json"], cwd=str(cwd),
                              env=child_env(self.home), capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        return proc.returncode, json.loads(proc.stdout)

    def workspace(self, name):
        ws = self.tmp / name
        subprocess.run(["git", "init", "-q", str(ws)], check=True)
        return ws

    def test_an_installer_written_copy_is_trusted(self):
        ws = self.workspace("locked")
        code, out = self.preflight(installed_scripts(ws), ws)
        self.assertEqual((code, out["success"]), (0, True), out)

    def test_a_hand_copied_copy_without_the_lock_is_validation_path(self):
        ws = self.workspace("lockless")
        code, out = self.preflight(installed_scripts(ws, lock=False), ws)
        self.assertEqual((code, out["success"], out["error"]["code"]), (2, False, "VALIDATION.PATH"), out)
        self.assertIn("install-lock.json", out["error"]["message"])

    def test_a_copy_the_lock_does_not_list_is_validation_path(self):
        ws = self.workspace("unlisted")
        installed_scripts(ws, "codex")  # the lock lists the .codex copy only
        code, out = self.preflight(installed_scripts(ws, lock=False), ws)
        self.assertEqual((code, out["error"]["code"]), (2, "VALIDATION.PATH"), out)
        self.assertIn("does not list .claude/skills/plan-anchoring/scripts/jev_judge.py", out["error"]["message"])

    def test_a_copy_under_agents_is_validation_path_even_with_a_lock(self):
        ws = self.workspace("agents")
        code, out = self.preflight(installed_scripts(ws, "agents"), ws)
        self.assertEqual((code, out["success"], out["error"]["code"]), (2, False, "VALIDATION.PATH"), out)


@needs_wheel
class SubfolderInstall(Scratch):
    def install(self, dest: Path, *extra):
        dest.mkdir(parents=True, exist_ok=True)
        with fake_home(self.home):
            return call_main(["--dest", str(dest), *extra])

    def run_installed(self, dest: Path, cwd: Path, script: str, *argv):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        _write_fake_cli(bin_dir, "br", FAKE_BR)
        path = dest / ".claude" / "skills" / "plan-anchoring" / "scripts" / script
        proc = subprocess.run([sys.executable, str(path), *argv], cwd=str(cwd), env=child_env(self.home, bin_dir),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)["data"]

    def test_install_into_a_repo_subfolder_with_beads_needs_no_tracker(self):
        repo = git_repo(self.tmp / "r", backend="sqlite")
        sub = repo / "sub"
        code, out = self.install(sub, "--allow-remote-judge")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["tracker"], "br")
        own = sub / ".sc" / "plan-anchor" / "settings.yaml"
        self.assertTrue(own.is_file())
        self.assertFalse((repo / ".sc").exists())  # nothing written at the repository root
        # from the subfolder, show and resolve read the subfolder's file: the nearest one wins inside a repository
        shown = self.run_installed(sub, sub, "plan_anchor_settings.py", "show")
        self.assertEqual((Path(shown["settings_path"]).resolve() if os.path.isabs(shown["settings_path"]) else (repo / shown["settings_path"]).resolve(),
                          shown["allow_remote_judge"], shown["settings_inherited"]), (own.resolve(), True, False), shown)
        resolved = self.run_installed(sub, sub, "anchor_tracker.py", "resolve")
        self.assertEqual(resolved["tracker"], "br")
        self.assertEqual((repo / resolved["settings_path"]).resolve() if not os.path.isabs(resolved["settings_path"])
                         else Path(resolved["settings_path"]).resolve(), own.resolve(), resolved)
        self.assertFalse(resolved["settings_inherited"])

    def test_install_into_a_repo_subfolder_under_settings_needs_no_tracker(self):
        repo = git_repo(self.tmp / "r", settings="schema_version: 1\nanchor_tracker: br\n")
        code, out = self.install(repo / "sub")  # the repository has no .beads/ yet: br is selected, not initialized
        self.assertEqual((code, out["error"]["code"], out["data"]["tracker"]), (2, "TRACKER.NOT_INITIALIZED", "br"), out)
        code, out = self.install(repo / "sub", "--init-br")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["tracker"], "br")
        self.assertTrue((repo / ".beads" / "metadata.json").is_file())  # br init ran at the repository root
        self.assertFalse((repo / "sub" / ".beads").exists())


if __name__ == "__main__":
    unittest.main()
