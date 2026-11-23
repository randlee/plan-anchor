"""Bound test subprocesses without changing their inputs or shorter timeouts."""
import os
from pathlib import Path
import subprocess

HANG_GUARD_SECONDS = 60


def run_test_child(args, **options):
    timeout = options.pop("timeout", HANG_GUARD_SECONDS)
    if timeout is None or timeout > HANG_GUARD_SECONDS:
        raise ValueError("test child timeout must be at most 60 seconds")
    if options.get("input") is None:
        options.setdefault("stdin", subprocess.DEVNULL)
    environment = dict(options.get("env") or os.environ)
    test_support = str(Path(__file__).resolve().parent)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(part for part in (test_support, existing) if part)
    options["env"] = environment
    try:
        return subprocess.run(args, timeout=timeout, **options)
    except subprocess.TimeoutExpired as error:
        raise AssertionError(f"test child timed out after {error.timeout} seconds: {error.cmd!r}") from error
