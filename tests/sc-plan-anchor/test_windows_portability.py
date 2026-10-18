"""Two Windows behaviours, simulated portably so every OS runs them.

1. Output encoding. A child Python on Windows writes piped stdout in the locale
   code page (cp1252), so ``·`` reached UTF-8 readers as byte 0xb7. Every
   plan-anchor CLI now reconfigures its streams to UTF-8 at entry. The tests run
   each CLI with ``PYTHONIOENCODING=cp1252`` (the Windows pipe default, forced on
   any OS) and decode stdout and stderr strictly as UTF-8.

2. No home directory. Windows with no ``USERPROFILE`` and no
   ``HOMEDRIVE``/``HOMEPATH`` has no home: ``os.path.expanduser('~')`` returns
   ``~`` and ``Path.home()`` / ``Path('~').expanduser()`` raise RuntimeError.
   ``no_home()`` reproduces exactly that in this process. The walk for the
   nearest install or settings then ends at the filesystem root, the machine-wide
   global directories are still refused, and no lookup raises.

No test calls Jev; TYPESAFE_API_KEY is removed from every child environment.
"""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import test_jev_judge as tjj  # also puts scripts/ on sys.path
import test_remote_judge_setting as trs
from layout_support import PLUGIN, SCRIPTS

import plan_anchor_paths as paths  # noqa: E402
import plan_anchor_settings as settings_mod  # noqa: E402

INSTALL = PLUGIN / "install.py"
HOOK = PLUGIN / "hooks" / "check_install.py"
DOT = "·"  # the character that broke the Windows runs
NO_HOME = "Could not determine home directory."


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def no_home():
    """This process has no determinable home directory, as on Windows without USERPROFILE/HOMEDRIVE."""

    def expanduser(self):
        if str(self).startswith("~"):
            raise RuntimeError(NO_HOME)
        return self

    def home(cls):
        raise RuntimeError(NO_HOME)

    with mock.patch("os.path.expanduser", side_effect=lambda p: p), \
            mock.patch.object(Path, "expanduser", expanduser), \
            mock.patch.object(Path, "home", classmethod(home)):
        yield


def child_env(**extra):
    environment = {k: v for k, v in os.environ.items() if k not in ("TYPESAFE_API_KEY", "PYTHONUTF8")}
    environment.update(extra)
    return environment


class Scratch(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name).resolve()


