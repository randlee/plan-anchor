#!/usr/bin/env python3
"""Install the pinned sc-decidr prerelease wheel on CI's supported runners."""
import os
from pathlib import Path
import re
import subprocess
import sys

CLIENT_TEMPLATE = (
    Path(__file__).resolve().parent
    / "../plugins/sc-plan-anchor/install/templates/skills/plan-anchoring/scripts/decidr_client.py.j2"
).resolve()
_CLIENT_VERSION = re.compile(r"^SC_DECIDR_VERSION\s*=\s*['\"]([^'\"]+)['\"]\s*$", re.MULTILINE)
PLATFORMS = {
    ("Linux", "X64"): "manylinux_2_28_x86_64",
    ("Linux", "ARM64"): "manylinux_2_28_aarch64",
    ("macOS", "X64"): "macosx_11_0_x86_64",
    ("macOS", "ARM64"): "macosx_11_0_arm64",
    ("Windows", "X64"): "win_amd64",
    ("Windows", "ARM64"): "win_arm64",
}


def client_version():
    """Read the wheel version recorded by the source client template."""
    source = CLIENT_TEMPLATE.read_text(encoding="utf-8")
    versions = _CLIENT_VERSION.findall(source)
    if len(versions) != 1:
        raise RuntimeError(
            f"Expected exactly one SC_DECIDR_VERSION in {CLIENT_TEMPLATE}, found {len(versions)}"
        )
    return versions[0]


def main():
    runner = (os.environ.get("RUNNER_OS"), os.environ.get("RUNNER_ARCH"))
    platform = PLATFORMS.get(runner)
    if platform is None:
        raise SystemExit(f"No sc-decidr wheel for {runner[0]}/{runner[1]}")
    version = client_version()
    asset = f"sc_decidr-{version}-cp311-abi3-{platform}.whl"
    subprocess.run(["gh", "release", "download", f"prerelease/v{version}", "--repo", "randlee/sc-agent", "--pattern", asset], check=True)
    subprocess.run([sys.executable, "-m", "pip", "install", asset], check=True)


if __name__ == "__main__":
    main()
