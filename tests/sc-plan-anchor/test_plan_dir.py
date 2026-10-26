"""The anchor record lives in the current phase folder, docs/plans/phase-<current>/ (REQ-082).

``plan_dir`` in .sc/plan-anchor/settings.yaml names that folder with the phase id
written out (docs/plans/phase-b). The skill reads it as ``$P`` and sets
``A="$P/anchors.json"``; no shipped file names a literal folder. ``add`` takes the
new record's ``plan`` and ``intent_ref`` from ``--anchors``. Settings tests need
PyYAML and skip with the reason when it is missing.
"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_jev_judge import QUOTE, STATEMENT, run_cli  # noqa: F401 - puts scripts/ on sys.path
import plan_anchor_settings as settings_mod  # noqa: E402
import anchor_tracker as tracker_mod  # noqa: E402
from layout_support import TEST_TRACKER, TRACKERS, TARGETS, rendered_agent, rendered_skill  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
HAS_YAML = importlib.util.find_spec("yaml") is not None
NO_YAML = "PyYAML is not installed (python3 -m pip install pyyaml); parsing a present settings file needs it"
OLD_LITERALS = ("phase-current", "doc/plan/")
BAD = ("docs/plans/phase-<current>", "../plans", "docs/../x", "/abs/plans", "docs/plans/", "docs//plans",
       "docs\\plans", "C:/plans", " docs/plans/phase-b", "")


class Repo:
    def __init__(self, test, text=None):
        td = tempfile.TemporaryDirectory()
        test.addCleanup(td.cleanup)
        self.root = Path(td.name).resolve()
        (self.root / ".git").mkdir()
        if text is not None:
            self.settings.parent.mkdir(parents=True, exist_ok=True)
            self.settings.write_text(text, encoding="utf-8")

    @property
    def settings(self):
        return self.root / ".sc" / "plan-anchor" / "settings.yaml"


def main(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = settings_mod.main(list(argv))
    return code, json.loads(buf.getvalue())


@unittest.skipUnless(HAS_YAML, NO_YAML)
class PlanDirSettingTests(unittest.TestCase):
    def test_set_records_the_phase_folder_and_show_reports_it(self):
        repo = Repo(self, "schema_version: 1\nallow_remote_judge: true\n")
        code, out = main("show", "--repository-root", str(repo.root))
        self.assertEqual((code, out["data"]["plan_dir"]), (0, None))
        code, out = main("set", "plan_dir", "docs/plans/phase-b", "--repository-root", str(repo.root))
        self.assertEqual((code, out["data"]["value"], out["data"]["previous"], out["data"]["written"]),
                         (0, "docs/plans/phase-b", None, True))
        text = repo.settings.read_text(encoding="utf-8")
        self.assertIn("\nallow_remote_judge: true\n", text)
        self.assertTrue(text.endswith('\nplan_dir: "docs/plans/phase-b"\n'), text)
        code, out = main("show", "--repository-root", str(repo.root))
        self.assertEqual((code, out["data"]["plan_dir"], out["data"]["allow_remote_judge"]), (0, "docs/plans/phase-b", True))
        code, out = main("set", "plan_dir", "docs/plans/phase-c", "--repository-root", str(repo.root))
        self.assertEqual((code, out["data"]["previous"], out["data"]["written"]), (0, "docs/plans/phase-b", True))
        code, out = main("set", "allow_remote_judge", "false", "--repository-root", str(repo.root))
        self.assertEqual(code, 0, out)
        self.assertIn('\nplan_dir: "docs/plans/phase-c"\n', repo.settings.read_text(encoding="utf-8"))

    def test_a_hand_written_unquoted_path_reads_as_a_string(self):
        repo = Repo(self, "schema_version: 1\nplan_dir: docs/plans/phase-b\n")
        code, out = main("show", "--repository-root", str(repo.root))
        self.assertEqual((code, out["data"]["plan_dir"]), (0, "docs/plans/phase-b"))

    def test_set_refuses_a_placeholder_or_unsafe_path_and_writes_nothing(self):
        repo = Repo(self)
        for value in BAD:
            with self.subTest(value=value):
                code, out = main("set", "plan_dir", value, "--repository-root", str(repo.root))
                self.assertEqual((code, out["error"]["code"]), (2, "VALIDATION.INPUT"), out)
        self.assertFalse(repo.settings.exists())

    def test_a_bad_file_value_is_a_typed_error(self):
        for value in (*(json.dumps(v) for v in BAD), "2", "[docs]", "null"):
            with self.subTest(value=value):
                repo = Repo(self, f"schema_version: 1\nplan_dir: {value}\n")
                code, out = main("show", "--repository-root", str(repo.root))
                self.assertEqual((code, out["error"]["code"]), (2, "SETTINGS.INVALID_PLAN_DIR"), out)

    def test_values_that_yaml_would_retype_round_trip_as_strings(self):
        for value in ("yes", "2026", "null", "docs/plans/phase-é"):
            with self.subTest(value=value):
                s = settings_mod.Settings(1, None, None, value)
                yaml = settings_mod.load_yaml().value
                self.assertEqual(settings_mod.parse_settings(settings_mod.render_settings(s), yaml).value, s)

    def test_anchor_tracker_write_keeps_the_plan_dir(self):
        repo = Repo(self, "schema_version: 1\nallow_remote_judge: true\nplan_dir: docs/plans/phase-b\n")
        if TEST_TRACKER == "bd":  # a bd install needs a Dolt-backed .beads/
            (repo.root / ".beads").mkdir()
            (repo.root / ".beads" / "metadata.json").write_text('{"backend": "dolt"}', encoding="utf-8")
        with mock.patch.object(settings_mod, "_git_toplevel", lambda start: None):
            outcome = tracker_mod.write(repo.root, which=lambda name: f"/fake/bin/{name}", run=lambda *a, **k: None)
        self.assertTrue(outcome.ok, getattr(outcome, "error", None))
        text = repo.settings.read_text(encoding="utf-8")
        self.assertIn(f"\nanchor_tracker: {TEST_TRACKER}\n", text)
        self.assertTrue(text.endswith('\nplan_dir: "docs/plans/phase-b"\n'), text)


class AddDefaultsTests(unittest.TestCase):
    def test_a_new_record_takes_plan_and_intent_from_the_anchors_path(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "docs" / "plans" / "phase-b" / "anchors.json"
            path.parent.mkdir(parents=True)
            code, out = run_cli(["add", "--anchors", str(path), "--statement", STATEMENT, "--quote", QUOTE])
            self.assertEqual(code, 0, out)
            rec = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual((rec["plan"], rec["intent_ref"]),
                             ("phase-b", (path.parent / "intent.md").as_posix()))

    def test_explicit_plan_and_intent_still_win(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "anchors.json"
            code, out = run_cli(["add", "--anchors", str(path), "--statement", STATEMENT, "--quote", QUOTE,
                                 "--plan", "phase-z", "--intent-ref", "docs/plans/phase-z/intent.md"])
            self.assertEqual(code, 0, out)
            rec = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual((rec["plan"], rec["intent_ref"]), ("phase-z", "docs/plans/phase-z/intent.md"))


class ShippedTextTests(unittest.TestCase):
    def test_no_shipped_file_names_a_literal_phase_folder(self):
        paths = [p for p in sorted(PLUGIN.rglob("*")) if p.is_file() and "__pycache__" not in p.parts
                 and p.suffix in {".md", ".j2", ".py", ".json", ".yaml"}]
        self.assertGreater(len(paths), 40)
        for path in [*paths, ROOT / "README.md"]:
            text = path.read_text(encoding="utf-8")
            for literal in OLD_LITERALS:
                with self.subTest(path=path.relative_to(ROOT).as_posix(), literal=literal):
                    self.assertNotIn(literal, text)

    def test_the_skill_reads_plan_dir_and_derives_the_anchors_path(self):
        for tracker in TRACKERS:
            text = (rendered_skill(tracker) / "SKILL.md").read_text(encoding="utf-8")
            with self.subTest(tracker=tracker):
                self.assertIn("show | jq -r '.data.plan_dir // empty')\"", text)
                self.assertIn('A="$P/anchors.json"', text)
                self.assertIn("`docs/plans/phase-<current>`", text)
                self.assertIn("set plan_dir docs/plans/phase-<id>", text)

    def test_gate_agents_default_to_the_plan_dir(self):
        for tracker in TRACKERS:
            for target in TARGETS:
                for name in ("anchor-plan-review.md", "anchor-sprint-review.md"):
                    text = rendered_agent(tracker, target, name).read_text(encoding="utf-8")
                    with self.subTest(tracker=tracker, target=target, name=name):
                        self.assertIn("use `<plan_dir>/anchors.json`", text)
                        self.assertIn("docs/plans/phase-<current>/anchors.json", text)


if __name__ == "__main__":
    unittest.main()
