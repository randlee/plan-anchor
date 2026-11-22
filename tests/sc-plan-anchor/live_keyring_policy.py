"""Policy for reporting the optional platform keyring case in live integration."""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from typing import Any


def secret_service_available(
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    which=None,
    run=None,
) -> bool | None:
    """Return Linux Secret Service presence, or None when it cannot be checked.

    Secret Service is reached through the session D-Bus. No session bus proves
    that this process cannot reach Secret Service. If there is a bus, ask D-Bus
    directly whether the service owns its well-known name; do not infer service
    absence from the keyring lookup error being assessed.
    """
    current_platform = sys.platform if platform is None else platform
    if current_platform != "linux":
        return None
    env = os.environ if environ is None else environ
    if not env.get("DBUS_SESSION_BUS_ADDRESS"):
        return False
    find_executable = shutil.which if which is None else which
    run_process = subprocess.run if run is None else run
    gdbus = find_executable("gdbus")
    if gdbus is None:
        return None
    try:
        result = run_process(
            [gdbus, "call", "--session", "--dest", "org.freedesktop.DBus",
             "--object-path", "/org/freedesktop/DBus", "--method",
             "org.freedesktop.DBus.NameHasOwner", "org.freedesktop.secrets"],
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=5,
            env=dict(env),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    if output in {"(true,)", "true"}:
        return True
    if output not in {"(false,)", "false"}:
        return None
    try:
        activatable = run_process(
            [gdbus, "call", "--session", "--dest", "org.freedesktop.DBus",
             "--object-path", "/org/freedesktop/DBus", "--method",
             "org.freedesktop.DBus.ListActivatableNames"],
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=5,
            env=dict(env),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if activatable.returncode != 0:
        return None
    try:
        names = ast.literal_eval(activatable.stdout.strip())
    except (SyntaxError, ValueError):
        return None
    if not isinstance(names, tuple) or len(names) != 1 or not isinstance(names[0], list):
        return None
    return "org.freedesktop.secrets" in names[0]


def keyring_case_result(error_id: str | None, service_available: bool | None) -> str:
    """Classify the live default-keyring outcome without hiding real failures."""
    if error_id is None:
        return "success"
    if error_id == "secrets.keyring_timeout":
        return "secrets.keyring_timeout"
    if error_id == "secrets.keyring_read" and service_available is False:
        return "secret service absent: secrets.keyring_read"
    raise AssertionError(f"unexpected default keyring error id: {error_id}")


def keyring_error_id(outcome: Any) -> str | None:
    """Extract only the typed error id from the live client's result."""
    error = getattr(outcome, "error", None)
    if error is None:
        return None
    return (error.data or {}).get("id") or "unknown"


def keyring_guidance_present(outcome: Any) -> bool:
    """Whether the error tells callers about keyring unavailability and fallback."""
    error = getattr(outcome, "error", None)
    if error is None:
        return True
    text = " ".join((getattr(error, "message", "") or "",
                     getattr(error, "suggested_action", "") or "")).lower()
    return "keyring" in text and "unavailable" in text and "env" in text
