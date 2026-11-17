"""Offline input-validation checks for the manual live runner."""
import subprocess
import sys
import tempfile
import unittest
import importlib.util
import os
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


class IntegrationRunnerInputs(unittest.TestCase):
    def test_runner_requests_shared_run_page_and_index(self):
        spec = importlib.util.spec_from_file_location('integration_runner', ROOT / 'scripts/integration.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            credentials = root / 'credentials.env'
            credentials.write_text('EXPLICIT_TEST_KEY=synthetic-secret\n')
            renderer = root / 'sdk/templates/integration-report/render.py'
            renderer.parent.mkdir(parents=True)
            renderer.touch()
            argv = ['integration.py', '--venv', str(root / 'venv'), '--env-file', str(credentials),
                    '--key-variable', 'EXPLICIT_TEST_KEY', '--sc-agent-source', str(root / 'sdk'),
                    '--source-sha', 'source', '--pin-tag', 'prerelease/v0.2.5', '--pin-sha', 'wheel',
                    '--platform', 'macos', '--results', str(root / 'results')]
            with mock.patch.object(runner, 'ROOT', root), mock.patch.object(sys, 'argv', argv), \
                    mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(runner.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run:
                self.assertEqual(runner.main(), 0)
            self.assertEqual(run.call_count, 2)
            command = run.call_args_list[1].args[0]
            self.assertEqual(command[1], str(renderer))
            self.assertEqual(command[command.index('--reports-dir') + 1], str(root / 'site/reports'))
            self.assertEqual(command[command.index('--title') + 1], 'Plan-anchor integration report')
            self.assertEqual(command[command.index('--output') + 1], str(root / 'site/reports/integration/macos.xhtml'))
            self.assertFalse(credentials.exists())

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
