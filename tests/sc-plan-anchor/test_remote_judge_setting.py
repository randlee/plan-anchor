"""allow_remote_judge: the committed answer that gates every live Jev call.

The repository's .sc/plan-anchor/settings.yaml records whether plan text may be
sent to TypeSafe. true lets a live call through; false and an absent answer
refuse it with POLICY.REMOTE_JUDGE_DISABLED. The old per-session opt-in
(PLAN_ANCHOR_ALLOW_REMOTE_JUDGE, --allow-remote) is gone and has no effect.

The Jev transport is the recording stub from test_jev_judge, so no network is
touched. Tests that parse a present settings file need PyYAML and skip with the
reason when it is missing; the absent-answer tests need no PyYAML. The file
name sorts after test_anchor_tracker, which reloads result.py; every result is
checked with ``.ok``, never isinstance.
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

from test_jev_judge import (  # noqa: F401 - shared helpers
    QUOTE, SKILL, STATEMENT, Judged, Transport, anchor, answer, env, jj, plan_answers, record, run_cli, write,
)
import plan_anchor_settings as settings_mod  # noqa: E402 - test_jev_judge put scripts/ on sys.path
import anchor_tracker as tracker_mod  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
SETTINGS_SCRIPT = SKILL / "scripts" / "plan_anchor_settings.py"
HAS_YAML = importlib.util.find_spec("yaml") is not None
NO_YAML = "PyYAML is not installed (python3 -m pip install pyyaml); parsing a present settings file needs it"
KEY = {"TYPESAFE_API_KEY": "sk-test-0001"}
OLD_VAR = "PLAN_ANCHOR_ALLOW_REMOTE_JUDGE"
HEADER = ("# .sc/plan-anchor/settings.yaml\n"
          "# Repository settings for the sc-plan-anchor plugin; commit this file, never put secrets in it.\n"
          "schema_version: 1\n")
REMOTE_COMMENT = "# allow_remote_judge: may plan text be sent to TypeSafe (Jev) for judging? Only the user decides it.\n"
ABSENT_ACTION = ("Ask the user once whether plan text may be sent to TypeSafe (Jev) for judging, record the answer with "
                 "`python3 scripts/plan_anchor_settings.py set allow_remote_judge true|false`, and commit "
                 ".sc/plan-anchor/settings.yaml. Never infer consent from existing run files or past runs. "
                 "Use --dry-run to inspect the request instead.")
AGENT_RULE = ("Never write `allow_remote_judge`; only the user decides it. "
              "On `POLICY.REMOTE_JUDGE_DISABLED`, return it unchanged.")


def rubric_answers():
    return {q: answer("yes", options=("no", "unclear", "yes")) for q in jj.RUBRIC_QUESTIONS}


class Repo:
    """A repository root (``.git`` marker) with an optional settings file."""

    def __init__(self, test, text=None):
        td = tempfile.TemporaryDirectory()
        test.addCleanup(td.cleanup)
        self.root = Path(td.name).resolve()
        (self.root / ".git").mkdir()
        if text is not None:
            self.write(text)

    @property
    def settings(self):
        return self.root / ".sc" / "plan-anchor" / "settings.yaml"

    def write(self, text):
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(text, encoding="utf-8")

    def answer(self, value):
        self.write(f"schema_version: 1\nallow_remote_judge: {value}\n")
        return self


def judged(test, repo, env_values=None, transport=None, extra=()):
    transport = transport if transport is not None else Transport()
    d = tempfile.mkdtemp(dir=str(repo.root))
    j = Judged(d, transport, consent=False, env_values=dict(KEY) if env_values is None else env_values,
               extra_args=["--repository-root", str(repo.root), *extra])
    return j, transport


def yaml_test(fn):
    return unittest.skipUnless(HAS_YAML, NO_YAML)(fn)


class LiveCallConsentTests(unittest.TestCase):
    @yaml_test
    def test_true_lets_the_call_through(self):
        repo = Repo(self).answer("true")
        j, t = judged(self, repo)
        self.assertEqual((j.code, j.result["verdict"], len(t.bodies)), (0, "satisfied", 1))

    @yaml_test
    def test_true_is_found_from_a_subdirectory(self):
        repo = Repo(self).answer("true")
        sub = repo.root / "doc" / "plan"
        sub.mkdir(parents=True)
        with mock.patch.object(settings_mod, "_git_toplevel", lambda start: None):
            self.assertTrue(settings_mod.remote_judge_consent(settings_mod.find_repo_root(sub).value).value)
        j, t = judged(self, repo, extra=["--repository-root", str(sub)])  # the later flag wins
        self.assertEqual((j.code, len(t.bodies)), (0, 1))

    @yaml_test
    def test_false_is_refused(self):
        repo = Repo(self).answer("false")
        j, t = judged(self, repo)
        self.assertEqual((j.code, j.out["error"]["code"], t.bodies), (2, "POLICY.REMOTE_JUDGE_DISABLED", []))
        self.assertIn("sets allow_remote_judge: false", j.out["error"]["message"])
        self.assertIn("only the user changes it", j.out["error"]["suggested_action"])

    def test_absent_file_is_refused_with_the_ask_once_action(self):
        repo = Repo(self)
        j, t = judged(self, repo)
        self.assertEqual(j.code, 2)
        self.assertEqual(j.out, {"success": False, "data": None, "error": {
            "code": "POLICY.REMOTE_JUDGE_DISABLED",
            "message": "Sending plan text to TypeSafe is disabled. The anchor statement and the item text would leave this "
                       "machine. .sc/plan-anchor/settings.yaml does not set allow_remote_judge.",
            "recoverable": False, "suggested_action": ABSENT_ACTION}})
        self.assertEqual(t.bodies, [])

    def test_absent_answer_needs_no_pyyaml(self):
        repo = Repo(self)
        with mock.patch.dict(sys.modules, {"yaml": None}):
            j, t = judged(self, repo)
        self.assertEqual((j.code, j.out["error"]["code"], t.bodies), (2, "POLICY.REMOTE_JUDGE_DISABLED", []))

    @yaml_test
    def test_file_without_the_key_is_refused_as_absent(self):
        repo = Repo(self, "schema_version: 1\nanchor_tracker: br\n")
        j, t = judged(self, repo)
        self.assertEqual((j.code, j.out["error"]["suggested_action"], t.bodies), (2, ABSENT_ACTION, []))

    def test_old_variable_has_no_effect(self):
        """Planted negative: the variable that used to opt in is set, and the call is still refused."""
        repo = Repo(self)
        j, t = judged(self, repo, env_values=dict(KEY, **{OLD_VAR: "1"}))
        self.assertEqual((j.code, j.out["error"]["code"], t.bodies), (2, "POLICY.REMOTE_JUDGE_DISABLED", []))
        if HAS_YAML:
            repo.answer("false")
            j, t = judged(self, repo, env_values=dict(KEY, **{OLD_VAR: "1"}))
            self.assertEqual((j.code, j.out["error"]["code"], t.bodies), (2, "POLICY.REMOTE_JUDGE_DISABLED", []))

    def test_old_flag_is_a_usage_error_on_every_live_subcommand(self):
        repo = Repo(self)
        anchors = write(repo.root, "anchors.json", record(anchor()))
        item = write(repo.root, "item.txt", "Sprint 2 copies the legacy runtime crates.")
        cases = {
            "judge": ["judge", "--anchors", anchors, "--gate", "plan", "--all", "--item-id", "x", "--item-file", item],
            "check-fixtures": ["check-fixtures", "--anchors", anchors, "--gate", "plan", "--all"],
            "dedupe": ["dedupe", "--anchors", anchors, "--jev"],
            "rubric": ["rubric", "--statement", STATEMENT, "--quote", QUOTE],
            "add": ["add", "--anchors", anchors, "--statement", STATEMENT, "--quote", QUOTE, "--rubric"],
        }
        t = Transport()
        for name, argv in cases.items():
            with self.subTest(name), env(**KEY), mock.patch.object(jj, "call_jev", t):
                code, out = run_cli([*argv, "--allow-remote"])
            self.assertEqual((code, out["success"], out["error"]["code"]), (2, False, "VALIDATION.INPUT"))
            self.assertIn("unrecognized arguments: --allow-remote", out["error"]["message"])
        self.assertEqual(t.bodies, [])

    def test_usage_error_through_the_script_is_json_on_stdout(self):
        proc = subprocess.run([sys.executable, str(SKILL / "scripts" / "jev_judge.py"), "judge", "--allow-remote"],
                              capture_output=True, text=True, encoding="utf-8",
                              env={k: v for k, v in os.environ.items() if k != "TYPESAFE_API_KEY"})
        self.assertEqual((proc.returncode, proc.stderr), (2, ""))
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "VALIDATION.INPUT")

    @yaml_test
    def test_invalid_value_is_a_typed_error(self):
        for value in ("'true'", "1", "null", "maybe", "[true]"):
            with self.subTest(value=value):
                repo = Repo(self).answer(value)
                j, t = judged(self, repo)
                self.assertEqual((j.code, j.out["error"]["code"], t.bodies), (2, "SETTINGS.INVALID_REMOTE_JUDGE", []))

    @yaml_test
    def test_unknown_key_is_still_rejected(self):
        repo = Repo(self, "schema_version: 1\nallow_remote_judge: true\nallow_remote: true\n")
        j, t = judged(self, repo)
        self.assertEqual((j.code, j.out["error"]["code"], t.bodies), (2, "SETTINGS.UNKNOWN_KEY", []))

    def test_missing_pyyaml_with_a_settings_file_is_dependency_error(self):
        repo = Repo(self, "schema_version: 1\nallow_remote_judge: true\n")
        with mock.patch.dict(sys.modules, {"yaml": None}):
            j, t = judged(self, repo)
        self.assertEqual((j.code, j.out["error"]["code"], t.bodies), (2, "DEPENDENCY.PYYAML", []))
        self.assertIn("python3 -m pip install pyyaml", j.out["error"]["suggested_action"])

    def test_outside_a_repository_is_a_typed_error(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(settings_mod, "_git_toplevel", lambda start: None):
                outcome = settings_mod.find_repo_root(Path(d))
            if outcome.ok:
                self.skipTest("the temporary directory is inside a repository here")
            t = Transport()
            anchors = write(d, "anchors.json", record(anchor()))
            item = write(d, "item.txt", "Sprint 2 copies the legacy runtime crates.")
            with env(**KEY), mock.patch.object(jj, "call_jev", t), \
                    mock.patch.object(settings_mod, "_git_toplevel", lambda start: None):
                code, out = run_cli(["judge", "--anchors", anchors, "--gate", "plan", "--all", "--item-id", "x",
                                     "--item-file", item, "--repository-root", d])
            self.assertEqual((code, out["error"]["code"], t.bodies), (2, "REPO.NOT_FOUND", []))

    def test_every_live_subcommand_is_refused_without_an_answer(self):
        repo = Repo(self)
        root = str(repo.root)
        a, b = STATEMENT, "The runtime crates are created by copying the legacy runtime crates and deleting the legacy modules; none is written from scratch."
        anchors = write(repo.root, "anchors.json", record(anchor(fixtures={"pass": ["x"], "fail": ["y"]}),
                                                           anchor("ANC-002", statement=b, quote="copy them")))
        cases = {
            "check-fixtures": ["check-fixtures", "--anchors", anchors, "--gate", "plan", "--all"],
            "dedupe --jev": ["dedupe", "--anchors", anchors, "--jev", "--threshold", "0.1"],
            "rubric": ["rubric", "--statement", a, "--quote", QUOTE],
            "add --rubric": ["add", "--anchors", anchors, "--statement", "The build uses cargo only.", "--quote", "cargo only",
                             "--rubric"],
        }
        t = Transport()
        for name, argv in cases.items():
            with self.subTest(name), env(**KEY), mock.patch.object(jj, "call_jev", t):
                code, out = run_cli([*argv, "--repository-root", root])
            self.assertEqual((code, out["error"]["code"], out["error"]["suggested_action"]),
                             (2, "POLICY.REMOTE_JUDGE_DISABLED", ABSENT_ACTION))
        self.assertEqual(t.bodies, [])

    def test_dry_run_and_fixture_answers_need_no_setting(self):
        with tempfile.TemporaryDirectory() as d:  # not a repository, no settings, no key
            fixture = write(d, "answers.json", {"*": plan_answers()})
            missing = str(Path(d) / "no-such-dir")
            for extra in (["--dry-run"], ["--answers-file", fixture]):
                with self.subTest(extra=extra):
                    t = Transport()
                    j = Judged(d, t, consent=False, env_values={}, extra_args=[*extra, "--repository-root", missing])
                    self.assertEqual((j.code, t.bodies), (0, []))
            rubric = write(d, "rubric.json", {"*": rubric_answers()})
            with env():
                code, out = run_cli(["rubric", "--statement", STATEMENT, "--quote", QUOTE, "--answers-file", rubric])
            self.assertEqual(code, 0, out)
            with mock.patch.dict(sys.modules, {"yaml": None}):
                j = Judged(d, Transport(), consent=False, env_values={}, extra_args=["--dry-run"])
            self.assertEqual(j.code, 0)


@unittest.skipUnless(HAS_YAML, NO_YAML)
class SetCommandTests(unittest.TestCase):
    def main(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = settings_mod.main(list(argv))
        return code, json.loads(buf.getvalue())

    def test_set_true_writes_the_committed_form_and_reads_back(self):
        repo = Repo(self)
        code, out = self.main("set", "allow_remote_judge", "true", "--repository-root", str(repo.root))
        self.assertEqual(code, 0, out)
        self.assertEqual((out["data"]["value"], out["data"]["previous"], out["data"]["written"], out["data"]["commit_paths"]),
                         (True, None, True, [".sc/plan-anchor/settings.yaml"]))
        self.assertEqual(repo.settings.read_text(encoding="utf-8"), HEADER + REMOTE_COMMENT + "allow_remote_judge: true\n")
        code, out = self.main("show", "--repository-root", str(repo.root))
        self.assertEqual((code, out["data"]["allow_remote_judge"], out["data"]["anchor_tracker"]), (0, True, None))
        self.assertTrue(settings_mod.remote_judge_consent(repo.root).value)

    def test_set_false_keeps_the_tracker_and_reports_the_change(self):
        repo = Repo(self, HEADER + "anchor_tracker: br\n")
        self.main("set", "allow_remote_judge", "true", "--repository-root", str(repo.root))
        code, out = self.main("set", "allow_remote_judge", "false", "--repository-root", str(repo.root))
        self.assertEqual((code, out["data"]["previous"], out["data"]["value"], out["data"]["written"]), (0, True, False, True))
        self.assertEqual(repo.settings.read_text(encoding="utf-8"),
                         HEADER + "anchor_tracker: br\n" + REMOTE_COMMENT + "allow_remote_judge: false\n")
        code, out = self.main("set", "allow_remote_judge", "false", "--repository-root", str(repo.root))
        self.assertEqual((code, out["data"]["written"], out["data"]["commit_paths"]), (0, False, []))

    def test_bad_arguments_are_validation_input(self):
        repo = Repo(self)
        for argv in (["set", "allow_remote_judge", "yes"], ["set", "allow_remote_judge", "True"],
                     ["set", "anchor_tracker", "br"], ["set", "allow_remote_judge"], ["delete"]):
            with self.subTest(argv=argv):
                code, out = self.main(*argv, "--repository-root", str(repo.root))
                self.assertEqual((code, out["error"]["code"]), (2, "VALIDATION.INPUT"))
        self.assertFalse(repo.settings.exists())

    def test_a_malformed_file_is_never_overwritten(self):
        for text, code_expected in (("schema_version: [1\n", "SETTINGS.MALFORMED"),
                                    ("schema_version: 1\nfast: 1\n", "SETTINGS.UNKNOWN_KEY"),
                                    ("schema_version: 2\n", "SETTINGS.SCHEMA_VERSION"),
                                    ("schema_version: 1\nallow_remote_judge: 'no'\n", "SETTINGS.INVALID_REMOTE_JUDGE")):
            with self.subTest(text=text):
                repo = Repo(self, text)
                code, out = self.main("set", "allow_remote_judge", "true", "--repository-root", str(repo.root))
                self.assertEqual((code, out["error"]["code"]), (2, code_expected))
                self.assertEqual(repo.settings.read_text(encoding="utf-8"), text)

    def test_missing_pyyaml_is_a_typed_error(self):
        repo = Repo(self)
        with mock.patch.dict(sys.modules, {"yaml": None}):
            code, out = self.main("set", "allow_remote_judge", "true", "--repository-root", str(repo.root))
        self.assertEqual((code, out["error"]["code"]), (2, "DEPENDENCY.PYYAML"))
        self.assertFalse(repo.settings.exists())

    def test_the_script_runs_end_to_end(self):
        repo = Repo(self)
        subprocess.run(["git", "init", "-q", str(repo.root)], check=False, capture_output=True)
        proc = subprocess.run([sys.executable, str(SETTINGS_SCRIPT), "set", "allow_remote_judge", "true",
                               "--repository-root", str(repo.root)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["data"]["written"])
        self.assertIn("allow_remote_judge: true\n", repo.settings.read_text(encoding="utf-8"))

    def test_anchor_tracker_write_keeps_the_answer(self):
        repo = Repo(self, "schema_version: 1\nallow_remote_judge: true\n")
        with mock.patch.object(settings_mod, "_git_toplevel", lambda start: None):
            outcome = tracker_mod.write(repo.root, which=lambda name: f"/fake/bin/{name}", run=lambda *a, **k: None)
        self.assertTrue(outcome.ok, getattr(outcome, "error", None))
        self.assertEqual(repo.settings.read_text(encoding="utf-8"),
                         HEADER + "anchor_tracker: br\n" + REMOTE_COMMENT + "allow_remote_judge: true\n")

    def test_schema_version_stays_one(self):
        self.assertEqual(settings_mod.SCHEMA_VERSION, 1)
        self.assertIn("allow_remote_judge", settings_mod.ALLOWED_KEYS)


class PromptAndDocsTests(unittest.TestCase):
    """The old opt-in is gone from every shipped file; agents get the one rule."""

    def shipped_text_files(self):
        for path in sorted(PLUGIN.rglob("*")):
            if path.is_file() and path.suffix in {".md", ".j2", ".py", ".yaml", ".json"} and "__pycache__" not in path.parts:
                yield path

    def test_no_shipped_file_names_the_old_variable_or_flag(self):
        for path in [*self.shipped_text_files(), ROOT / "README.md"]:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertNotIn(OLD_VAR, text)
                self.assertNotRegex(text, r"--allow-remote(?!-judge)")

    def test_gate_agents_carry_the_rule(self):
        agents = [*PLUGIN.glob(".*/agents/anchor-*-review.md"), *(PLUGIN / "install" / "templates" / "agents").glob("anchor-*-review.md.j2")]
        self.assertEqual(len(agents), 8)
        for path in agents:
            with self.subTest(path=path.name, harness=path.parent.parent.name):
                self.assertIn(AGENT_RULE, path.read_text(encoding="utf-8"))

    def test_skill_asks_once_and_never_infers(self):
        for path in (SKILL / "SKILL.md", PLUGIN / "install" / "templates" / "skills" / "plan-anchoring" / "SKILL.md.j2"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn("plan_anchor_settings.py\" set allow_remote_judge true|false", text)
                self.assertIn("ask the user once", text)
                self.assertIn("Never infer consent from existing run files", text)

    def test_this_repository_records_true(self):
        text = (ROOT / ".sc" / "plan-anchor" / "settings.yaml").read_text(encoding="utf-8")
        self.assertIn("\nallow_remote_judge: true\n", text)


if __name__ == "__main__":
    unittest.main()
