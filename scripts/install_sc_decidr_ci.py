#!/usr/bin/env python3
"""Install the pinned sc-decidr prerelease wheel on CI's supported runners."""
import os
import subprocess
import sys

VERSION = "0.2.0"
PLATFORMS = {
    ("Linux", "X64"): "manylinux_2_28_x86_64",
    ("Linux", "ARM64"): "manylinux_2_28_aarch64",
    ("macOS", "X64"): "macosx_11_0_x86_64",
    ("macOS", "ARM64"): "macosx_11_0_arm64",
}


def main():
    runner = (os.environ.get("RUNNER_OS"), os.environ.get("RUNNER_ARCH"))
    platform = PLATFORMS.get(runner)
    if platform is None:
        raise SystemExit(f"No sc-decidr wheel for {runner[0]}/{runner[1]}")
    asset = f"sc_decidr-{VERSION}-cp311-abi3-{platform}.whl"
    subprocess.run(["gh", "release", "download", f"prerelease/v{VERSION}", "--repo", "randlee/sc-agent", "--pattern", asset], check=True)
    subprocess.run([sys.executable, "-m", "pip", "install", asset], check=True)


if __name__ == "__main__":
    main()
