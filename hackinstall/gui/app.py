"""Main application shell — NavigationRail + view routing + shared state.

This is the top-level controller. It owns the Flet ``Page``, creates the
sidebar, and swaps the main content area between views.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import flet as ft

from . import theme
from .output_view import OutputView
from .scan_view import ScanView
from .settings_view import SettingsView
from .generate_view import GenerateView


class HackInstallApp:
    """Flet application controller — builds the page and routes navigation."""

    def __init__(self) -> None:
        # Shared state — populated by views, read by other views.
        self.profile: dict[str, Any] | None = None
        self.build_result: dict[str, Any] | None = None
        self.output_dir: str = "efi_output"

        # Views (created once, updated when switched to).
        self._views: dict[int, ft.Control] = {}
        # One persistent slot per nav destination. Each view lives in its slot
        # for the whole session and is shown/hidden with `visible` instead of
        # being moved in the tree. Moving a cached control leaves its `_parent`
        # weakref pointing at a discarded wrapper, which later makes .update()
        # crash with "Control must be added to the page first".
        self._slots: list[ft.Column | None] = [None, None, None, None]
        self._view_holder = ft.Column(expand=True, spacing=0)
        self._nav_index = 0
        self._page: ft.Page | None = None

    # ─── Public entry point called by ft.app() ──────────────────────────────

    def build(self, page: ft.Page) -> None:
        """Set up the page, build the shell, do initial render."""
        self._page = page
        page.title = "HackInstall"
        page.theme_mode = ft.ThemeMode.DARK
        page.window.width = 1200
        page.window.height = 800
        page.window.min_width = 900
        page.window.min_height = 600
        page.padding = 0
        page.bgcolor = theme.BG

        # Navigation rail (left sidebar).
        rail = ft.NavigationRail(
            selected_index=self._nav_index,
            label_type=ft.NavigationRailLabelType.SELECTED,
            min_width=80,
            min_extended_width=180,
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.Icons.SEARCH, selected_icon=ft.Icons.SEARCH,
                    label="Scan",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.BUILD, selected_icon=ft.Icons.BUILD,
                    label="Generate",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.FOLDER_OUTLINED, selected_icon=ft.Icons.FOLDER,
                    label="Output",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SETTINGS, selected_icon=ft.Icons.SETTINGS,
                    label="Settings",
                ),
            ],
            on_change=self._on_nav_change,
            bgcolor=theme.SIDEBAR_BG,
        )

        # Page layout: rail on left, scrollable content on right.
        page.add(
            ft.Row(
                controls=[rail, self._view_holder],
                expand=True,
                spacing=0,
            ),
        )

        # Build one persistent slot per nav destination. Views are never
        # moved after this — only toggled visible — so their `_parent` link
        # stays valid for the lifetime of the app.
        for i in range(len(self._slots)):
            slot = ft.Column(
                controls=[ft.Container(expand=True, margin=16)],
                expand=True,
                spacing=0,
                visible=(i == self._nav_index),
            )
            self._slots[i] = slot
            self._view_holder.controls.append(slot)

        # Flush the new slots to the page so that views mounted inside them
        # have a valid _parent chain and can call .update() / self.page.
        page.update()

        # Show initial view.
        self._show_view(self._nav_index)

    # ─── Navigation routing ───────────────────────────────────────────────

    def _on_nav_change(self, e: ft.ControlEvent) -> None:
        idx = e.control.selected_index
        self._nav_index = idx
        self._show_view(idx)

    def _show_view(self, index: int) -> None:
        """Switch the content area to the view at *index*.

        Each view is mounted into a dedicated slot the first time it's shown,
        then shown/hidden with ``visible``. Views are *never* moved between
        parents, so their Flet ``_parent`` weakref (used by ``.update()`` and
        ``self.page``) stays valid for the whole session.
        """
        # Lazily create + mount the view into its permanent slot.
        if index not in self._views:
            view = self._create_view(index)
            self._views[index] = view
            slot = self._slots[index]
            assert slot is not None
            slot.controls[0].content = view  # type: ignore[index]

        # Toggle visibility: only the active destination is visible.
        for i, slot in enumerate(self._slots):
            if slot is not None:
                slot.visible = (i == index)

        view = self._views[index]
        if self._page:
            self._page.update()
        if hasattr(view, "on_enter"):
            view.on_enter()  # type: ignore[union-attr]

    def _create_view(self, index: int) -> ft.Control:
        if index == 0:
            return ScanView(app=self)
        if index == 1:
            return GenerateView(app=self)
        if index == 2:
            return OutputView(app=self)
        if index == 3:
            return SettingsView(app=self)
        return ft.Text("Unknown view")

    # ─── Shared state helpers ──────────────────────────────────────────────

    def set_profile(self, profile: dict[str, Any]) -> None:
        """Called by ScanView when a scan completes or a profile is loaded."""
        self.profile = profile
        # Invalidate cached generate view so it picks up the new profile.
        self._views.pop(1, None)

    def set_output_dir(self, path: str) -> None:
        self.output_dir = path

    def set_build_result(self, result: dict[str, Any]) -> None:
        """Called by GenerateView when EFI generation completes."""
        self.build_result = result
        # Invalidate cached output view.
        self._views.pop(2, None)

    @property
    def page(self) -> ft.Page:
        if self._page is None:
            raise RuntimeError("Page not initialised — call build() first.")
        return self._page