# ------------------------------------------------------------------ home directory
class NoHomeDirectoryTests(Scratch):
    def test_simulation_matches_windows(self):
        with no_home():
            self.assertEqual(os.path.expanduser("~"), "~")
            with self.assertRaises(RuntimeError):
                Path.home()
            with self.assertRaises(RuntimeError):
                Path("~").expanduser()

    def test_home_dir_is_none_and_the_walk_reaches_the_filesystem_root(self):
        start = self.tmp / "a" / "b"
        start.mkdir(parents=True)
        with no_home():
            self.assertIsNone(paths.home_dir())
            walked = list(paths.ancestors(start))
        self.assertEqual(walked[0], start)
        self.assertEqual(walked[-1], Path(walked[-1].anchor))
        self.assertEqual(walked[-1].parent, walked[-1])
        self.assertIn(self.tmp, walked)

    def test_settings_lock_and_install_lookups_do_not_raise(self):
        root = self.tmp / "parent"
        child = root / "repo" / "src"
        child.mkdir(parents=True)
        settings = root / ".sc" / "plan-anchor" / "settings.yaml"
        settings.parent.mkdir(parents=True)
        settings.write_text("schema_version: 1\n", encoding="utf-8")
        lock = root / ".sc" / "plan-anchor" / "install-lock.json"
        lock.write_text("{}", encoding="utf-8")
        script = root / ".claude" / "skills" / "plan-anchoring" / "scripts" / "jev_judge.py"
        script.parent.mkdir(parents=True)
        script.write_text("", encoding="utf-8")
        with no_home():
            self.assertEqual(paths.find_settings(child), settings)
            self.assertEqual(paths.find_lock(child), lock)
            self.assertEqual(paths.find_installs(child), (root, [script]))
            self.assertEqual(paths.trusted_script(script, child), (True, f"nearest install {root}"))
            self.assertIsNone(paths.global_location(child))

    def test_machine_wide_globals_are_still_refused(self):
        with no_home():
            for system in paths.SYSTEM_GLOBALS:
                with self.subTest(system=system):
                    why = paths.global_location(Path(system) / "skills" / "plan-anchoring")
                    self.assertIsNotNone(why)
                    self.assertIn("global location", why)
            self.assertEqual(paths.global_roots(), [paths._resolve(Path(p)) for p in paths.SYSTEM_GLOBALS])

    def test_a_known_home_still_stops_the_walk_and_is_global(self):
        home = self.tmp / "home"
        start = home / "work" / "repo"
        start.mkdir(parents=True)
        self.assertEqual(list(paths.ancestors(start, home)), [start, home / "work"])
        self.assertIsNotNone(paths.global_location(home, home))
        self.assertIsNotNone(paths.global_location(home / ".claude" / "x", home))

    def test_settings_show_runs(self):
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        out = io.StringIO()
        with no_home(), contextlib.redirect_stdout(out):
            code = settings_mod.main(["show", "--repository-root", str(self.tmp)])
        envelope = json.loads(out.getvalue())
        if not trs.HAS_YAML:
            self.assertEqual((code, envelope["error"]["code"]), (2, "DEPENDENCY.PYYAML"))
            return
        self.assertEqual((code, envelope["success"], envelope["error"]), (0, True, None), envelope)
        self.assertIsNone(envelope["data"]["allow_remote_judge"])

    def test_live_judge_without_consent_is_the_policy_refusal(self):
        with tempfile.TemporaryDirectory() as d, no_home():
            transport = tjj.Transport()
            j = tjj.Judged(d, transport, env_values={"TYPESAFE_API_KEY": "sk-test"}, consent=False,
                           extra_args=["--repository-root", tjj.unset_repo()])
        self.assertEqual((j.code, j.out["error"]["code"]), (2, "POLICY.REMOTE_JUDGE_DISABLED"), j.out)
        self.assertEqual(transport.bodies, [])

    @unittest.skipUnless(trs.HAS_YAML, trs.NO_YAML)
    def test_recorded_consent_is_found(self):
        repo = trs.Repo(self).answer("true")
        with no_home():
            j, transport = trs.judged(self, repo)
        self.assertEqual((j.code, j.result["verdict"], len(transport.bodies)), (0, "satisfied", 1), j.out)

    def test_install_destination_check(self):
        from test_install import inst
        with no_home():
            ok = inst.check_dest(self.tmp)
            tilde = inst.check_dest(Path("~"))
            system = inst.check_dest(Path(paths.SYSTEM_GLOBALS[0])) if Path(paths.SYSTEM_GLOBALS[0]).is_dir() else None
        self.assertTrue(ok.ok, ok)
        self.assertEqual(ok.value, self.tmp)
        self.assertEqual(tilde.error.code, "INSTALL.DEST")
        self.assertIn("home directory cannot be determined", tilde.error.message)
        if system is not None:
            self.assertEqual(system.error.code, "INSTALL.DEST_GLOBAL")

    def test_session_start_hook_finds_the_lock(self):
        hook = _load("check_install_no_home", HOOK)
        repo = self.tmp / "repo"
        (repo / "src").mkdir(parents=True)
        lock = repo / ".sc" / "plan-anchor" / "install-lock.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"version": "0.0.1"}), encoding="utf-8")
        with no_home():
            line = hook.message(repo / "src")
        self.assertIsNotNone(line)
        self.assertTrue(line.startswith("plan-anchor 0.0.1 installed, "), line)


