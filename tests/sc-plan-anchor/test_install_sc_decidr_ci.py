"""Install one pinned wheel from PyPI or its verified GitHub prerelease."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/install_sc_decidr_ci.py"
spec = importlib.util.spec_from_file_location("install_sc_decidr_ci", SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class DecidrWheelInstallerTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict("os.environ", {"RUNNER_OS": "Linux", "RUNNER_ARCH": "X64"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory()
        pin_file = Path(self.temp.name) / "decidr_client.py.j2"
        pin_file.write_text("sc_decidr_pin: 7.1.2\n", encoding="utf-8")
        self.pin = mock.patch.object(installer, "CLIENT_TEMPLATE", pin_file)
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.addCleanup(self.temp.cleanup)
        self.version = "7.1.2"

    @staticmethod
    def not_found(*_args, **_kwargs):
        error = HTTPError("url", 404, "missing", {}, None)
        error.close()
        raise error

    @staticmethod
    def download_dir(argv):
        return Path(argv[argv.index("--dir") + 1])

    def test_published_wheel_uses_the_explicit_pin(self):
        with mock.patch.object(installer, "urlopen"), mock.patch.object(installer, "run_child") as run:
            installer.main()
        run.assert_called_once_with([
            sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
            "--only-binary=:all:", "--index-url", "https://pypi.org/simple",
            f"sc-decidr=={self.version}",
        ])

    def test_prerelease_wheel_checksum_is_verified_before_install(self):
        payload = b"verified wheel bytes"
        asset = f"sc_decidr-{self.version}-cp311-abi3-manylinux_2_28_x86_64.whl"

        def download(argv):
            if argv[:3] != ["gh", "release", "download"]:
                return None
            root = self.download_dir(argv)
            (root / asset).write_bytes(payload)
            (root / "checksums.txt").write_text(f"{hashlib.sha256(payload).hexdigest()}  {asset}\n")

        with mock.patch.object(installer, "urlopen", side_effect=self.not_found), \
                mock.patch.object(installer, "run_child", side_effect=download) as run:
            installer.main()

        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][2:4], ["download", f"prerelease/v{self.version}"])
        self.assertEqual(run.call_args_list[1].args[0][-2], "--no-index")
        self.assertTrue(run.call_args_list[1].args[0][-1].endswith(asset))

    def test_corrupt_prerelease_wheel_is_refused_before_install(self):
        asset = f"sc_decidr-{self.version}-cp311-abi3-manylinux_2_28_x86_64.whl"

        def download(argv):
            if argv[:3] != ["gh", "release", "download"]:
                return None
            root = self.download_dir(argv)
            (root / asset).write_bytes(b"corrupt wheel")
            (root / "checksums.txt").write_text(f"{'0' * 64}  {asset}\n")

        with mock.patch.object(installer, "urlopen", side_effect=self.not_found), \
                mock.patch.object(installer, "run_child", side_effect=download) as run:
            with self.assertRaisesRegex(SystemExit, "Checksum verification failed"):
                installer.main()
        run.assert_called_once()

    def test_non_404_registry_error_does_not_fall_back(self):
        def unavailable(*_args, **_kwargs):
            error = HTTPError("url", 503, "unavailable", {}, None)
            error.close()
            raise error

        with mock.patch.object(installer, "urlopen", side_effect=unavailable), \
                mock.patch.object(installer, "run_child") as run:
            with self.assertRaises(HTTPError):
                installer.main()
        run.assert_not_called()

    def test_unsupported_runner_is_refused_before_network(self):
        with mock.patch.dict("os.environ", {"RUNNER_OS": "Unsupported", "RUNNER_ARCH": "X64"}), \
                mock.patch.object(installer, "urlopen") as request, \
                mock.patch.object(installer, "run_child") as run:
            with self.assertRaisesRegex(SystemExit, "No sc-decidr wheel for Unsupported/X64"):
                installer.main()
        request.assert_not_called()
        run.assert_not_called()

    def test_subprocess_timeout_is_reported(self):
        with mock.patch.object(installer.subprocess, "run", side_effect=subprocess.TimeoutExpired(["gh"], 300)):
            with self.assertRaises(SystemExit) as caught:
                installer.run_child(["gh"])
        self.assertEqual(caught.exception.code, 2)
