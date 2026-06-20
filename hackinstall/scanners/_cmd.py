"""Tiny subprocess helper used by both scanners.

Wraps ``subprocess.run`` with a consistent timeout, utf-8 decoding, and
non-zero tolerance. Returns ``(stdout, returncode)`` — the caller decides
what counts as failure. Centralized so error handling is identical across
Linux/Windows scanners and we never hang on a missing tool.
"""
from __future__ import annotations

import shutil
import subprocess


def have(tool: str) -> bool:
    """True if ``tool`` is on PATH."""
    return shutil.which(tool) is not None


def run(
    cmd: list[str],
    *,
    timeout: float = 8.0,
    check: bool = False,
    as_root: bool = False,
) -> tuple[str, int]:
    """Run ``cmd``, return ``(stdout, returncode)``.

    ``as_root=True`` prepends sudo non-interactively (``-n``). If passwordless
    sudo isn't available the command fails fast with a nonzero return — callers
    treat that as 'needs root' and fall back to /sys.
    """
    if as_root and cmd[0] != "sudo":
        cmd = ["sudo", "-n", "--"] + cmd

    try:
        proc = subprocess.run(  # noqa: S603 — cmd is built internally, not from user input here
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
        return proc.stdout, proc.returncode
    except FileNotFoundError:
        return "", 127
    except subprocess.TimeoutExpired:
        return "", 124
    except subprocess.CalledProcessError as exc:
        return exc.stdout or "", exc.returncode
