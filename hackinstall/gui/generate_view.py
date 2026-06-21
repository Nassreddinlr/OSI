"""Generate view — EFI generation wizard.

A 4-step manual wizard (ft.Stepper was removed in Flet 0.85) that walks the
user through:
  Step 1: Review detected hardware (summary).
  Step 2: Configure — macOS target, output directory.
  Step 3: Build Plan preview — kexts, SSDTs, SMBIOS, quirks, boot-args.
  Step 4: Generate — run ``efi_builder.build_efi()`` and show results.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import flet as ft

from . import theme

if TYPE_CHECKING:
    from .app import HackInstallApp

_STEP_TITLES = ["1. Review Hardware", "2. Configure", "3. Build Plan", "4. Generate"]


class GenerateView(ft.Column):
    """Wizard-style page for generating an OpenCore EFI."""

    def __init__(self, app: HackInstallApp) -> None:
        super().__init__(spacing=0, expand=True)
        self.app = app
        self._plan: dict[str, Any] | None = None
        self._generating = False
        self._current_step = 0

        # ── Step content containers ────────────────────────────────────
        self._step1_content = ft.Column(spacing=8)
        self._step2_content = ft.Column(spacing=12, controls=self._build_step2())
        self._step3_content = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)
        self._step4_content = ft.Column(spacing=8)

        # References to step-2 controls (built once in _build_step2).
        self._macos_dropdown: ft.Dropdown
        self._output_field: ft.TextField

        # ── Wizard chrome ───────────────────────────────────────────────
        self._step_indicator = ft.Container(margin=ft.Margin.only(bottom=8))
        self._step_body = ft.Container(expand=True)
        self._back_btn = ft.ElevatedButton(
            "Back", icon=ft.Icons.ARROW_BACK, on_click=self._on_back,
        )
        self._continue_btn = ft.ElevatedButton(
            "Continue", icon=ft.Icons.ARROW_FORWARD,
            on_click=self._on_continue,
            style=ft.ButtonStyle(bgcolor=theme.ACCENT, color="#FFFFFF"),
        )

        self.controls = [
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.BUILD, size=28, color=theme.ACCENT),
                    ft.Text("EFI Generator", size=20, weight=ft.FontWeight.BOLD,
                            color=theme.TEXT_PRIMARY),
                ], spacing=10),
                margin=ft.Margin.only(bottom=12),
            ),
            self._step_indicator,
            ft.Container(
                content=self._step_body,
                expand=True,
                bgcolor=theme.CARD_BG,
                padding=16,
                border_radius=10,
            ),
            ft.Container(
                content=ft.Row([self._back_btn, self._continue_btn], spacing=10),
                margin=ft.Margin.only(top=8),
            ),
        ]
        self._render_step()

    # ─── Step 2 control factory ─────────────────────────────────────────────

    def _build_step2(self) -> list[ft.Control]:
        self._macos_dropdown = ft.Dropdown(
            label="macOS Target",
            options=[
                ft.dropdown.Option("auto",    text="Auto (detect from CPU)"),
                ft.dropdown.Option("ventura", text="Ventura (13)"),
                ft.dropdown.Option("sonoma",  text="Sonoma (14)"),
                ft.dropdown.Option("sequoia", text="Sequoia (15)"),
            ],
            value="auto",
            width=300,
            bgcolor=theme.CARD_BG,
            color=theme.TEXT_PRIMARY,
        )
        self._output_field = ft.TextField(
            label="Output Directory",
            value="efi_output",
            width=350,
            bgcolor=theme.CARD_BG,
            color=theme.TEXT_PRIMARY,
        )
        browse_btn = ft.ElevatedButton(
            "Browse…", on_click=self._on_browse,
        )
        return [
            ft.Text("macOS target version", size=13, color=theme.TEXT_SECONDARY),
            self._macos_dropdown,
            ft.Text("Output directory", size=13, color=theme.TEXT_SECONDARY),
            ft.Row([self._output_field, browse_btn], spacing=8),
        ]

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        """Refresh Step 1 when this view becomes visible."""
        if self._current_step == 0:
            self._populate_step1()
            self._render_step()

    # ─── Wizard navigation ──────────────────────────────────────────────────

    def _render_step(self) -> None:
        """Re-render the step indicator + body for the current step."""
        chips = []
        for i, title in enumerate(_STEP_TITLES):
            is_current = i == self._current_step
            is_done = i < self._current_step
            color = theme.ACCENT if is_current else (
                "#4CAF50" if is_done else theme.TEXT_SECONDARY)
            icon = (ft.Icons.CHECK_CIRCLE if is_done else
                    ft.Icons.RADIO_BUTTON_CHECKED if is_current else
                    ft.Icons.RADIO_BUTTON_UNCHECKED)
            chips.append(ft.Container(
                content=ft.Row([
                    ft.Icon(icon, size=14, color=color),
                    ft.Text(title, size=12, color=color,
                            weight=ft.FontWeight.BOLD if is_current else ft.FontWeight.NORMAL),
                ], spacing=4),
                padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            ))
            if i < len(_STEP_TITLES) - 1:
                chips.append(ft.Text("›", color=theme.TEXT_SECONDARY, size=14))
        self._step_indicator.content = ft.Row(chips, spacing=4)

        bodies = [self._step1_content, self._step2_content,
                  self._step3_content, self._step4_content]
        self._step_body.content = ft.Column(
            controls=[bodies[self._current_step]],
            spacing=8,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

        self._back_btn.disabled = self._current_step == 0
        self._continue_btn.text = (
            "Finish" if self._current_step == 3 else
            "Generate EFI" if self._current_step == 2 else "Continue")
        self._continue_btn.icon = (
            ft.Icons.CHECK_CIRCLE if self._current_step == 3 else
            ft.Icons.BOLT if self._current_step == 2 else ft.Icons.ARROW_FORWARD)

    def _on_back(self, _: ft.ControlEvent) -> None:
        if self._current_step > 0:
            self._current_step -= 1
            self._render_step()
            self.update()

    def _on_continue(self, _: ft.ControlEvent) -> None:
        idx = self._current_step
        if idx == 0:
            self._populate_step1()
            if not self.app.profile:
                self._step1_content.controls = [
                    theme.alert_banner("No hardware profile — go to Scan tab first.", severity="error"),
                ]
                self._render_step()
                self.update()
                return
            self._current_step = 1
            self._render_step()
            self.update()
        elif idx == 1:
            self._build_plan()
        elif idx == 2:
            self._generate_efi()
        # idx == 3: nothing further (Finish); generation already ran.

    # ─── Step 1: Review hardware ───────────────────────────────────────────

    def _populate_step1(self) -> None:
        """Show a compact hardware summary in Step 1."""
        p = self.app.profile
        if not p:
            self._step1_content.controls = [
                theme.alert_banner(
                    "No hardware profile loaded. Go to the Scan tab to detect your hardware, "
                    "or load a profile file.",
                    severity="warning",
                ),
            ]
            return

        cpu = p.get("cpu", {}) or {}
        gpus = p.get("gpu", []) or []
        mobo = p.get("motherboard", {}) or {}

        controls: list[ft.Control] = [
            ft.Text("Detected hardware summary:", size=14, weight=ft.FontWeight.BOLD,
                    color=theme.TEXT_PRIMARY),
            ft.Divider(color=theme.DIVIDER),
        ]

        controls.append(theme.section_card("CPU", ft.Column([
            theme.info_row("Name", cpu.get("name")),
            ft.Row([
                ft.Text("macOS support:", size=12, color=theme.TEXT_SECONDARY, width=130),
                theme.status_badge(cpu.get("macos_support")),
            ], spacing=8),
        ], spacing=4), icon=ft.Icons.MEMORY))

        for g in gpus:
            controls.append(theme.section_card("GPU", ft.Column([
                theme.info_row("Name", g.get("name")),
                theme.info_row("Vendor", g.get("vendor")),
                ft.Row([
                    ft.Text("macOS support:", size=12, color=theme.TEXT_SECONDARY, width=130),
                    theme.status_badge(g.get("macos_support")),
                ], spacing=8),
            ], spacing=4), icon=ft.Icons.MONITOR))

        controls.append(theme.section_card("Board", ft.Column([
            theme.info_row("Board", f"{mobo.get('vendor','?')} {mobo.get('model','?')}"),
            theme.info_row("Chassis", mobo.get("chassis_type")),
        ], spacing=4), icon=ft.Icons.DEVELOPER_BOARD))

        controls.append(ft.Text("Press Continue to configure generation options.",
                                size=12, color=theme.TEXT_SECONDARY, italic=True))
        self._step1_content.controls = controls

    # ─── Step 2 → 3: Build plan ─────────────────────────────────────────────

    def _build_plan(self) -> None:
        """Run the decision engine to produce a BuildPlan, then move to Step 3."""
        if not self.app.profile:
            return
        self._step3_content.controls = [
            ft.Row([ft.ProgressRing(width=20, height=20, stroke_width=2),
                    ft.Text("Running decision engine…")], spacing=10),
        ]
        self._current_step = 2
        self._render_step()
        self.update()

        thread = threading.Thread(target=self._run_build_plan, daemon=True)
        thread.start()

    def _run_build_plan(self) -> None:
        try:
            from ..core import decisions
            plan = decisions.build_plan(
                self.app.profile,
                macos_target=self._macos_dropdown.value,
            )
            self.app.page.run_thread(self._plan_complete, plan, None)
        except Exception as exc:
            self.app.page.run_thread(self._plan_complete, None, str(exc))

    def _plan_complete(self, plan: dict | None, error: str | None) -> None:
        if error or not plan:
            self._step3_content.controls = [
                theme.alert_banner(f"Build plan failed: {error}", severity="error"),
            ]
            self._current_step = 1
            self._render_step()
            self.update()
            return

        self._plan = plan
        self._populate_step3(plan)
        self.update()

    def _populate_step3(self, plan: dict) -> None:
        """Render the BuildPlan preview in Step 3."""
        meta = plan.get("plan_metadata", {})
        smbios = plan.get("smbios", {})
        kexts = plan.get("kexts", [])
        ssdts = plan.get("ssdts", [])
        boot_args = plan.get("boot_args", {})
        quirks = plan.get("quirks", {})
        blockers = plan.get("blockers", [])
        warnings = plan.get("warnings", [])
        notes = plan.get("config_notes", [])

        controls: list[ft.Control] = []

        if blockers:
            controls.append(ft.Text("BLOCKERS", size=14, weight=ft.FontWeight.BOLD,
                                     color="#F44336"))
            for b in blockers:
                controls.append(theme.alert_banner(
                    f"[{b.get('field','?')}] {b.get('reason','?')}", severity="error"))
            controls.append(ft.Text(
                "Cannot proceed — fix the blocker(s) or choose a different macOS target.",
                size=13, color="#F44336"))
            self._step3_content.controls = controls
            return

        if warnings:
            for w in warnings:
                controls.append(theme.alert_banner(
                    f"{w.get('field','?')}: {w.get('reason','?')}",
                    severity="warning",
                ))

        controls.append(theme.section_card("Target", ft.Column([
            theme.info_row("macOS", meta.get("macos_target", "?")),
            theme.info_row("OpenCore", meta.get("opencore_version", "?")),
            theme.info_row("Timestamp", meta.get("timestamp", "?")),
        ], spacing=4), icon=ft.Icons.CENTER_FOCUS_STRONG))

        controls.append(theme.section_card("SMBIOS", ft.Column([
            theme.info_row("Model", smbios.get("system_product_name")),
            theme.info_row("Serial", smbios.get("system_serial")),
            theme.info_row("MLB", smbios.get("mlb")),
            theme.info_row("UUID", smbios.get("system_uuid")),
            theme.info_row("ROM", smbios.get("rom")),
        ], spacing=4), icon=ft.Icons.COMPUTER))

        active = boot_args.get("active", "debug")
        controls.append(theme.section_card("Boot Args", ft.Column([
            theme.info_row("Mode", active),
            theme.info_row("Debug", boot_args.get("debug")),
            theme.info_row("Release", boot_args.get("release")),
        ], spacing=4), icon=ft.Icons.TERMINAL))

        kext_rows = [[k.get("id", "?"), k.get("version", "?"), k.get("reason", "")]
                      for k in kexts]
        controls.append(theme.section_card(
            f"Kexts ({len(kexts)})",
            theme.data_table(["Kext", "Version", "Reason"], kext_rows),
            icon=ft.Icons.EXTENSION,
        ))

        ssdt_rows = [[s.get("name", "?"), s.get("reason", ""), s.get("when", "")]
                       for s in ssdts]
        if ssdt_rows:
            controls.append(theme.section_card(
                f"SSDTs ({len(ssdts)})",
                theme.data_table(["Name", "Reason", "When"], ssdt_rows),
                icon=ft.Icons.CODE,
            ))

        quirks_controls: list[ft.Control] = []
        for section, values in quirks.items():
            rows = [[str(k), str(v)] for k, v in values.items()]
            quirks_controls.append(
                ft.Text(section, size=13, weight=ft.FontWeight.BOLD, color=theme.ACCENT_LIGHT))
            quirks_controls.append(theme.data_table(["Quirk", "Value"], rows))
        if quirks_controls:
            controls.append(theme.section_card(
                "Quirks", ft.Column(quirks_controls, spacing=6),
                icon=ft.Icons.TUNE,
            ))

        if notes:
            controls.append(theme.section_card(
                f"Decision Log ({len(notes)})",
                ft.Column([ft.Text(f"• {n}", size=11, color=theme.TEXT_SECONDARY)
                           for n in notes], spacing=2),
                icon=ft.Icons.LIST_ALT,
            ))

        controls.append(ft.Text("Press Generate EFI to build the EFI folder.",
                                 size=12, color=theme.TEXT_SECONDARY, italic=True))
        self._step3_content.controls = controls

    # ─── Step 3 → 4: Generate EFI ───────────────────────────────────────────

    def _generate_efi(self) -> None:
        if not self.app.profile or not self._plan:
            return
        if self._plan.get("blockers"):
            self._step4_content.controls = [
                theme.alert_banner("Blockers detected — cannot generate.", severity="error"),
            ]
            self.update()
            return

        self._generating = True
        self._step4_content.controls = [
            ft.Row([ft.ProgressRing(width=20, height=20, stroke_width=2),
                    ft.Text("Generating EFI…")], spacing=10),
        ]
        self._current_step = 3
        self._render_step()
        self.update()

        thread = threading.Thread(target=self._run_generate, daemon=True)
        thread.start()

    def _run_generate(self) -> None:
        try:
            from ..core import efi_builder
            result = efi_builder.build_efi(
                self.app.profile,
                self._output_field.value,
                macos_target=self._macos_dropdown.value,
            )
            self.app.page.run_thread(self._generate_complete, result, None)
        except Exception as exc:
            self.app.page.run_thread(self._generate_complete, None, str(exc))

    def _generate_complete(self, result: Any, error: str | None) -> None:
        self._generating = False
        if error:
            self._step4_content.controls = [
                theme.alert_banner(f"Generation failed: {error}", severity="error"),
            ]
            self._current_step = 2
            self._render_step()
            self.update()
            return

        controls: list[ft.Control] = [
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE, size=24, color="#4CAF50"),
                    ft.Text("EFI generated successfully!", size=16,
                            weight=ft.FontWeight.BOLD, color="#4CAF50"),
                ], spacing=8),
                margin=ft.Margin.only(bottom=12),
            ),
        ]

        meta = self._plan.get("plan_metadata", {}) if self._plan else {}
        smbios = self._plan.get("smbios", {}) if self._plan else {}

        controls.append(theme.section_card("Summary", ft.Column([
            theme.info_row("macOS target", meta.get("macos_target")),
            theme.info_row("OpenCore", meta.get("opencore_version")),
            theme.info_row("SMBIOS", smbios.get("system_product_name")),
            theme.info_row("Kexts", str(result.kext_count)),
            theme.info_row("SSDTs", str(result.ssdt_count)),
        ], spacing=4), icon=ft.Icons.SUMMARIZE))

        controls.append(theme.section_card("Output Files", ft.Column([
            theme.info_row("config.plist", str(result.config_path)),
            theme.info_row("build_plan.json", str(result.plan_path)),
            theme.info_row("EFI folder", str(result.efi_dir)),
        ], spacing=4), icon=ft.Icons.FOLDER))

        if result.warnings:
            for w in result.warnings:
                controls.append(theme.alert_banner(
                    f"{w.get('field','?')}: {w.get('reason','?')}",
                    severity="warning",
                ))

        controls.append(ft.ElevatedButton(
            "Open Output Folder",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=lambda _: self._open_folder(str(result.output_dir)),
            style=ft.ButtonStyle(bgcolor=theme.ACCENT, color="#FFFFFF"),
        ))

        self._step4_content.controls = controls
        self.app.set_build_result({
            "output_dir": str(result.output_dir),
            "config_path": str(result.config_path),
            "plan_path": str(result.plan_path),
            "efi_dir": str(result.efi_dir),
            "kext_count": result.kext_count,
            "ssdt_count": result.ssdt_count,
            "warnings": result.warnings,
        })
        self.update()

    # ─── Helpers ────────────────────────────────────────────────────────────

    async def _on_browse(self, _: ft.ControlEvent) -> None:
        fp = ft.FilePicker()
        self.app.page.overlay.append(fp)
        self.app.page.update()
        try:
            path = await fp.get_directory_path(
                dialog_title="Select output directory",
            )
        finally:
            self.app.page.overlay.remove(fp)
            self.app.page.update()
        if path:
            self._output_field.value = path
            self.update()

    @staticmethod
    def _open_folder(path: str) -> None:
        """Open a folder in the system file manager."""
        import subprocess
        import os
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif os.name == "posix":
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass
