"""Scan view — hardware scanner page.

Displays a "Scan Hardware" button, shows progress while scanning, then
renders the full ``hardware_profile.json`` as rich, expandable cards.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from . import theme

if TYPE_CHECKING:
    from .app import HackInstallApp


class ScanView(ft.Column):
    """Page for scanning hardware and viewing the profile."""

    def __init__(self, app: HackInstallApp) -> None:
        super().__init__(spacing=0, expand=True)
        self.app = app
        self._scanning = False
        self._status_text = ft.Text("Ready to scan.", color=theme.TEXT_SECONDARY, size=13)
        self._scan_btn = ft.ElevatedButton(
            "Scan Hardware",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._on_scan,
            style=ft.ButtonStyle(bgcolor=theme.ACCENT, color="#FFFFFF"),
        )
        self._load_btn = ft.ElevatedButton(
            "Load Profile…",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self._on_load_profile,
        )
        self._save_btn = ft.ElevatedButton(
            "Save Profile",
            icon=ft.Icons.SAVE,
            on_click=self._on_save_profile,
            disabled=True,
        )
        self._content = ft.Column(spacing=8, expand=True, scroll=ft.ScrollMode.AUTO)

        self.controls = [
            heading_row(),
            action_bar(self._scan_btn, self._load_btn, self._save_btn, self._status_text),
            self._content,
        ]

    # ─── Actions ────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        """Called when this view becomes visible — refresh if profile exists."""
        if self.app.profile:
            self._render_profile(self.app.profile)

    def _on_scan(self, _: ft.ControlEvent) -> None:
        if self._scanning:
            return
        self._scanning = True
        self._scan_btn.disabled = True
        self._scan_btn.text = "Scanning…"
        self._status_text.value = "Detecting hardware components…"
        self._content.controls.clear()
        self._content.controls.append(
            ft.Row([ft.ProgressRing(width=20, height=20, stroke_width=2),
                    ft.Text("Scanning your hardware…", color=theme.TEXT_SECONDARY)],
                   spacing=10)
        )
        self.update()

        thread = threading.Thread(target=self._run_scan, daemon=True)
        thread.start()

    def _run_scan(self) -> None:
        """Scanner runs in a background thread — posts results via page.update()."""
        try:
            from ..scanners import get_scanner
            scanner = get_scanner()
            profile = scanner.scan()
            self.app.page.run_thread(
                self._scan_complete, profile, None,
            )
        except Exception as exc:
            self.app.page.run_thread(
                self._scan_complete, None, str(exc),
            )

    def _scan_complete(self, profile: dict | None, error: str | None) -> None:
        """Update the UI from the main thread after scan finishes."""
        self._scanning = False
        self._scan_btn.disabled = False
        self._scan_btn.text = "Scan Hardware"

        if error:
            self._status_text.value = f"Scan failed: {error}"
            self._status_text.color = "#F44336"
            self._content.controls = [
                theme.alert_banner(error, severity="error"),
            ]
            self.update()
            return

        if profile:
            self.app.set_profile(profile)
            meta = profile.get("scan_metadata", {})
            warnings = profile.get("warnings", [])
            self._status_text.value = (
                f"Scan complete — {len(warnings)} warning(s). {meta.get('timestamp', '')}"
            )
            self._status_text.color = "#4CAF50"
            self._save_btn.disabled = False
            self._render_profile(profile)

    async def _on_load_profile(self, _: ft.ControlEvent) -> None:
        fp = ft.FilePicker()
        self.app.page.overlay.append(fp)
        self.app.page.update()
        try:
            result = await fp.pick_files(
                dialog_title="Load hardware_profile.json",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["json"],
            )
        finally:
            self.app.page.overlay.remove(fp)
            self.app.page.update()
        if not result:
            return
        path = result[0].path
        try:
            with open(path, encoding="utf-8") as fh:
                profile = json.load(fh)
            self.app.set_profile(profile)
            self._status_text.value = f"Loaded profile from {Path(path).name}"
            self._status_text.color = "#4CAF50"
            self._save_btn.disabled = False
            self._render_profile(profile)
        except (json.JSONDecodeError, OSError) as exc:
            self._status_text.value = f"Failed to load: {exc}"
            self._status_text.color = "#F44336"
        self.update()

    def _on_save_profile(self, _: ft.ControlEvent) -> None:
        if not self.app.profile:
            return
        out = Path("hardware_profile.json")
        out.write_text(json.dumps(self.app.profile, indent=2, ensure_ascii=False), encoding="utf-8")
        self._status_text.value = f"Saved to {out}"
        self._status_text.color = "#4CAF50"
        self.update()

    # ─── Profile rendering ───────────────────────────────────────────────────

    def _render_profile(self, p: dict) -> None:
        """Rebuild the content column from a hardware profile dict."""
        cards: list[ft.Control] = []
        meta = p.get("scan_metadata", {})

        # Header chip.
        root_tag = " 🔑 root" if meta.get("used_root") else " (no root)"
        cards.append(ft.Row([
            ft.Text(f"Scan: {meta.get('host_os','?')} {meta.get('host_release','')}"
                    f"  ·  {meta.get('timestamp','')}"
                    f"  ·  scanner v{meta.get('scanner_version','?')}"
                    f"  ·  {meta.get('warning_count', 0)} warning(s){root_tag}",
                    size=11, color=theme.TEXT_SECONDARY),
        ]))
        cards.append(ft.Divider(color=theme.DIVIDER))

        # ── CPU ──────────────────────────────────────────────────────────
        cpu = p.get("cpu") or {}
        cpu_rows: list[ft.Control] = [
            theme.info_row("Name", cpu.get("name")),
            theme.info_row("Vendor", cpu.get("vendor")),
            theme.info_row("Codename", cpu.get("codename")),
            theme.info_row("Generation", str(cpu.get("generation")) if cpu.get("generation") else None),
            theme.info_row("Cores / Threads", f"{cpu.get('cores','?')} / {cpu.get('threads','?')}"),
            theme.info_row("Architecture", cpu.get("architecture")),
            theme.info_row("Clock", f"{cpu.get('min_clock_ghz','?')} – {cpu.get('base_clock_ghz','?')} GHz"),
            theme.info_row("Virtualization", cpu.get("virtualization")),
            theme.info_row("Stepping", str(cpu.get("stepping")) if cpu.get("stepping") is not None else None),
            theme.info_row("Microcode", cpu.get("microcode")),
            theme.info_row("Governor", cpu.get("governor")),
            theme.info_row("Hybrid cores", "Yes (P/E)" if cpu.get("hybrid_cores") else "No"),
        ]
        flags = cpu.get("flags") or []
        if flags:
            cpu_rows.append(theme.info_row("Key flags", ", ".join(flags)))
        cpu_rows.append(ft.Row([
            ft.Text("macOS support:", size=13, color=theme.TEXT_SECONDARY, width=130),
            theme.status_badge(cpu.get("macos_support")),
        ], spacing=8))
        cards.append(theme.section_card("CPU", ft.Column(cpu_rows, spacing=4), icon=ft.Icons.MEMORY))

        # CPU Caches (deep).
        caches = p.get("cpu_caches") or {}
        if any(caches.values()):
            cards.append(theme.section_card("CPU Caches", ft.Column([
                theme.info_row("L1 Data", f"{caches.get('l1_data_kb')} KB" if caches.get("l1_data_kb") else None),
                theme.info_row("L1 Instruction", f"{caches.get('l1_inst_kb')} KB" if caches.get("l1_inst_kb") else None),
                theme.info_row("L2", f"{caches.get('l2_kb')} KB" if caches.get("l2_kb") else None),
                theme.info_row("L3", f"{caches.get('l3_kb')} KB" if caches.get("l3_kb") else None),
            ], spacing=4), icon=ft.Icons.SPEED))

        # ── GPUs ─────────────────────────────────────────────────────────
        gpus = p.get("gpu") or []
        gpu_rows = [[
            g.get("name", "?"),
            g.get("vendor", "?"),
            g.get("pci_id", "—"),
            g.get("gpu_gen", ""),
            g.get("kernel_driver", "—"),
            "iGPU" if g.get("is_integrated") else "dGPU",
        ] for g in gpus]
        gpu_content: list[ft.Control] = [
            theme.data_table(["Name", "Vendor", "PCI ID", "Gen", "Driver", "Type"], gpu_rows),
        ]
        for g in gpus:
            support_row = ft.Row([
                ft.Text(f"{g.get('name','?')}:", size=12, color=theme.TEXT_SECONDARY),
                theme.status_badge(g.get("macos_support")),
            ], spacing=6)
            gpu_content.append(support_row)
            if g.get("drm_connectors"):
                conn_strs = [f"{c['name']} ({c['status']})" for c in g["drm_connectors"]]
                gpu_content.append(
                    theme.info_row("Connectors", ", ".join(conn_strs)))
            if g.get("gpu_total_mem_mb"):
                gpu_content.append(
                    theme.info_row("VRAM", f"{g['gpu_total_mem_mb']} MB"))
        cards.append(theme.section_card(
            f"GPU ({len(gpus)})",
            ft.Column(gpu_content, spacing=6),
            icon=ft.Icons.MONITOR,
        ))

        # ── Motherboard ──────────────────────────────────────────────────
        mobo = p.get("motherboard") or {}
        mobo_rows: list[ft.Control] = [
            theme.info_row("Vendor", mobo.get("vendor")),
            theme.info_row("Model", mobo.get("model")),
            theme.info_row("Chipset", mobo.get("chipset")),
            theme.info_row("Chipset (full)", mobo.get("chipset_full")),
            theme.info_row("Chassis", mobo.get("chassis_type")),
            theme.info_row("BIOS", f"{mobo.get('bios_vendor','')} {mobo.get('bios_version','')}"),
            theme.info_row("BIOS Date", mobo.get("bios_date")),
        ]
        if mobo.get("board_serial"):
            mobo_rows.append(theme.info_row("Board Serial", mobo["board_serial"]))
        if mobo.get("system_serial"):
            mobo_rows.append(theme.info_row("System Serial", mobo["system_serial"]))
        if mobo.get("system_uuid"):
            mobo_rows.append(theme.info_row("System UUID", mobo["system_uuid"]))
        if mobo.get("bios_rom_size"):
            mobo_rows.append(theme.info_row("BIOS ROM", mobo["bios_rom_size"]))
        if mobo.get("iommu_enabled") is not None:
            iommu_str = f"{'Enabled' if mobo['iommu_enabled'] else 'Disabled'}"
            if mobo.get("iommu_type"):
                iommu_str += f" ({mobo['iommu_type']})"
            if mobo.get("iommu_groups"):
                iommu_str += f" — {mobo['iommu_groups']} groups"
            mobo_rows.append(theme.info_row("IOMMU", iommu_str))
        if mobo.get("acpi_tables"):
            mobo_rows.append(theme.info_row("ACPI Tables", ", ".join(mobo["acpi_tables"][:10])))
        cards.append(theme.section_card("Motherboard", ft.Column(mobo_rows, spacing=4),
                                         icon=ft.Icons.DEVELOPER_BOARD))

        # ── Audio ────────────────────────────────────────────────────────
        audio = p.get("audio") or {}
        audio_rows: list[ft.Control] = [
            theme.info_row("Codec", audio.get("codec")),
            theme.info_row("Codec ID", audio.get("codec_id")),
            theme.info_row("Layout ID", str(audio.get("layout_id")) if audio.get("layout_id") else None),
            theme.info_row("Kext", audio.get("kext")),
            theme.info_row("ALSA Cards", str(audio.get("alsa_card_count")) if audio.get("alsa_card_count") else None),
        ]
        all_codecs = audio.get("all_codecs") or []
        if len(all_codecs) > 1:
            for i, c in enumerate(all_codecs):
                audio_rows.append(theme.info_row(
                    f"Codec #{i+1}", f"{c.get('codec','')} ({c.get('codec_id','')})"))
        if audio.get("hdmi_audio_devices"):
            for ha in audio["hdmi_audio_devices"]:
                audio_rows.append(theme.info_row("HDMI Audio", f"{ha.get('name','')} [{ha.get('pci_id','')}]"))
        cards.append(theme.section_card("Audio", ft.Column(audio_rows, spacing=4),
                                         icon=ft.Icons.SPEAKER))

        # ── Ethernet ─────────────────────────────────────────────────────
        eths = p.get("ethernet") or []
        if eths:
            eth_rows = [[
                e.get("name", "?"),
                e.get("vendor", "?"),
                e.get("pci_id", "—"),
                e.get("kext", "—"),
                e.get("kernel_driver", "—"),
                e.get("interface", "—"),
            ] for e in eths]
            cards.append(theme.section_card(
                f"Ethernet ({len(eths)})",
                theme.data_table(["Name", "Vendor", "PCI ID", "Kext", "Driver", "Interface"], eth_rows),
                icon=ft.Icons.LAN,
            ))

        # ── WiFi + Bluetooth ─────────────────────────────────────────────
        wireless = p.get("wireless") or {}
        wl_controls: list[ft.Control] = []
        if wireless.get("wifi_chip"):
            wl_controls.append(theme.info_row("WiFi", wireless["wifi_chip"]))
            wl_controls.append(theme.info_row("WiFi Driver", wireless.get("wifi_driver")))
            wl_controls.append(theme.info_row("WiFi Interface", wireless.get("wifi_interface")))
            wl_controls.append(theme.info_row("WiFi Kext", wireless.get("wifi_kext")))
            wl_controls.append(ft.Row([
                ft.Text("WiFi support:", size=12, color=theme.TEXT_SECONDARY, width=130),
                theme.status_badge(wireless.get("wifi_support")),
            ], spacing=8))
        if wireless.get("bluetooth_chip"):
            wl_controls.append(theme.info_row("Bluetooth", wireless["bluetooth_chip"]))
            wl_controls.append(theme.info_row("BT Vendor", wireless.get("bt_vendor")))
        if wireless.get("airdrop_support"):
            wl_controls.append(theme.info_row("AirDrop", "Supported ✓"))
        elif wireless.get("wifi_chip"):
            wl_controls.append(theme.info_row("AirDrop", "Not supported (non-Broadcom)"))
        if wl_controls:
            cards.append(theme.section_card(
                "Wireless", ft.Column(wl_controls, spacing=4), icon=ft.Icons.WIFI))

        # ── Storage ──────────────────────────────────────────────────────
        disks = p.get("storage") or []
        if disks:
            disk_rows = [[
                d.get("name", "?"),
                f"{d.get('size_gb','?')} GB",
                d.get("type", "?").upper(),
                "HDD" if d.get("rotational") else "SSD",
                d.get("serial", "—") or "—",
                d.get("partition_table", "—") or "—",
            ] for d in disks]
            cards.append(theme.section_card(
                f"Storage ({len(disks)})",
                theme.data_table(["Name", "Size", "Interface", "Type", "Serial", "PT"], disk_rows),
                icon=ft.Icons.STORAGE,
            ))

        # ── Memory ───────────────────────────────────────────────────────
        mem = p.get("memory") or {}
        if mem.get("total_gb"):
            mem_rows: list[ft.Control] = [
                theme.info_row("Total", f"{mem.get('total_gb')} GB"),
                theme.info_row("Available", f"{mem.get('available_gb')} GB" if mem.get("available_gb") is not None else None),
                theme.info_row("Swap", f"{mem.get('swap_total_gb')} GB" if mem.get("swap_total_gb") is not None else None),
                theme.info_row("Type", mem.get("type")),
                theme.info_row("Speed", f"{mem.get('speed_mhz')} MT/s" if mem.get("speed_mhz") else None),
                theme.info_row("Form Factor", mem.get("form_factor")),
                theme.info_row("Slots", f"{mem.get('slots_used','?')}/{mem.get('slots_total','?')}" if mem.get("slots_total") else None),
                theme.info_row("Max Capacity", f"{mem.get('max_capacity_gb')} GB" if mem.get("max_capacity_gb") else None),
            ]
            # Show individual DIMMs.
            dimms = mem.get("dimms") or []
            for i, d in enumerate(dimms):
                dimm_str = f"{d.get('size', '?')}"
                if d.get("type"):
                    dimm_str += f" {d['type']}"
                if d.get("speed"):
                    dimm_str += f" @ {d['speed']}"
                if d.get("manufacturer"):
                    dimm_str += f" ({d['manufacturer']})"
                if d.get("part_number"):
                    dimm_str += f" [{d['part_number'].strip()}]"
                mem_rows.append(theme.info_row(
                    d.get("locator", f"DIMM {i+1}"), dimm_str))
            cards.append(theme.section_card("Memory", ft.Column(mem_rows, spacing=4),
                                             icon=ft.Icons.RAMEN_DINING))

        # ── USB Controllers ──────────────────────────────────────────────
        usbs = p.get("usb_controllers") or []
        if usbs:
            usb_rows = [[
                u.get("name", "?"),
                u.get("vendor", "?"),
                u.get("controller_type", "—"),
                u.get("kernel_driver", "—"),
                str(u.get("port_count", "—")),
            ] for u in usbs]
            cards.append(theme.section_card(
                f"USB Controllers ({len(usbs)})",
                ft.Column([
                    theme.data_table(["Name", "Vendor", "Type", "Driver", "Ports"], usb_rows),
                    ft.Text("USB port mapping recommended for macOS (15-port limit)",
                            size=11, color=theme.TEXT_SECONDARY, italic=True),
                ], spacing=4),
                icon=ft.Icons.USB,
            ))

        # ── USB Devices (deep) ───────────────────────────────────────────
        usb_devs = p.get("usb_devices") or []
        if usb_devs and isinstance(usb_devs, list):
            usb_dev_rows = [[
                d.get("name", "?"),
                d.get("usb_id", "—"),
                d.get("category", "?"),
            ] for d in usb_devs]
            cards.append(theme.section_card(
                f"USB Devices ({len(usb_devs)})",
                theme.data_table(["Name", "USB ID", "Category"], usb_dev_rows),
                icon=ft.Icons.USB,
            ))

        # ── Input devices ────────────────────────────────────────────────
        inputs = p.get("input_devices") or {}
        if inputs.get("ps2_present"):
            cards.append(theme.section_card(
                "Input", ft.Column([
                    ft.Text("PS/2 port detected — VoodooPS2 required", size=13,
                            color=theme.TEXT_PRIMARY),
                    theme.info_row("Keyboard", inputs.get("keyboard_bus")),
                    theme.info_row("Mouse", inputs.get("mouse_bus")),
                ], spacing=4),
                icon=ft.Icons.KEYBOARD,
            ))

        # ── Boot Info (deep) ─────────────────────────────────────────────
        boot = p.get("boot_info") or {}
        if boot:
            boot_rows: list[ft.Control] = [
                theme.info_row("Boot Mode", boot.get("mode")),
                theme.info_row("Secure Boot", "Enabled" if boot.get("secure_boot") else "Disabled" if boot.get("secure_boot") is not None else "N/A"),
            ]
            pt_list = boot.get("partition_tables") or []
            for pt in pt_list:
                boot_rows.append(theme.info_row(
                    pt.get("device", "?"),
                    f"{pt.get('table', 'unknown')} — {pt.get('name', '')}"))
            if boot.get("note"):
                boot_rows.append(ft.Text(boot["note"], size=11, color="#FF9800", italic=True))
            cards.append(theme.section_card("Boot / Firmware", ft.Column(boot_rows, spacing=4),
                                             icon=ft.Icons.POWER_SETTINGS_NEW))

        # ── Battery (deep) ───────────────────────────────────────────────
        battery = p.get("battery") or {}
        if battery.get("present"):
            bat_rows: list[ft.Control] = [
                theme.info_row("Batteries", str(battery.get("count", 0))),
                theme.info_row("Health", f"{battery.get('health_pct')}%" if battery.get("health_pct") else None),
                theme.info_row("Kext needed", "SMCBatteryManager.kext" if battery.get("needs_smbat_kext") else "None"),
            ]
            cards.append(theme.section_card("Battery", ft.Column(bat_rows, spacing=4),
                                             icon=ft.Icons.BATTERY_FULL))

        # ── TPM (deep) ───────────────────────────────────────────────────
        tpm = p.get("tpm") or {}
        if tpm.get("present"):
            cards.append(theme.section_card("TPM", ft.Column([
                theme.info_row("Present", "Yes"),
                theme.info_row("Version", tpm.get("version_major")),
            ], spacing=4), icon=ft.Icons.SECURITY))

        # ── Camera (deep) ────────────────────────────────────────────────
        camera = p.get("camera") or {}
        if camera.get("present"):
            cam_rows: list[ft.Control] = [
                theme.info_row("Detected", "Yes"),
            ]
            for cam in (camera.get("usb_cameras") or []):
                cam_rows.append(theme.info_row("USB Camera", cam))
            cards.append(theme.section_card("Camera", ft.Column(cam_rows, spacing=4),
                                             icon=ft.Icons.CAMERA_ALT))

        # ── Network MACs (deep) ──────────────────────────────────────────
        net_macs = p.get("network_macs") or {}
        if net_macs.get("interfaces"):
            mac_rows: list[ft.Control] = []
            for iface, mac in (net_macs["interfaces"] or {}).items():
                mac_rows.append(theme.info_row(iface, mac))
            if net_macs.get("primary_mac"):
                mac_rows.append(theme.info_row("SMBIOS ROM candidate", net_macs["primary_mac"]))
            cards.append(theme.section_card("Network MACs", ft.Column(mac_rows, spacing=4),
                                             icon=ft.Icons.ROUTER))

        # ── Display Ports ────────────────────────────────────────────────
        disp = p.get("display_ports") or {}
        if disp.get("connectors"):
            disp_rows: list[ft.Control] = []
            for c in disp["connectors"]:
                status_icon = "🟢" if c.get("status") == "connected" else "⚪"
                modes = c.get("modes") or []
                mode_str = f" — {modes[0]}" if modes else ""
                disp_rows.append(ft.Text(
                    f"  {status_icon}  {c.get('name', '?')}: {c.get('status', '?')}{mode_str}",
                    size=12, color=theme.TEXT_PRIMARY))
            summary = []
            if disp.get("hdmi"):
                summary.append(f"{disp['hdmi']} HDMI")
            if disp.get("displayport"):
                summary.append(f"{disp['displayport']} DP")
            if disp.get("vga"):
                summary.append(f"{disp['vga']} VGA")
            if disp.get("edp"):
                summary.append(f"{disp['edp']} eDP")
            disp_rows.insert(0, theme.info_row("Ports", " · ".join(summary) if summary else "None"))
            if disp.get("igpu_headless"):
                disp_rows.append(ft.Text("iGPU should be configured as headless (connectorless)",
                                          size=11, color="#FF9800", italic=True))
            cards.append(theme.section_card(
                f"Display Ports ({disp.get('total_connectors', 0)})",
                ft.Column(disp_rows, spacing=4),
                icon=ft.Icons.DESKTOP_WINDOWS,
            ))

        # ── NVRAM ────────────────────────────────────────────────────────
        nvram = p.get("nvram") or {}
        nvram_rows: list[ft.Control] = []
        if nvram.get("type"):
            nvram_rows.append(theme.info_row("Type", nvram["type"]))
        if nvram.get("host_bridge"):
            nvram_rows.append(theme.info_row("Host Bridge", nvram["host_bridge"]))
        if nvram.get("efi_vars_accessible") is not None:
            nvram_rows.append(theme.info_row("EFI Variables",
                f"Accessible ({nvram.get('efi_var_count',0)} vars)" if nvram["efi_vars_accessible"]
                else "Not accessible"))
        if nvram.get("recommendation"):
            nvram_rows.append(ft.Text(nvram["recommendation"], size=11, color="#FF9800", italic=True))
        if nvram_rows:
            cards.append(theme.section_card("NVRAM", ft.Column(nvram_rows, spacing=4),
                                             icon=ft.Icons.DATA_USAGE))

        # ── All PCI Devices (deep) ───────────────────────────────────────
        all_pci = p.get("all_pci") or []
        if all_pci and isinstance(all_pci, list):
            pci_rows = [[
                d.get("slot", "?"),
                d.get("class", "?"),
                d.get("name", "?"),
                d.get("vendor", "?"),
                d.get("pci_id", "—"),
            ] for d in all_pci]
            cards.append(theme.section_card(
                f"All PCI Devices ({len(all_pci)})",
                theme.data_table(["Slot", "Class", "Name", "Vendor", "PCI ID"], pci_rows),
                icon=ft.Icons.DEVICE_HUB,
            ))

        # ── Warnings ─────────────────────────────────────────────────────
        warnings = p.get("warnings") or []
        if warnings:
            warn_controls: list[ft.Control] = []
            for w in warnings:
                sev = w.get("severity", "info")
                icon = {"error": ft.Icons.ERROR, "warn": ft.Icons.WARNING,
                        "info": ft.Icons.INFO}.get(sev, ft.Icons.INFO)
                color = {"error": "#F44336", "warn": "#FF9800", "info": "#1976D2"}.get(sev, theme.TEXT_SECONDARY)
                root_note = "  [needs root]" if w.get("needs_root") else ""
                warn_controls.append(ft.Row([
                    ft.Icon(icon, size=14, color=color),
                    ft.Text(f"{w.get('field','?')}: {w.get('message','?')}{root_note}",
                            size=12, color=color),
                ], spacing=6))
            cards.append(theme.section_card(
                f"Warnings ({len(warnings)})",
                ft.Column(warn_controls, spacing=4),
                icon=ft.Icons.WARNING_AMBER,
            ))

        self._content.controls = cards
        self.update()


# ─── Helper constructors ───────────────────────────────────────────────────────

def heading_row() -> ft.Container:
    return ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.RADAR, size=28, color=theme.ACCENT),
            ft.Text("Hardware Scanner", size=20, weight=ft.FontWeight.BOLD,
                    color=theme.TEXT_PRIMARY),
        ], spacing=10),
        margin=ft.Margin.only(bottom=12),
    )


def action_bar(
    scan_btn: ft.ElevatedButton,
    load_btn: ft.ElevatedButton,
    save_btn: ft.ElevatedButton,
    status: ft.Text,
) -> ft.Container:
    return ft.Container(
        content=ft.Row([
            scan_btn,
            load_btn,
            save_btn,
            ft.Container(expand=True),
            status,
        ], spacing=10, alignment=ft.MainAxisAlignment.START),
        margin=ft.Margin.only(bottom=12),
    )
