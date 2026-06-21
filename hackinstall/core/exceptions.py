"""Exception hierarchy for Phase 2.

Two kinds of failure:
  - Blocker       : hard stop. EFI generation must not complete. Surfaced to
                    the user with the offending field and a clear reason.
  - BuildWarning  : soft. Generation proceeds; the issue is recorded in the
                    BuildPlan's ``warnings[]`` and shown to the user.
"""
from __future__ import annotations


class HackInstallError(Exception):
    """Base class for all Phase 2 errors."""


class Blocker(HackInstallError):
    """Hard stop — a hardware combination that cannot produce a bootable EFI.

    Carries ``field`` (the profile path that triggered it) and ``reason``
    (human-readable). Phase 3 must refuse to proceed when any blocker exists.
    """

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"[{field}] {reason}")


class BuildWarning(HackInstallError):
    """Soft warning — generation proceeds, but the user should know."""

    def __init__(self, field: str, reason: str, *, needs_root: bool = False) -> None:
        self.field = field
        self.reason = reason
        self.needs_root = needs_root
        super().__init__(f"[{field}] {reason}")


__all__ = ["HackInstallError", "Blocker", "BuildWarning"]
