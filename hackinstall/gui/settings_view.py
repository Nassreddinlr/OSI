"""Settings view — user preferences and about page.

Persists settings to ``~/.hackinstall/settings.json``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import flet as ft

from . import theme

if TYPE_CHECKING:
    from .app import HackInstallApp

_SETTINGS_DIR = Path.home() / ".hackinstall"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"

_DEFAULTS = {
    "macos_target": "auto",
    "output_dir": "efi_output",
    "theme": "dark",
}


class SettingsView(ft.Column):
    """Page for viewing and editing HackInstall preferences."""

    def __init__(self, app: HackInstallApp) -> None:
        super().__init__(spacing=0, expand=True)
        self.app = app
        self._settings = self._load_settings()

        self._macos_dropdown = ft.Dropdown(
            label="Default macOS Target",
            options=[
                ft.dropdown.Option("auto",    text="Auto (detect from CPU)"),
                ft.dropdown.Option("ventura", text="Ventura (13)"),
                ft.dropdown.Option("sonoma",  text="Sonoma (14)"),
                ft.dropdown.Option("sequoia", text="Sequoia (15)"),
            ],
            value=self._settings.get("macos_target", "auto"),
            width=300,
            bgcolor=theme.CARD_BG,
            color=theme.TEXT_PRIMARY,
        )
        self._output_field = ft.TextField(
            label="Default Output Directory",
            value=self._settings.get("output_dir", "efi_output"),
            width=350,
            bgcolor=theme.CARD_BG,
            color=theme.TEXT_PRIMARY,
        )
        self._theme_dropdown = ft.Dropdown(
            label="Theme",
            options=[
                ft.dropdown.Option("dark",  text="Dark"),
                ft.dropdown.Option("light", text="Light"),
            ],
            value=self._settings.get("theme", "dark"),
            width=300,
            bgcolor=theme.CARD_BG,
            color=theme.TEXT_PRIMARY,
            on_select=self._on_theme_change,
        )

        self._save_btn = ft.ElevatedButton(
            "Save Settings",
            icon=ft.Icons.SAVE,
            on_click=self._on_save,
            style=ft.ButtonStyle(bgcolor=theme.ACCENT, color="#FFFFFF"),
        )
        self._status = ft.Text("", size=12, color=theme.TEXT_SECONDARY)

        self.controls = [
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.SETTINGS, size=28, color=theme.ACCENT),
                    ft.Text("Settings", size=20, weight=ft.FontWeight.BOLD,
                            color=theme.TEXT_PRIMARY),
                ], spacing=10),
                margin=ft.Margin.only(bottom=16),
            ),
            # Generation defaults.
            theme.section_card("Generation Defaults", ft.Column([
                self._macos_dropdown,
                self._output_field,
            ], spacing=12), icon=ft.Icons.BUILD),
            # Appearance.
            theme.section_card("Appearance", ft.Column([
                self._theme_dropdown,
            ], spacing=12), icon=ft.Icons.PALETTE),
            # Save button.
            ft.Container(
                content=ft.Row([
                    self._save_btn,
                    self._status,
                ], spacing=12),
                margin=ft.Margin.only(top=8),
            ),
            # About section.
            _about_card(),
        ]

    # ─── Actions ────────────────────────────────────────────────────────────

    def _on_save(self, _: ft.ControlEvent) -> None:
        self._settings = {
            "macos_target": self._macos_dropdown.value,
            "output_dir": self._output_field.value,
            "theme": self._theme_dropdown.value,
        }
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(
            json.dumps(self._settings, indent=2), encoding="utf-8",
        )
        self._status.value = f"Saved to {_SETTINGS_FILE}"
        self._status.color = "#4CAF50"
        self.update()

    def _on_theme_change(self, _: ft.ControlEvent) -> None:
        val = self._theme_dropdown.value
        if val == "light":
            self.app.page.theme_mode = ft.ThemeMode.LIGHT
        else:
            self.app.page.theme_mode = ft.ThemeMode.DARK
        self.app.page.update()

    # ─── Persistence ────────────────────────────────────────────────────────

    @staticmethod
    def _load_settings() -> dict:
        if _SETTINGS_FILE.exists():
            try:
                data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
                return {**_DEFAULTS, **data}
            except (json.JSONDecodeError, OSError):
                pass
        return dict(_DEFAULTS)


# ─── About card ───────────────────────────────────────────────────────────────

def _about_card() -> ft.Container:
    from .. import __version__
    return ft.Container(
        content=ft.Column([
            ft.Text("About HackInstall", size=16, weight=ft.FontWeight.BOLD,
                    color=theme.TEXT_PRIMARY),
            ft.Divider(color=theme.DIVIDER),
            theme.info_row("Version", __version__),
            theme.info_row("License", "MIT"),
            theme.info_row("Author", "HackInstall"),
            ft.Text(
                "HackInstall is a one-click macOS-on-PC EFI generator. "
                "It scans your hardware, selects the right kexts, quirks, "
                "and SSDTs, and produces a complete OpenCore EFI folder.",
                size=12, color=theme.TEXT_SECONDARY, italic=True,
            ),
        ], spacing=6),
        bgcolor=theme.CARD_BG,
        padding=14,
        border_radius=10,
        margin=ft.Margin.only(top=16),
    )
