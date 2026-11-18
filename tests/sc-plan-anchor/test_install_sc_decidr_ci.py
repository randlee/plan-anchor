"""The CI PyPI installer selects a matching published wheel without a network call."""
import contextlib
import io
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/install_sc_decidr_ci.py"
spec = importlib.util.spec_from_file_location("install_sc_decidr_ci", SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class DecidrWheelInstallerTests(unittest.TestCase):
    def test_supported_runners_download_and_install_the_same_pinned_wheel(self):
        for runner, suffix in ((('Linux', 'X64'), 'manylinux_2_28_x86_64'),
                               (('Linux', 'ARM64'), 'manylinux_2_28_aarch64'),
                               (('macOS', 'X64'), 'macosx_11_0_x86_64'),
                               (('macOS', 'ARM64'), 'macosx_11_0_arm64'),
                               (('Windows', 'X64'), 'win_amd64'),
                               (('Windows', 'ARM64'), 'win_arm64')):
            with self.subTest(runner=runner), mock.patch.dict('os.environ', {'RUNNER_OS': runner[0], 'RUNNER_ARCH': runner[1]}), \
                    mock.patch.object(installer.subprocess, 'run') as run:
                installer.main()
            version = installer.client_version()
            self.assertEqual(run.call_args_list, [
                mock.call([sys.executable, '-m', 'pip', 'install', '--index-url', 'https://pypi.org/simple',
                           '--only-binary=:all:', f'sc-decidr=={version}'], check=True,
                          stdin=subprocess.DEVNULL, timeout=installer.COMMAND_TIMEOUT_SECONDS),
            ])

    def test_command_timeouts_are_typed(self):
        for runner in (('Linux', 'X64'), ('Windows', 'ARM64')):
            with self.subTest(runner=runner), \
                    mock.patch.dict('os.environ', {'RUNNER_OS': runner[0], 'RUNNER_ARCH': runner[1]}):
                timed_out = subprocess.TimeoutExpired('child', installer.COMMAND_TIMEOUT_SECONDS)
                err = io.StringIO()
                with mock.patch.object(installer.subprocess, 'run', side_effect=timed_out) as run, \
                        contextlib.redirect_stderr(err):
                    code = installer.run()
                self.assertEqual(code, 2)
                self.assertIn('timed out after 300 seconds', err.getvalue())
                self.assertNotIn('Traceback', err.getvalue())
                self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
                self.assertEqual(run.call_args.kwargs['timeout'], installer.COMMAND_TIMEOUT_SECONDS)
                self.assertEqual(run.call_count, 1)

    def test_release_and_wheel_versions_follow_client_template(self):
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory) / 'decidr_client.py.j2'
            template.write_text('SC_DECIDR_VERSION = "9.8.7"\n', encoding='utf-8')
            with mock.patch.object(installer, 'CLIENT_TEMPLATE', template), \
                    mock.patch.dict('os.environ', {'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64'}), \
                    mock.patch.object(installer.subprocess, 'run') as run:
                installer.main()

        self.assertEqual(run.call_args_list, [
            mock.call([sys.executable, '-m', 'pip', 'install', '--index-url', 'https://pypi.org/simple',
                       '--only-binary=:all:', 'sc-decidr==9.8.7'], check=True,
                       stdin=subprocess.DEVNULL, timeout=installer.COMMAND_TIMEOUT_SECONDS),
        ])

    def test_client_template_must_define_one_version(self):
        for source in ('# no version\n', 'SC_DECIDR_VERSION = "0.2.2"\nSC_DECIDR_VERSION = "0.2.3"\n'):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                template = Path(directory) / 'decidr_client.py.j2'
                template.write_text(source, encoding='utf-8')
                with mock.patch.object(installer, 'CLIENT_TEMPLATE', template):
                    with self.assertRaisesRegex(RuntimeError, 'Expected exactly one SC_DECIDR_VERSION'):
                        installer.client_version()

    def test_unsupported_runner_is_refused_before_download(self):
        with mock.patch.dict('os.environ', {'RUNNER_OS': 'Unsupported', 'RUNNER_ARCH': 'X64'}), \
                mock.patch.object(installer.subprocess, 'run') as run:
            with self.assertRaisesRegex(SystemExit, 'Unsupported/X64'):
                installer.main()
        run.assert_not_called()
