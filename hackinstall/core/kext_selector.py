"""Kext selector — builds the dependency-ordered kext list.

OpenCore loads kexts in the order listed in config.plist → Kernel → Add.
Dependency order matters: Lilu MUST be first (it's the patcher framework
that all other Acidanthera kexts depend on), then VirtualSMC (the SMC
emulator that plugins attach to). Wrong order = kernel panic.

This module reads the kext rules from ``compat_matrix.json`` and the detected
hardware from ``hardware_profile.json`` to produce the ordered list.

Order (by design, not chance):
  1. Lilu            (core, always)
  2. VirtualSMC      (core, always)
  3. CPU-specific    (SMCProcessor/SMCSuperIO for Intel; SMCAMDProcessor for AMD)
  4. GPU             (WhateverGreen)
  5. Audio           (AppleALC)
  6. Ethernet        (IntelMausi / LucyRTL8125 / RealtekRTL8111)
  7. WiFi/BT         (AirportItlwm / IntelBluetoothFirmware / BlueToolFixup)
  8. Storage         (NVMeFix)
  9. Input           (VoodooPS2 if PS/2)
"""
from __future__ import annotations

from typing import Any

from ..data import _load


def select_kexts(profile: dict) -> list[dict[str, Any]]:
    """Return the dependency-ordered kext list for the given hardware profile.

    Each entry: ``{ id, version, source, reason, bundle_path }``.
    De-duplicates by id (first occurrence wins — core kexts always come first).
    """
    matrix = _load("compat_matrix.json")
    cpu = profile.get("cpu", {}) or {}
    gpus = profile.get("gpu", []) or []
    audio = profile.get("audio", {}) or {}
    ethernet = profile.get("ethernet", []) or []
    wireless = profile.get("wireless", {}) or {}
    storage = profile.get("storage", []) or []
    inputs = profile.get("input_devices", {}) or {}

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(entry: dict[str, Any]) -> None:
        kid = entry["id"]
        if kid in seen:
            return
        seen.add(kid)
        # Ensure bundle_path is always present for config_generator.
        entry.setdefault("bundle_path", f"{kid}.kext/Contents/Info.plist")
        selected.append(entry)

    # 1-2. Core (always).
    for entry in matrix["kexts_core"]:
        _add(dict(entry))

    # 3. CPU-specific.
    vendor = (cpu.get("vendor") or "").lower()
    cpu_rules = matrix.get("kexts_by_cpu", {}).get(vendor, {})
    for entry in cpu_rules.get("always", []):
        _add(dict(entry))

    # 4. GPU.
    for gpu in gpus:
        gpu_vendor = (gpu.get("vendor") or "").lower()
        gpu_support = gpu.get("macos_support")
        # WhateverGreen is needed for any Intel/AMD GPU.
        if gpu_vendor in ("intel", "amd") and gpu_support != "none":
            gpu_rules = matrix.get("kexts_by_gpu", {}).get(gpu_vendor, [])
            for entry in gpu_rules:
                _add(dict(entry))
        # Nvidia-only with no Intel iGPU = blocker, handled in decisions.py.
        elif gpu_vendor == "nvidia" and gpu_support == "none":
            # Only add WhateverGreen if there's also an Intel iGPU to patch.
            if any((g.get("vendor") or "").lower() == "intel" for g in gpus):
                for entry in matrix.get("kexts_by_gpu", {}).get("nvidia_dropped", []):
                    _add(dict(entry))

    # 5. Audio.
    if audio.get("kext") == "AppleALC.kext":
        _add({
            "id": "WhateverGreen",  # ensure WhateverGreen present for audio too
            "version": _kext_version(matrix, "WhateverGreen"),
            "source": "Acidanthera",
            "reason": "GPU patching (AppleALC companion — enables audio)",
        })
        _add({
            "id": "AppleALC",
            "version": "1.9.2",
            "source": "Acidanthera",
            "reason": f"Audio: {audio.get('codec','?')}, layout-id {audio.get('layout_id','?')}",
        })

    # 6. Ethernet.
    for eth in ethernet:
        kext = eth.get("kext") or ""
        if kext and kext != "native" and not kext.startswith("Unknown"):
            _add({
                "id": _kext_id_from_path(kext),
                "version": "1.0.7",  # default; matrix has specific versions
                "source": eth.get("vendor", "Mieze"),
                "reason": f"Ethernet: {eth.get('name','?')}",
            })

    # 7. WiFi + Bluetooth.
    wifi_kext = wireless.get("wifi_kext")
    if wifi_kext and "Itlwm" in wifi_kext:
        _add({
            "id": "AirportItlwm",
            "version": "2.2.0",
            "source": "OpenIntelWireless",
            "reason": f"WiFi: {wireless.get('wifi_chip','?')} (partial support)",
        })
    if wireless.get("bluetooth_chip"):
        bt_kext = wireless.get("bt_kext") or "IntelBluetoothFirmware.kext"
        _add({
            "id": _kext_id_from_path(bt_kext),
            "version": "2.4.0",
            "source": "OpenIntelWireless",
            "reason": f"Bluetooth: {wireless.get('bluetooth_chip','?')}",
        })
        # Monterey+ needs BlueToolFixup for non-Apple BT.
        _add({
            "id": "BlueToolFixup",
            "version": "1.1.2",
            "source": "Acidanthera",
            "reason": "Bluetooth stack fix for macOS Monterey+ (BrcmPatchRAM)",
        })

    # 8. Storage.
    for disk in storage:
        if (disk.get("type") or "").upper() == "NVME":
            _add({
                "id": "NVMeFix",
                "version": "1.1.2",
                "source": "Acidanthera",
                "reason": "NVMe power management fix",
            })

    # 9. Input.
    if inputs.get("ps2_present"):
        _add({
            "id": "VoodooPS2Controller",
            "version": "2.3.6",
            "source": "Acidanthera",
            "reason": "PS/2 keyboard/mouse driver",
        })

    return selected


def _kext_version(matrix: dict, kext_id: str) -> str:
    """Look up a kext version from the matrix (core table first)."""
    for entry in matrix.get("kexts_core", []):
        if entry.get("id") == kext_id:
            return entry.get("version", "1.0.0")
    return "1.0.0"


def _kext_id_from_path(path: str) -> str:
    """'IntelMausi.kext' → 'IntelMausi'."""
    return path.replace(".kext", "").replace("/", "")


__all__ = ["select_kexts"]
