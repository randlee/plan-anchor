"""The real-wheel integration inputs must not install the offline wheel double."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import unittest


class LiveFixtureIsolationTests(unittest.TestCase):
    def test_real_wheel_harness_does_not_import_offline_support_module(self):
        root = Path(__file__).resolve().parents[2]
        tree = ast.parse((root / "tests/integration/test_installed_wheel.py").read_text(encoding="utf-8"))
        imported = {
            node.module for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imported.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                        for alias in node.names)
        self.assertNotIn("jev_test_support", imported)

    def test_input_builders_leave_the_sc_agent_module_untouched(self):
        tests = Path(__file__).resolve().parent
        environment = dict(os.environ, PYTHONPATH=str(tests))
        program = (
            "import sys, types; "
            "wheel = types.ModuleType('sc_agent'); sys.modules['sc_agent'] = wheel; "
            "import jev_inputs; "
            "assert sys.modules['sc_agent'] is wheel, 'fixture imports replaced the installed sc_agent wheel'"
        )
        completed = subprocess.run([sys.executable, "-c", program], cwd=tests, env=environment,
                                   capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
