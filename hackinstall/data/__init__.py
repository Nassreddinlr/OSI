"""Bundled data tables + lookup helpers.

Loads the JSON files shipped in ``data/`` and exposes typed lookup functions.
Phase 1 uses these to enrich raw detected hardware (PCI IDs → names/kexts,
CPU model string → codename/microarch, audio codec → AppleALC layout-id).

Tables are plain JSON so they can be updated without touching Python code —
this is the plan's 'updatable without rebuild' requirement.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    """Load a JSON data file, stripping the ``_``-prefixed comment keys."""
    path = _DATA_DIR / name
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return {k: v for k, v in data.items() if not k.startswith("_")}


# ─── PCI ID database ──────────────────────────────────────────────────────────

def normalize_pci_id(vendor: str, device: str) -> str:
    """Turn ``'8086'`` / ``'1916'`` (or ``'0x8086'``) into ``'8086:1916'``."""
    v = vendor.lower().replace("0x", "").strip()
    d = device.lower().replace("0x", "").strip()
    return f"{v}:{d}"


def pci_lookup(pci_id: str) -> dict | None:
    """Look up a PCI device by ``'vendor:device'`` (e.g. ``'8086:156f'``).

    Returns the device dict or ``None`` if unknown. Unknown devices are
    *expected* — the curated DB only covers hackintosh-relevant hardware.
    The caller records a warning so Phase 2 can ask the user.
    """
    return _load("pci_ids.json")["devices"].get(pci_id.lower())


def vendor_name(vendor_id: str) -> str | None:
    """Map a PCI vendor ID to a human name (``'8086'`` → ``'Intel'``)."""
    return _load("pci_ids.json")["vendors"].get(vendor_id.lower().replace("0x", ""))


# ─── CPU codename / microarch ─────────────────────────────────────────────────

def cpu_lookup(model_string: str, vendor: str) -> dict:
    """Match a CPU model string against the codename table.

    Returns a dict with at least ``codename``, ``microarch``, ``generation``,
    ``macos_support``. Unknown CPUs get ``codename=None`` and
    ``macos_support='unknown'`` — never raises.
    """
    table = _load("cpu_codenames.json")
    haystack = model_string.lower()

    # Vendor-specific keys first (more precise), then a generic fallback.
    vendor_key = "intel" if vendor.lower() == "intel" else "amd"
    for key, info in table.get(vendor_key, {}).items():
        if key in haystack:
            return dict(info)
    # Cross-vendor fallback (e.g. bare "xeon")
    for key, info in table.get("intel", {}).items():
        if key in haystack and "xeon" in key:
            return dict(info)

    return {
        "codename": None,
        "microarch": None,
        "generation": None,
        "macos_support": "unknown",
        "has_igpu": None,
    }


# ─── Audio codec → AppleALC layout-id ─────────────────────────────────────────

def audio_layout(codec_id: str | None) -> tuple[str | None, int | None]:
    """Map a normalized codec id (``'10ec:0293'``) to (codec_name, layout_id).

    Returns ``(None, None)`` for unknown codecs — caller records a warning.
    """
    if not codec_id:
        return None, None
    entry = _load("audio_layouts.json")["layouts"].get(codec_id.lower())
    if not entry:
        return None, None
    return entry["codec"], entry["layout_id"]


# ─── SMBIOS target (Phase 2 will refine; heuristic stub for Phase 1) ──────────

def smbios_target_hint(cpu: dict, motherboard: dict) -> str | None:
    """Rough SMBIOS family guess for display only.

    Real SMBIOS selection (including Intel vs AMD, iGPU vs headless, laptop
    vs desktop) happens in Phase 2's ``smbios_gen.py``. This just gives the
    user a hint in the scan report.
    """
    support = cpu.get("macos_support")
    if support in ("none", "unknown", "dropped"):
        return None
    vendor = cpu.get("vendor", "").lower()
    chassis = motherboard.get("chassis_type", "desktop")
    if vendor == "intel":
        gen = cpu.get("generation")
        if gen and gen >= 12:
            return "iMacPro1,1" if chassis == "desktop" else "MacBookPro18,x"
        if gen and gen >= 8:
            return "iMac19,1" if chassis == "desktop" else "MacBookPro16,x"
        return "iMac18,3" if chassis == "desktop" else "MacBookPro14,x"
    if vendor == "amd":
        return "MacPro7,1"
    return None
