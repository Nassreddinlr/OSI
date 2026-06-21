"""HackInstall GUI — Flet desktop application.

Launch via::

    python -m hackinstall gui

Or programmatically::

    from hackinstall.gui import run
    run()
"""
from __future__ import annotations

import flet as ft

from .app import HackInstallApp


def run() -> None:
    """Launch the HackInstall GUI window (native desktop app)."""
    ft.app(target=HackInstallApp().build)


__all__ = ["run"]