# ------------------------------------------------------------------ output encoding
class Utf8OutputTests(Scratch):
    """Each CLI's piped output is UTF-8 even when the interpreter's default is cp1252."""

    CLIS = {
        "jev_judge.py": SCRIPTS / "jev_judge.py",
        "anchor_tracker.py": SCRIPTS / "anchor_tracker.py",
        "plan_anchor_settings.py": SCRIPTS / "plan_anchor_settings.py",
        "anchor_runner_contract.py": SCRIPTS / "anchor_runner_contract.py",
        "anchor_tuning_contract.py": SCRIPTS / "anchor_tuning_contract.py",
        "install.py": INSTALL,
    }

    def run_cp1252(self, argv, **kw):
        proc = subprocess.run([sys.executable, *map(str, argv)], cwd=str(self.tmp), capture_output=True,
                              env=child_env(PYTHONIOENCODING="cp1252"), timeout=120, **kw)
        stdout = proc.stdout.decode("utf-8")  # strict: a cp1252 byte such as 0xb7 raises here
        stderr = proc.stderr.decode("utf-8")
        return proc.returncode, stdout, stderr

    BAD = f"frob{DOT}"
    USAGE = {  # argv whose usage error message quotes the non-ASCII argument back
        "jev_judge.py": [BAD],
        "anchor_tracker.py": [BAD],
        "plan_anchor_settings.py": [BAD],
        "anchor_runner_contract.py": [BAD],
        "anchor_tuning_contract.py": [BAD, "x.json"],
        "install.py": ["--dest", ".", "--tracker", BAD],
    }

    def test_usage_error_envelopes_are_utf8(self):
        self.assertEqual(set(self.USAGE), set(self.CLIS))
        for name, script in self.CLIS.items():
            with self.subTest(script=name):
                code, out, err = self.run_cp1252([script, *self.USAGE[name]])
                self.assertEqual((code, err), (2, ""), out)
                envelope = json.loads(out)
                self.assertEqual(envelope["error"]["code"], "VALIDATION.INPUT")
                self.assertIn(self.BAD, envelope["error"]["message"])

    def test_judge_report_with_a_middle_dot_is_utf8(self):
        anchors = self.tmp / "anchors.json"
        anchors.write_text(json.dumps(tjj.record(tjj.anchor())), encoding="utf-8")
        item = self.tmp / "item.txt"
        item.write_text("The runtime crates are not mentioned anywhere in this sprint.\n" * 3, encoding="utf-8")
        answers = self.tmp / "answers.json"
        answers.write_text(json.dumps({"*": tjj.plan_answers()}), encoding="utf-8")
        code, out, err = self.run_cp1252([SCRIPTS / "jev_judge.py", "judge", "--anchors", anchors, "--gate", "plan",
                                          "--all", "--item-id", "bd-1", "--item-file", item,
                                          "--answers-file", answers, "--out", self.tmp / "run.json"])
        self.assertEqual((code, err), (0, ""), out)
        self.assertIs(json.loads(out)["data"]["summary"]["pass"], True)
        # The report heading is "## Anchor gate: plan · bd-1" (the line that broke on Windows).
        code, out, err = self.run_cp1252([SCRIPTS / "jev_judge.py", "report", "--run", self.tmp / "run.json"])
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn(f"plan {DOT} bd-1", json.loads(out)["data"]["markdown"])
        code, out, err = self.run_cp1252([SCRIPTS / "jev_judge.py", "report", "--run", self.tmp / "run.json",
                                          "--format", "md"])
        self.assertEqual((code, err), (0, ""), out)
        self.assertTrue(out.startswith(f"## Anchor gate: plan {DOT} bd-1"), out)

    def test_settings_message_with_a_non_ascii_path_is_utf8(self):
        root = self.tmp / f"r{DOT}po"
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        code, out, err = self.run_cp1252([SCRIPTS / "plan_anchor_settings.py", "show", "--repository-root", root])
        self.assertEqual(err, "")
        envelope = json.loads(out)
        if envelope["success"]:
            self.assertEqual(code, 0)
        else:  # without PyYAML the settings script cannot run; the envelope is still UTF-8
            self.assertEqual((code, envelope["error"]["code"]), (2, "DEPENDENCY.PYYAML"))

    def test_session_start_hook_line_is_utf8(self):
        repo = self.tmp / f"r{DOT}po"
        repo.mkdir()
        lock = repo / ".sc" / "plan-anchor" / "install-lock.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"version": "0.0.1"}), encoding="utf-8")
        payload = json.dumps({"cwd": str(repo), "hook_event_name": "SessionStart"}, ensure_ascii=False)
        code, out, err = self.run_cp1252([HOOK], input=payload.encode("utf-8"))
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith("plan-anchor 0.0.1 installed, "), out)
        self.assertIn(f"({repo})", out)


if __name__ == "__main__":
    unittest.main()
