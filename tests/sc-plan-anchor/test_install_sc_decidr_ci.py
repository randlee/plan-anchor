"""The CI prerelease installer selects a matching wheel without a network call."""
import importlib.util
from pathlib import Path
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
                               (('macOS', 'ARM64'), 'macosx_11_0_arm64')):
            with self.subTest(runner=runner), mock.patch.dict('os.environ', {'RUNNER_OS': runner[0], 'RUNNER_ARCH': runner[1]}), \
                    mock.patch.object(installer.subprocess, 'run') as run:
                installer.main()
            version = installer.client_version()
            asset = f'sc_decidr-{version}-cp311-abi3-{suffix}.whl'
            self.assertEqual(run.call_args_list, [
                mock.call(['gh', 'release', 'download', f'prerelease/v{version}', '--repo', 'randlee/sc-agent', '--pattern', asset], check=True),
                mock.call([sys.executable, '-m', 'pip', 'install', asset], check=True),
            ])

    def test_release_and_wheel_versions_follow_client_template(self):
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory) / 'decidr_client.py.j2'
            template.write_text('SC_DECIDR_VERSION = "9.8.7"\n', encoding='utf-8')
            with mock.patch.object(installer, 'CLIENT_TEMPLATE', template), \
                    mock.patch.dict('os.environ', {'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64'}), \
                    mock.patch.object(installer.subprocess, 'run') as run:
                installer.main()

        self.assertEqual(run.call_args_list, [
            mock.call(['gh', 'release', 'download', 'prerelease/v9.8.7', '--repo', 'randlee/sc-agent',
                       '--pattern', 'sc_decidr-9.8.7-cp311-abi3-manylinux_2_28_x86_64.whl'], check=True),
            mock.call([sys.executable, '-m', 'pip', 'install',
                       'sc_decidr-9.8.7-cp311-abi3-manylinux_2_28_x86_64.whl'], check=True),
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
        with mock.patch.dict('os.environ', {'RUNNER_OS': 'Windows', 'RUNNER_ARCH': 'X64'}), \
                mock.patch.object(installer.subprocess, 'run') as run:
            with self.assertRaisesRegex(SystemExit, 'Windows/X64'):
                installer.main()
        run.assert_not_called()
