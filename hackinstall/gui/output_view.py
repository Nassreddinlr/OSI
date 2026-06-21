"""Output view — browses the generated EFI folder.

Shows the EFI/OC directory tree, build plan summary, and the README
that ``efi_builder`` wrote. If no EFI has been generated yet, shows a
placeholder prompting the user to go to the Generate tab.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import flet as ft

from . import theme

if TYPE_CHECKING:
    from .app import HackInstallApp


class OutputView(ft.Column):
    """Page for browsing the generated EFI output."""

    def __init__(self, app: HackInstallApp) -> None:
        super().__init__(spacing=0, expand=True)
        self.app = app
        self._content = ft.Column(spacing=8, expand=True, scroll=ft.ScrollMode.AUTO)
        self.controls = [
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.FOLDER, size=28, color=theme.ACCENT),
                    ft.Text("EFI Output", size=20, weight=ft.FontWeight.BOLD,
                            color=theme.TEXT_PRIMARY),
                ], spacing=10),
                margin=ft.Margin.only(bottom=12),
            ),
            self._content,
        ]

    def on_enter(self) -> None:
        """Refresh when the user switches to this tab."""
        self._refresh()

    def _refresh(self) -> None:
        """Re-scan the output directory and rebuild the view."""
        result = self.app.build_result
        if not result:
            self._content.controls = [
                _empty_state(),
            ]
            self.update()
            return

        out_dir = Path(result.get("output_dir", "efi_output"))
        controls: list[ft.Control] = []

        # Quick summary bar.
        controls.append(ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.CHECK_CIRCLE, size=18, color="#4CAF50"),
                ft.Text(
                    f"Generated {result.get('kext_count', 0)} kexts, "
                    f"{result.get('ssdt_count', 0)} SSDTs  —  "
                    f"{out_dir}",
                    size=13, color=theme.TEXT_PRIMARY,
                ),
                ft.Container(expand=True),
                ft.ElevatedButton(
                    "Open Folder", icon=ft.Icons.FOLDER_OPEN,
                    on_click=lambda _: _open_folder(str(out_dir)),
                    style=ft.ButtonStyle(bgcolor=theme.ACCENT, color="#FFFFFF"),
                ),
            ], spacing=10),
            bgcolor=theme.CARD_BG,
            padding=12,
            border_radius=8,
            margin=ft.Margin.only(bottom=8),
        ))

        # File tree.
        efi_dir = out_dir / "EFI"
        if efi_dir.exists():
            tree_text = _directory_tree(efi_dir, prefix="EFI/")
            controls.append(theme.section_card(
                "Directory Structure",
                ft.Text(tree_text, font_family="monospace", size=12,
                        color=theme.TEXT_PRIMARY, selectable=True),
                icon=ft.Icons.ACCOUNT_TREE,
            ))
        else:
            controls.append(theme.alert_banner(
                f"EFI folder not found at {efi_dir}", severity="warning"))

        # Build plan summary.
        plan_path = out_dir / "build_plan.json"
        if plan_path.exists():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                meta = plan.get("plan_metadata", {})
                smbios = plan.get("smbios", {})
                boot_args = plan.get("boot_args", {})
                controls.append(theme.section_card("Build Plan Summary", ft.Column([
                    theme.info_row("macOS target", meta.get("macos_target")),
                    theme.info_row("OpenCore", meta.get("opencore_version")),
                    theme.info_row("SMBIOS model", smbios.get("system_product_name")),
                    theme.info_row("Serial", smbios.get("system_serial")),
                    theme.info_row("Boot args", boot_args.get(
                        boot_args.get("active", "debug"), "")),
                ], spacing=4), icon=ft.Icons.SUMMARIZE))
            except (json.JSONDecodeError, OSError):
                pass

        # Manifest files.
        for subdir_name, icon in [("ACPI", ft.Icons.CODE), ("Kexts", ft.Icons.EXTENSION),
                                   ("Drivers", ft.Icons.SETTINGS_ETHERNET)]:
            manifest = efi_dir / "OC" / subdir_name / "MANIFEST.txt"
            if manifest.exists():
                try:
                    text = manifest.read_text(encoding="utf-8").strip()
                    # Strip comment lines that start with #, show them as-is.
                    lines = [l for l in text.splitlines() if l.strip()]
                    if lines:
                        controls.append(theme.section_card(
                            f"EFI/OC/{subdir_name}/ expected files",
                            ft.Text("\n".join(lines), font_family="monospace",
                                    size=11, color=theme.TEXT_SECONDARY),
                            icon=icon,
                        ))
                except OSError:
                    pass

        # README.
        readme_path = out_dir / "README.md"
        if readme_path.exists():
            try:
                readme = readme_path.read_text(encoding="utf-8")
                controls.append(theme.section_card(
                    "README",
                    ft.Markdown(readme, selectable=True),
                    icon=ft.Icons.DESCRIPTION,
                ))
            except OSError:
                pass

        # Warnings from generation.
        gen_warnings = result.get("warnings") or []
        if gen_warnings:
            for w in gen_warnings:
                controls.append(theme.alert_banner(
                    f"{w.get('field','?')}: {w.get('reason','?')}",
                    severity="warning",
                ))

        self._content.controls = controls
        self.update()


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _empty_state() -> ft.Container:
    """Placeholder when no EFI has been generated yet."""
    return ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.FOLDER_OFF, size=64, color=theme.TEXT_SECONDARY),
            ft.Text("No EFI output yet.", size=16, color=theme.TEXT_PRIMARY,
                    weight=ft.FontWeight.BOLD),
            ft.Text("Go to the Generate tab, configure your options, "
                    "and generate an EFI to see the results here.",
                    size=13, color=theme.TEXT_SECONDARY),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
        alignment=ft.Alignment.CENTER,
        expand=True,
    )


def _directory_tree(root: Path, prefix: str = "", depth: int = 0, max_depth: int = 4) -> str:
    """Build an ASCII tree string for a directory."""
    if depth > max_depth or not root.exists():
        return prefix if depth == 0 else ""
    lines = [prefix] if depth == 0 else []
    entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    # Skip hidden files and __pycache__.
    entries = [e for e in entries if not e.name.startswith(".") and e.name != "__pycache__"]
    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        indent = "│   " * depth
        if depth > 0:
            line = f"{indent}{connector}{entry.name}"
        else:
            line = f"{'├── ' if i < len(entries) - 1 else '└── '}{entry.name}"
        lines.append(line)
        if entry.is_dir():
            child_prefix = entry.name + "/"
            child_lines = _directory_tree(entry, child_prefix, depth + 1, max_depth)
            lines.append(child_lines)
    return "\n".join(lines)


def _open_folder(path: str) -> None:
    import subprocess
    import os
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif os.name == "posix":
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass
