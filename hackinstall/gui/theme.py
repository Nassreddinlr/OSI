"""Shared design system — colors, typography, reusable component helpers.

All views import from here so the look-and-feel stays consistent.
"""
from __future__ import annotations

import flet as ft

# ─── Color palette ─────────────────────────────────────────────────────────────
# Dark theme base colors (roughly Material Design Dark).
BG           = "#1C1B1F"          # page background
CARD_BG      = "#2B2B30"          # raised card surface
SIDEBAR_BG   = "#1E1E24"          # navigation rail
TEXT_PRIMARY  = "#E6E1E5"          # primary text
TEXT_SECONDARY = "#9E9EA7"        # muted/secondary text
DIVIDER      = "#3C3C42"          # borders / separators
ACCENT       = "#1976D2"          # interactive accent (blue)
ACCENT_LIGHT = "#64B5F6"          # hovered accent

# Status badge colours.
STATUS_COLORS: dict[str, str] = {
    "full":    "#4CAF50",   # green
    "native":  "#4CAF50",   # green
    "partial": "#FF9800",   # amber
    "dropped": "#F44336",   # red
    "none":    "#F44336",   # red
    "unknown": "#9E9E9E",   # grey
}

# ─── Reusable component builders ─────────────────────────────────────────────


def status_badge(level: str | None) -> ft.Container:
    """Return a small coloured pill showing macOS support *level*."""
    label = (level or "unknown").upper()
    color = STATUS_COLORS.get(level or "unknown", STATUS_COLORS["unknown"])
    return ft.Container(
        content=ft.Text(label, size=11, color="#FFFFFF", weight=ft.FontWeight.BOLD),
        bgcolor=color,
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
        border_radius=10,
    )


def section_card(
    title: str,
    content: ft.Control,
    *,
    icon: str | None = None,
) -> ft.Container:
    """A styled card with a header title and body content."""
    header_parts: list[ft.Control] = [
        ft.Icon(icon or ft.Icons.CHEVRON_RIGHT, size=16, color=ACCENT),
        ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
    ]
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Row(header_parts, spacing=6),
                ft.Container(content=content, padding=ft.Padding.only(left=24, top=4)),
            ],
            spacing=4,
        ),
        bgcolor=CARD_BG,
        padding=14,
        border_radius=10,
        margin=ft.Margin.only(bottom=8),
    )


def info_row(label: str, value: str | None) -> ft.Row:
    """Single key-value row inside a card."""
    return ft.Row(
        controls=[
            ft.Text(label, size=13, color=TEXT_SECONDARY, width=130),
            ft.Text(value or "—", size=13, color=TEXT_PRIMARY, selectable=True),
        ],
        spacing=8,
    )


def info_rows(pairs: dict[str, str | None]) -> ft.Column:
    """Multiple info_rows from a label→value mapping."""
    return ft.Column([info_row(k, v) for k, v in pairs.items()], spacing=4)


def data_table(columns: list[str], rows: list[list[str]]) -> ft.DataTable:
    """Build a compact DataTable from column headers and string rows."""
    col_controls = [
        ft.DataColumn(ft.Text(h, size=12, weight=ft.FontWeight.BOLD, color=TEXT_SECONDARY))
        for h in columns
    ]
    data_rows = [
        ft.DataRow(
            cells=[ft.DataCell(ft.Text(str(c), size=12, color=TEXT_PRIMARY)) for c in row],
        )
        for row in rows
    ]
    return ft.DataTable(
        columns=col_controls,
        rows=data_rows,
        border=ft.Border.only(bottom=ft.BorderSide(1, DIVIDER)),
        column_spacing=16,
        heading_row_height=32,
        data_row_min_height=30,
        horizontal_lines=ft.BorderSide(1, "#2A2A30"),
    )


def heading(text: str, *, level: int = 1) -> ft.Text:
    """Return a styled heading. level 1 = page title, 2 = section, 3 = sub."""
    sizes = {1: 22, 2: 16, 3: 13}
    return ft.Text(text, size=sizes.get(level, 14), weight=ft.FontWeight.BOLD,
                   color=TEXT_PRIMARY if level > 1 else ACCENT_LIGHT)


def alert_banner(message: str, *, severity: str = "error") -> ft.Container:
    """A coloured alert bar — 'error' (red), 'warning' (amber), 'info' (blue)."""
    colors_map = {
        "error":   ("#F44336", ft.Icons.ERROR, "ERROR"),
        "warning": ("#FF9800", ft.Icons.WARNING, "WARNING"),
        "info":    ("#1976D2", ft.Icons.INFO, "INFO"),
    }
    bg, icon, prefix = colors_map.get(severity, colors_map["info"])
    return ft.Container(
        content=ft.Row([
            ft.Icon(icon, size=18, color="#FFFFFF"),
            ft.Text(f"{prefix}: {message}", size=13, color="#FFFFFF"),
        ], spacing=8),
        bgcolor=bg,
        padding=12,
        border_radius=8,
        margin=ft.Margin.only(bottom=8),
    )
