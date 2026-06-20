"""Scanner platform router.

Single entry point: ``get_scanner()`` returns the right concrete scanner for
the host OS. Phase 2's EFI generator calls only this — it never imports a
platform-specific module directly.

Matches the blueprint's::

    scanner = get_scanner()
    profile = scanner.scan()   # → hardware_profile.json
"""
from __future__ import annotations

import platform

from .base_scanner import BaseScanner
from .linux_scanner import LinuxScanner


class UnsupportedPlatformError(RuntimeError):
    """Raised when no scanner exists for the host OS."""


def get_scanner() -> BaseScanner:
    """Return a concrete scanner for the current OS.

    Raises ``UnsupportedPlatformError`` (with available-scanner list) if the
    OS has no implementation yet. On Windows, ``WindowsScanner`` is detected
    but its constructor raises ``NotImplementedError`` until Phase 1 Linux
    work is validated.
    """
    os_name = platform.system()
    if os_name == "Linux":
        return LinuxScanner()
    if os_name == "Windows":
        # Lazy import so Linux users never need the WindowsScanner symbol.
        from .windows_scanner import WindowsScanner
        return WindowsScanner()
    raise UnsupportedPlatformError(
        f"No scanner implemented for OS '{os_name}'. "
        "Supported: Linux (full), Windows (pending Phase 1 validation)."
    )


__all__ = ["BaseScanner", "LinuxScanner", "get_scanner", "UnsupportedPlatformError"]
