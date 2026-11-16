"""Offline input-validation checks for the manual live runner."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class IntegrationRunnerInputs(unittest.TestCase):
    def test_missing_renderer_names_file_and_consumes_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            credentials = root / 'credentials.env'
            credentials.write_text('EXPLICIT_TEST_KEY=synthetic-secret\n')
            source = root / 'absent-source'
            result = subprocess.run(
                [sys.executable, str(ROOT / 'scripts/integration.py'),
                 '--venv', str(root / 'unused-venv'), '--env-file', str(credentials),
                 '--key-variable', 'EXPLICIT_TEST_KEY', '--sc-agent-source', str(source),
                 '--source-sha', 'test-plan-anchor', '--pin-tag', 'prerelease/vtest',
                 '--pin-sha', 'test-sdk', '--platform', 'macos',
                 '--results', str(root / 'results')],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(str(source / 'templates/integration-report/render.py'), result.stderr)
            self.assertNotIn('synthetic-secret', result.stdout + result.stderr)
            self.assertFalse(credentials.exists())
            self.assertFalse((root / 'results').exists())
