"""The release matrix must exercise the supported interpreter floor."""
from pathlib import Path
import unittest

try:
    import yaml
except ImportError:
    yaml = None


@unittest.skipIf(yaml is None, "PyYAML is intentionally absent in the offline dependency-floor job")
class PythonFloorTests(unittest.TestCase):
    def test_all_supported_platforms_exercise_python_311(self):
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / '.github/workflows/tests.yml').read_text(encoding='utf-8'))
        jobs = workflow['jobs']
        matrix = jobs['unit']['strategy']['matrix']['include']
        floor_platforms = {entry['os'].split('-')[0] for entry in matrix if str(entry['python']) == '3.11'}
        self.assertEqual(floor_platforms, {'ubuntu', 'macos', 'windows'})
        self.assertTrue(all(str(entry['python']) != '3.9' for entry in matrix))
        floor = jobs['dependency-floor']['steps']
        setup = next(step for step in floor if step.get('uses', '').startswith('actions/setup-python@'))
        self.assertEqual(str(setup['with']['python-version']), '3.11')
