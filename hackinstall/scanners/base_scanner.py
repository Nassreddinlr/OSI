"""Abstract scanner base class + shared utilities.

Defines the contract every concrete scanner must satisfy. Platform-specific
scanners (``LinuxScanner``, ``WindowsScanner``) implement only the ``_scan_*``
methods — the public ``scan()`` here orchestrates them, normalizes output,
and stamps metadata consistently.

Design: fail-soft. Every ``_scan_*`` method returns a dict; if it raises,
we catch, substitute an empty dict, and record a structured warning. The
profile is always complete-shaped; unknown fields are ``null``.
"""
from __future__ import annotations

import platform
import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable

from .. import __version__
from ..data import audio_layout, cpu_lookup, pci_lookup, smbios_target_hint, vendor_name


class ScanWarning(dict):
    """A structured warning entry. Behaves as a dict for JSON serialization."""


class BaseScanner(ABC):
    """Common skeleton for all platform scanners."""

    def __init__(self) -> None:
        self.warnings: list[dict] = []
        self.used_root: bool = False
        self.tool_versions: dict[str, str] = {}

    # ─── Public API ──────────────────────────────────────────────────────

    def scan(self) -> dict:
        """Run the full hardware scan and return a normalized profile dict."""
        self.warnings = []
        self.used_root = False
        # NOTE: do NOT reset self.tool_versions here — the concrete scanner's
        # __init__ populates it once and the values remain valid across scans.

        sections: list[tuple[str, Callable[[], dict]]] = [
            ("cpu", self._scan_cpu),
            ("gpu", self._scan_gpu),
            ("audio", self._scan_audio),
            ("ethernet", self._scan_ethernet),
            ("usb_controllers", self._scan_usb_controllers),
            ("wireless", self._scan_wireless),
            ("motherboard", self._scan_motherboard),
            ("storage", self._scan_storage),
            ("memory", self._scan_memory),
            ("input_devices", self._scan_input_devices),
            ("nvram", self._scan_nvram),
            ("display_ports", self._scan_display_ports),
            # ── Deep-scan sections (Phase 1.5) ──────────────────────
            ("all_pci", self._scan_all_pci),
            ("usb_devices", self._scan_usb_devices),
            ("battery", self._scan_battery),
            ("boot_info", self._scan_boot_info),
            ("network_macs", self._scan_network_macs),
            ("tpm", self._scan_tpm),
            ("camera", self._scan_camera),
            ("cpu_caches", self._scan_cpu_caches),
        ]

        profile: dict[str, Any] = {}
        for name, fn in sections:
            profile[name] = self._safe(fn, name)

        # Enrich with data-table lookups (shared across platforms).
        # Sections may be {} (failure) or a list (gpu/ethernet) — coerce safely.
        cpu_raw = profile.get("cpu")
        profile["cpu"] = self._enrich_cpu(cpu_raw if isinstance(cpu_raw, dict) else {})
        audio_raw = profile.get("audio")
        profile["audio"] = self._enrich_audio(audio_raw if isinstance(audio_raw, dict) else {})
        profile["gpu"] = [
            self._enrich_pci_device(g)
            for g in (profile["gpu"] if isinstance(profile.get("gpu"), list) else [])
        ]
        profile["ethernet"] = [
            self._enrich_pci_device(e)
            for e in (profile["ethernet"] if isinstance(profile.get("ethernet"), list) else [])
        ]

        # SMBIOS hint + compatibility summary for the scan report.
        profile["smbios_hint"] = smbios_target_hint(
            profile.get("cpu") or {}, profile.get("motherboard") or {}
        )

        profile["scan_metadata"] = self._metadata()
        profile["warnings"] = self.warnings
        return profile

    # ─── Helpers shared by subclasses ────────────────────────────────────

    def warn(
        self,
        field: str,
        message: str,
        severity: str = "warn",
        needs_root: bool = False,
    ) -> None:
        self.warnings.append(
            {
                "field": field,
                "message": message,
                "severity": severity,
                "needs_root": needs_root,
            }
        )

    def _safe(self, fn: Callable[[], Any], section: str) -> Any:
        """Run a section scanner; on any exception, fall back to [] or {} + warning.

        Some sections legitimately return a list (gpu, ethernet, storage,
        usb_controllers) — others return a dict. We accept either; only a
        non-dict/non-list result or a raised exception triggers the fallback.
        """
        try:
            result = fn()
            if result is None:
                result = {}
            if not isinstance(result, (dict, list)):
                raise TypeError(
                    f"{section} scanner returned {type(result)!r}, expected dict or list"
                )
            return result
        except Exception as exc:  # noqa: BLE001 — fail-soft is the whole point
            self.warn(
                field=section,
                message=f"Scanner section '{section}' failed: {exc}",
                severity="error",
            )
            # In verbose mode the traceback is invaluable; stash it on self.
            self._last_traceback = traceback.format_exc()
            return {}

    def _enrich_cpu(self, cpu: dict) -> dict:
        name = cpu.get("name") or ""
        vendor = cpu.get("vendor") or ""
        info = cpu_lookup(name, vendor)
        cpu.setdefault("codename", info.get("codename"))
        cpu.setdefault("microarch", info.get("microarch"))
        cpu.setdefault("generation", info.get("generation"))
        cpu.setdefault("amd_zen", info.get("amd_zen"))
        cpu.setdefault("macos_support", info.get("macos_support") or "unknown")
        cpu.setdefault("has_igpu", info.get("has_igpu"))
        return cpu

    def _enrich_audio(self, audio: dict) -> dict:
        codec_id = audio.get("codec_id")
        codec_name, layout_id = audio_layout(codec_id)
        audio.setdefault("codec", codec_name)
        audio.setdefault("layout_id", layout_id)
        audio.setdefault("kext", "AppleALC.kext")
        if codec_id and layout_id is None:
            self.warn(
                field="audio.layout_id",
                message=(
                    f"Audio codec '{codec_id}' not in AppleALC layout database. "
                    "Audio will need a manual layout-id; see Dortania audio guide."
                ),
            )
        return audio

    def _enrich_pci_device(self, dev: dict) -> dict:
        """Merge curated PCI-DB info (kext, macos_support, etc.) into a device."""
        # Normalize verbose vendor names to the short canonical form the schema
        # expects ('Intel Corporation' → 'Intel'). This is display + matching.
        _VENDOR_SHORT = {
            "intel corporation": "Intel",
            "advanced micro devices, inc.": "AMD",
            "amd": "AMD",
            "nvidia corporation": "Nvidia",
            "nvidia": "Nvidia",
            "realtek semiconductor co., ltd.": "Realtek",
            "broadcom inc. and subsidiaries": "Broadcom",
            "broadcom": "Broadcom",
        }
        v = (dev.get("vendor") or "").strip().lower()
        if v in _VENDOR_SHORT:
            dev["vendor"] = _VENDOR_SHORT[v]

        pci_id = dev.get("pci_id")
        if pci_id:
            entry = pci_lookup(pci_id)
            if entry:
                # Use DB name only if the device gave us none; otherwise keep
                # the richer detected name (e.g. 'HD Graphics 520' detail).
                dev.setdefault("name", entry.get("name"))
                dev.setdefault("vendor", vendor_name(pci_id.split(":")[0]))
                dev.setdefault("kext", entry.get("kext"))
                dev.setdefault("macos_support", entry.get("macos_support"))
                dev.setdefault("needs_patch", entry.get("needs_patch"))
                if "patch_note" in entry:
                    dev.setdefault("patch_note", entry["patch_note"])
                if entry.get("category") == "gpu":
                    dev.setdefault("gpu_gen", entry.get("gpu_gen"))
                    dev.setdefault("needs_agdp_patch", entry.get("needs_agdp_patch"))
            else:
                # Unknown but classifiable PCI device — record for Phase 2.
                self.warn(
                    field=f"pci.{pci_id}",
                    message=(
                        f"PCI device {pci_id} ({dev.get('name','?')}) not in "
                        "compatibility database. Phase 2 may need a manual kext decision."
                    ),
                    severity="info",
                )
        return dev

    def _metadata(self) -> dict:
        return {
            "host_os": platform.system(),
            "host_release": platform.version(),
            "host_machine": platform.machine(),
            "scanner_version": __version__,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "used_root": self.used_root,
            "tool_versions": self.tool_versions,
            "warning_count": len(self.warnings),
        }

    # ─── Abstract section scanners (implemented per-platform) ────────────

    @abstractmethod
    def _scan_cpu(self) -> dict: ...
    @abstractmethod
    def _scan_gpu(self) -> list | dict: ...
    @abstractmethod
    def _scan_audio(self) -> dict: ...
    @abstractmethod
    def _scan_ethernet(self) -> list | dict: ...
    @abstractmethod
    def _scan_usb_controllers(self) -> list | dict: ...
    @abstractmethod
    def _scan_wireless(self) -> dict: ...
    @abstractmethod
    def _scan_motherboard(self) -> dict: ...
    @abstractmethod
    def _scan_storage(self) -> list | dict: ...
    @abstractmethod
    def _scan_memory(self) -> dict: ...
    @abstractmethod
    def _scan_input_devices(self) -> dict: ...
    @abstractmethod
    def _scan_nvram(self) -> dict: ...
    @abstractmethod
    def _scan_display_ports(self) -> dict: ...
    # ── Deep-scan sections (Phase 1.5) ──────────────────────────────
    @abstractmethod
    def _scan_all_pci(self) -> list | dict: ...
    @abstractmethod
    def _scan_usb_devices(self) -> list | dict: ...
    @abstractmethod
    def _scan_battery(self) -> dict: ...
    @abstractmethod
    def _scan_boot_info(self) -> dict: ...
    @abstractmethod
    def _scan_network_macs(self) -> dict: ...
    @abstractmethod
    def _scan_tpm(self) -> dict: ...
    @abstractmethod
    def _scan_camera(self) -> dict: ...
    @abstractmethod
    def _scan_cpu_caches(self) -> dict: ...
