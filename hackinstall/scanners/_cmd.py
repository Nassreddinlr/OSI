"""Tiny subprocess helper used by both scanners.

Wraps ``subprocess.run`` with a consistent timeout, utf-8 decoding, and
non-zero tolerance. Returns ``(stdout, returncode)`` — the caller decides
what counts as failure. Centralized so error handling is identical across
Linux/Windows scanners and we never hang on a missing tool.
"""
from __future__ import annotations

import os
import shutil
import subprocess


def have(tool: str) -> bool:
    """True if ``tool`` is on PATH."""
    return shutil.which(tool) is not None


def can_sudo() -> bool:
    """True if the current user can run sudo without a password.

    Uses ``sudo -n true`` (non-interactive). If that returns 0, passwordless
    sudo is available. Otherwise, the caller should request password from
    the user or skip the root-backed upgrade.
    """
    if os.geteuid() == 0:
        return True
    try:
        proc = subprocess.run(
            ["sudo", "-n", "true"],
            capture_output=True,
            timeout=5.0,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def is_root() -> bool:
    """True if the current process is running as root."""
    return os.geteuid() == 0


def run(
    cmd: list[str],
    *,
    timeout: float = 15.0,
    check: bool = False,
    as_root: bool = False,
) -> tuple[str, int]:
    """Run ``cmd``, return ``(stdout, returncode)``.

    ``as_root=True`` prepends sudo. Strategy:
    1. If already root — run directly.
    2. Try ``sudo -n`` (non-interactive / passwordless) first.
    3. If that fails with auth error, fall back to ``sudo`` (interactive)
       which will prompt the user's terminal for a password.

    The caller treats a nonzero return as 'failed' and falls back gracefully.
    """
    if as_root and cmd[0] != "sudo":
        if is_root():
            pass  # Already root, run as-is.
        else:
            # Try non-interactive first; if passwordless sudo is available
            # this is faster and silent.
            cmd = ["sudo", "-n", "--"] + cmd

    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
        # If sudo -n failed with auth error (rc=1, "password is required"),
        # retry interactively. This will prompt on the terminal.
        if (
            as_root
            and proc.returncode != 0
            and not is_root()
            and "sudo" in cmd
            and "-n" in cmd
        ):
            # Strip -n flag and retry interactively.
            interactive_cmd = [c for c in cmd if c != "-n"]
            try:
                proc = subprocess.run(  # noqa: S603
                    interactive_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=check,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass  # Fall through with original failure.
        return proc.stdout, proc.returncode
    except FileNotFoundError:
        return "", 127
    except subprocess.TimeoutExpired:
        return "", 124
    except subprocess.CalledProcessError as exc:
        return exc.stdout or "", exc.returncode
