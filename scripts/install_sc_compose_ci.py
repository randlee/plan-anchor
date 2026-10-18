#!/usr/bin/env python3
"""Install the pinned sc-compose CLI release on GitHub-hosted CI runners."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile


VERSION = "1.7.0"
ASSETS = {
    ("linux", "x86_64"): (
        f"sc-compose_{VERSION}_x86_64-unknown-linux-gnu.tar.gz",
        "5e2ffeb47072b26c47a44bfcc0d7068d0dfb8d5742feecc309fc535dab2e1c84",
    ),
    ("linux", "aarch64"): (
        f"sc-compose_{VERSION}_aarch64-unknown-linux-gnu.tar.gz",
        "fa2cd0247c78954a6f0d83dcf053a0405adda65dddbe5b9da820b4ed71c0b32a",
    ),
    ("darwin", "x86_64"): (
        f"sc-compose_{VERSION}_x86_64-apple-darwin.tar.gz",
        "6e32de8ee1fe627e64bd68f85dd4ba85d18fae2a8627d9dd8aeb4c42bdde674a",
    ),
    ("darwin", "aarch64"): (
        f"sc-compose_{VERSION}_aarch64-apple-darwin.tar.gz",
        "d7590a41921bef5a428bcbd33dda48006c6f6df5eafa83217cb820240fe6544b",
    ),
    ("win32", "x86_64"): (
        f"sc-compose_{VERSION}_x86_64-pc-windows-msvc.zip",
        "80027b651ef86f2abe9ca88a16635fd53994fc0e9ec3c6c14d56ab151cbb3111",
    ),
}


def normalized_machine() -> str:
    machine = platform.machine().lower()
    return {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)


def safe_member(name: str) -> None:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError("release archive contains an unsafe path")


def extract(archive: Path, destination: Path) -> None:
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                safe_member(member.filename)
            bundle.extractall(destination)
    else:
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                safe_member(member.name)
                if member.issym() or member.islnk():
                    raise RuntimeError("release archive must not contain links")
            bundle.extractall(destination)


def main() -> int:
    key = (sys.platform, normalized_machine())
    if key not in ASSETS:
        raise RuntimeError(f"unsupported CI platform: {key[0]} {key[1]}")
    asset, expected = ASSETS[key]
    runner_temp = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    install_dir = runner_temp / f"sc-compose-{VERSION}-bin"
    install_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runner_temp) as temporary:
        archive = Path(temporary) / asset
        subprocess.run(
            [
                "gh", "release", "download", f"v{VERSION}",
                "--repo", "randlee/sc-compose",
                "--pattern", asset,
                "--dir", temporary,
            ],
            check=True,
        )
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError("sc-compose release checksum mismatch")
        extracted = Path(temporary) / "extracted"
        extracted.mkdir()
        extract(archive, extracted)
        executable_name = "sc-compose.exe" if sys.platform == "win32" else "sc-compose"
        matches = [path for path in extracted.rglob(executable_name) if path.is_file()]
        if len(matches) != 1:
            raise RuntimeError("sc-compose release archive lacks one executable")
        target = install_dir / executable_name
        shutil.copy2(matches[0], target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    version = subprocess.run([str(target), "--version"], capture_output=True, text=True, check=True).stdout.strip()
    if version != f"sc-compose {VERSION}":
        raise RuntimeError(f"unexpected sc-compose version: {version}")
    github_path = os.environ.get("GITHUB_PATH")
    if github_path:
        with open(github_path, "a", encoding="utf-8") as handle:
            handle.write(str(install_dir) + "\n")
    print(version)
    print(f"installed to {install_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError, tarfile.TarError, zipfile.BadZipFile) as exc:
        # exit 2, like every plan-anchor CLI: the install could not be done (there is no exit 1)
        print(f"install_sc_compose_ci: {exc}", file=sys.stderr)
        raise SystemExit(2)
