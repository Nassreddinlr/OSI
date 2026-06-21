"""SSDT builder — selects the SSDTs (ACPI patches) needed for the hardware.

SSDTs (System Service Descriptor Tables) are compiled ACPI patches injected
via OpenCore. macOS expects certain ACPI devices that PCs don't expose (or
expose differently). The standard ones:

  - SSDT-PLUG     : CPU power management (XCPM). Defines plugin-type=1 on CPU0.
                    Required on all Intel/AMD desktops for proper P-states.
  - SSDT-EC-USBX  : Fake Embedded Controller + USB power properties. macOS
                    expects an EC device; modern PCs have a real one (which we
                    rename) or need a fake one.
  - SSDT-PNLF     : Backlight control for laptop panels. Desktops don't need it.
  - SSDT-GPIO     : GPIO controller for laptop trackpad (VoodooI2C prerequisite).
  - SSDT-AWAC     : Fixes AWAC clock on Intel 300-series+ (B360/Z390 onwards).

Phase 2 SELECTS which SSDTs to use and records notes; the actual compiled
.aml binaries are bundled in data/ssdt_templates/ (Phase 3 downloads or we
ship precompiled ones). This module never fails — it always returns a list,
possibly empty.
"""
from __future__ import annotations

from ..data import _load


def select_ssdts(profile: dict) -> list[dict]:
    """Return the list of SSDTs needed for the given profile.

    Each entry: ``{ name, reason, source, when }``.
    """
    matrix = _load("compat_matrix.json")
    cpu = profile.get("cpu", {}) or {}
    motherboard = profile.get("motherboard", {}) or {}

    vendor = (cpu.get("vendor") or "").lower()
    chassis = motherboard.get("chassis_type", "desktop")

    selected: list[dict] = []

    # CPU-driven SSDTs (PLUG, EC-USBX).
    cpu_ssdt_rules = matrix.get("ssdts_by_cpu", {}).get(vendor, [])
    for entry in cpu_ssdt_rules:
        name = entry.get("name") or entry.get("serial")
        if not name:
            continue
        selected.append({
            "name": name,
            "reason": entry.get("reason", ""),
            "source": entry.get("source", "bundled"),
            "when": entry.get("when", "always"),
        })

    # Chassis-driven SSDTs (laptop-only: PNLF, GPIO).
    chassis_rules = matrix.get("ssdts_by_chassis", {}).get(chassis, [])
    for entry in chassis_rules:
        selected.append({
            "name": entry["name"],
            "reason": entry.get("reason", ""),
            "source": entry.get("source", "bundled"),
            "when": entry.get("when", f"always ({chassis})"),
        })

    # Modern Intel chipset extra: SSDT-AWAC for 300-series+.
    chipset = (motherboard.get("chipset") or "").upper()
    if vendor == "intel" and _is_modern_intel_chipset(chipset):
        for entry in matrix.get("ssdts_optional", []):
            if entry["name"] == "SSDT-AWAC":
                selected.append({
                    "name": "SSDT-AWAC",
                    "reason": entry.get("reason", "AWAC clock fix"),
                    "source": "bundled",
                    "when": "Intel 300-series+",
                })

    # De-duplicate by name (EC-USBX may appear in both CPU and optional lists).
    seen: set[str] = set()
    deduped: list[dict] = []
    for s in selected:
        if s["name"] in seen:
            continue
        seen.add(s["name"])
        deduped.append(s)

    return deduped


def _is_modern_intel_chipset(chipset: str) -> bool:
    """True for Intel 300-series and newer (B360/Z390/Z490/Z690/Z790/H470/etc.)."""
    modern_prefixes = ("Z3", "Z4", "Z5", "Z6", "Z7", "B3", "B4", "B6", "B7",
                       "H3", "H4", "H6", "H7", "Q3", "Q4", "Q6", "Q7")
    return any(chipset.startswith(p) for p in modern_prefixes)


__all__ = ["select_ssdts"]
