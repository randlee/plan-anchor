#!/usr/bin/env python3
"""Install the pinned sc-decidr wheel from PyPI or its verified GitHub prerelease."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.error import HTTPError
from urllib.request import urlopen

CLIENT_TEMPLATE = (Path(__file__).resolve().parent.parent
                   / "plugins/sc-plan-anchor/install/templates/skills/plan-anchoring/scripts/decidr_client.py.j2")
TIMEOUT_SECONDS = 300
PLATFORMS = {
    ("Linux", "X64"): "manylinux_2_28_x86_64",
    ("Linux", "ARM64"): "manylinux_2_28_aarch64",
    ("macOS", "X64"): "macosx_11_0_x86_64",
    ("macOS", "ARM64"): "macosx_11_0_arm64",
    ("Windows", "X64"): "win_amd64",
    ("Windows", "ARM64"): "win_arm64",
}


def run_child(argv):
    try:
        return subprocess.run(argv, check=True, stdin=subprocess.DEVNULL, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        print(f"install_sc_decidr_ci: subprocess timed out after {exc.timeout}s: {exc.cmd!r}", file=sys.stderr)
        raise SystemExit(2) from None


def install_prerelease(version, platform, install):
    asset = f"sc_decidr-{version}-cp311-abi3-{platform}.whl"
    with tempfile.TemporaryDirectory(prefix="sc-decidr-ci-") as directory:
        root = Path(directory)
        run_child(["gh", "release", "download", f"prerelease/v{version}", "--repo", "randlee/sc-agent",
                   "--pattern", asset, "--pattern", "checksums.txt", "--dir", str(root)])
        matches = [line.split() for line in (root / "checksums.txt").read_text(encoding="utf-8").splitlines()
                   if len(line.split()) == 2 and line.split()[1] == asset]
        if len(matches) != 1 or hashlib.sha256((root / asset).read_bytes()).hexdigest() != matches[0][0]:
            raise SystemExit(f"Checksum verification failed for {asset}")
        run_child([*install, "--no-index", str(root / asset)])


def main():
    source = CLIENT_TEMPLATE.read_text(encoding="utf-8")
    pins = re.findall(r"^sc_decidr_pin:\s*([0-9]+\.[0-9]+\.[0-9]+)\s*$", source, re.M)
    if len(pins) != 1:
        raise SystemExit(f"Expected exactly one sc_decidr_pin in {CLIENT_TEMPLATE}")
    version = pins[0]
    runner = (os.environ.get("RUNNER_OS"), os.environ.get("RUNNER_ARCH"))
    platform = PLATFORMS.get(runner)
    if platform is None:
        raise SystemExit(f"No sc-decidr wheel for {runner[0]}/{runner[1]}")
    install = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
               "--only-binary=:all:"]
    try:
        with urlopen(f"https://pypi.org/pypi/sc-decidr/{version}/json", timeout=30):
            pass
    except HTTPError as exc:
        not_published = exc.code == 404
        exc.close()
        if not not_published:
            raise
        install_prerelease(version, platform, install)
    else:
        run_child([*install, "--index-url", "https://pypi.org/simple", f"sc-decidr=={version}"])


if __name__ == "__main__":
    main()
