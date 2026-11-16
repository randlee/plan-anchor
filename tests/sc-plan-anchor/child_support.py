"""Bound test subprocesses without changing their inputs or shorter timeouts."""
import subprocess

HANG_GUARD_SECONDS = 60


def run_test_child(args, **options):
    timeout = options.pop("timeout", HANG_GUARD_SECONDS)
    if timeout is None or timeout > HANG_GUARD_SECONDS:
        raise ValueError("test child timeout must be at most 60 seconds")
    if options.get("input") is None:
        options.setdefault("stdin", subprocess.DEVNULL)
    try:
        return subprocess.run(args, timeout=timeout, **options)
    except subprocess.TimeoutExpired as error:
        raise AssertionError(f"test child timed out after {error.timeout} seconds: {error.cmd!r}") from error
