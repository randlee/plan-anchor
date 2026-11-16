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


VERSION = "1.8.0"
ASSETS = {
    ("linux", "x86_64"): (
        f"sc-compose_{VERSION}_x86_64-unknown-linux-gnu.tar.gz",
        "a12a16259c1cab58c4c611320653e442fe3440c2a15cce0ba617ad77d145809a",
    ),
    ("linux", "aarch64"): (
        f"sc-compose_{VERSION}_aarch64-unknown-linux-gnu.tar.gz",
        "b4a909d0638914856a6e3c21598d4ee9f78e2a1d9b6d6aefb3d3d624a496c3f1",
    ),
    ("darwin", "x86_64"): (
        f"sc-compose_{VERSION}_x86_64-apple-darwin.tar.gz",
        "5f70b67b35e2c3f8e2784a7aea631fbf1ca0cf91f8378e4f1b44f96242a9d057",
    ),
    ("darwin", "aarch64"): (
        f"sc-compose_{VERSION}_aarch64-apple-darwin.tar.gz",
        "c7b03453d357f36997b27467b02cfe6124713ca1ee9344175c31f8e0dc5f5408",
    ),
    ("win32", "x86_64"): (
        f"sc-compose_{VERSION}_x86_64-pc-windows-msvc.zip",
        "987c33e1a8d66d364c3a3b85e8e54b10f47d60321ac464cd87a15b9245a91335",
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


def run(entry=None) -> int:
    """main() with the plan-anchor exit convention: 0 installed, 2 for any failure (never 1, never a traceback)."""
    try:
        return (entry or main)()
    except (RuntimeError, OSError, subprocess.CalledProcessError, tarfile.TarError, zipfile.BadZipFile) as exc:
        # exit 2, like every plan-anchor CLI: the install could not be done (there is no exit 1)
        print(f"install_sc_compose_ci: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - anything else is still "could not install", not a traceback
        print(f"install_sc_compose_ci: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
