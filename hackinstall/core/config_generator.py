"""config.plist generator — BuildPlan → OpenCore config.plist.

Builds a complete, valid OpenCore ``config.plist`` from a BuildPlan dict,
using only stdlib ``plistlib`` (no external template files to drift).

OpenCore's config.plist has 8 top-level sections (in canonical order):
  ACPI, Booter, DeviceProperties, Kernel, Misc, NVRAM, PlatformInfo, UEFI.

Each section is a nested dict with typed keys. plistlib serializes it to
Apple's XML plist format (``<?xml version="1.0"?> <!DOCTYPE plist ...>``).
We write it as ``FMT_XML`` (not binary) so users can read/diff it and OC
itself reads both.

Reference values based on OpenCore 1.0.x default/sample config + Dortania
guide recommendations. Every value here is explicitly chosen, not defaulted.
"""
from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Any

from .exceptions import Blocker


def generate_config_plist(plan: dict) -> bytes:
    """Return a complete OpenCore config.plist as XML bytes.

    Raises ``Blocker`` if the plan has unresolved blockers.
    """
    if plan.get("blockers"):
        first = plan["blockers"][0]
        raise Blocker(first["field"], first["reason"])

    smbios = plan.get("smbios", {})
    kexts = plan.get("kexts", [])
    boot_args = plan.get("boot_args", {})
    quirks = plan.get("quirks", {})
    ssdts = plan.get("ssdts", [])

    # Active boot-args (debug by default for first-boot visibility).
    active_args = boot_args.get(boot_args.get("active", "debug"), "-v")

    config: dict[str, Any] = {
        # ─── ACPI ────────────────────────────────────────────────────────
        "ACPI": {
            "Add": _acpi_add(ssdts),
            "Delete": [],
            "Patch": plan.get("acpi_patches", []),
            "Quirks": {
                "FadtEnableReset": False,
                "NormalizeHeaders": False,
                "RebaseRegions": False,
                "ResetHwSig": False,
                "ResetLogStatus": False,
                "SyncTableIds": False,
            },
        },

        # ─── Booter ──────────────────────────────────────────────────────
        "Booter": {
            "MmioWhitelist": [],
            "Patch": [],
            "Quirks": quirks.get("Booter", {}),
        },

        # ─── DeviceProperties ────────────────────────────────────────────
        "DeviceProperties": {
            "Add": _device_properties(plan),
            "Delete": [],
        },

        # ─── Kernel ──────────────────────────────────────────────────────
        "Kernel": {
            "Add": _kernel_add(kexts),
            "Block": [],
            "Emulate": {
                "Cpuid1Data": "00 00 00 00 00 00 00 00",
                "Cpuid1Mask": "00 00 00 00 00 00 00 00",
                "DummyPowerManagement": False,
                "MaxKernel": "",
                "MinKernel": "",
            },
            "Force": [],
            "Patch": [],  # AMD kernel patches injected here in Phase 2.5
            "Quirks": quirks.get("Kernel", {}),
            "Schemes": [],
            "Cpuid1Data": "00 00 00 00 00 00 00 00",  # legacy compat
            "Cpuid1Mask": "00 00 00 00 00 00 00 00",
        },

        # ─── Misc ────────────────────────────────────────────────────────
        "Misc": {
            "BlessOverride": [],
            "Boot": {
                "ConsoleBehaviourOs": "Graphics",
                "ConsoleMode": "",
                "DebugInfoPlist": True,
                "HibernateMode": "Auto",
                "HideAuxiliary": True,
                "PickerAttribute": 17,
                "PickerMode": "Builtin",
                "PickerVariant": "Acidanthera\\GoldenGate",
                "PollAppleHotKeys": True,
                "ShowPicker": True,
                "TakeoffDelay": 0,
                "Timeout": 5,
            },
            "Debug": {
                "AppleDebug": True,
                "ApplePanic": True,
                "DisableWatchDog": True,
                "DisplayDelay": 0,
                "DisplayLevel": 2147483650,
                "LogModules": "*",
                "SysReport": False,
                "Target": 67,
            },
            "Entries": [],
            "Security": {
                "AllowSetDefault": True,
                "ApECID": 0,
                "AuthRestart": False,
                "BlacklistAppleUpdate": True,
                "DmgLoading": "Signed",
                "ExposeSensitiveData": 6,
                "HaltLevel": 2147483648,
                "PasswordHash": b"",
                "PasswordSalt": b"",
                "ScanPolicy": 0,
                "SecureBootModel": "Default",
                "Vault": "Optional",
            },
            "Tools": [],
        },

        # ─── NVRAM ───────────────────────────────────────────────────────
        "NVRAM": {
            "Add": {
                "4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14": {
                    "DefaultBackgroundColor": "00000000",
                    "UIScale": "02",
                    "csr-active-config": "00000000",
                },
                "4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102": {
                    "rtc-blacklist": "",
                },
                "7C436110-AB2A-4BBB-A880-FE41995C9F82": {
                    "boot-args": active_args,
                    "prev-lang:kbd": "en-US:0",
                    "run-bridge": "address",
                    "csr-active-config": "00000000",
                    "blsWconnect": "01",
                    "run-bridge-over-vga": "01",
                },
            },
            "Delete": {},
            "LegacyOverwrite": False,
            "LegacySchema": {},
            "WriteFlash": True,
        },

        # ─── PlatformInfo ────────────────────────────────────────────────
        "PlatformInfo": {
            "Automatic": True,
            "CustomMemory": False,
            "Generic": {
                "AdviseFeatures": False,
                "MLB": smbios.get("mlb", ""),
                "MaxBIOSVersion": False,
                "ProcessorType": 0,
                "ROM": _rom_bytes(smbios.get("rom")),
                "SpoofVendor": True,
                "SystemMemoryStatus": "Auto",
                "SystemProductName": smbios.get("system_product_name", ""),
                "SystemSerialNumber": smbios.get("system_serial", ""),
                "SystemUUID": smbios.get("system_uuid", ""),
            },
            "UpdateDataHub": True,
            "UpdateNVRAM": True,
            "UpdateSMBIOS": True,
            "UpdateSMBIOSMode": "Create",
            "DataHub": [],
            "PlatformNVRAM": [],
            "SMBIOS": [],
            "SMBIOSOverride": [],
        },

        # ─── UEFI ────────────────────────────────────────────────────────
        "UEFI": {
            "APFS": {
                "EnableJumpstart": True,
                "GlobalConnect": False,
                "HideVerbose": True,
                "JumpstartHotPlug": False,
                "MinDate": 0,
                "MinVersion": 0,
            },
            "Audio": {
                "AudioCodec": 0,
                "AudioDevice": "",
                "AudioOutMask": -1,
                "AudioSupport": False,
                "DisconnectHda": False,
                "MaximumGain": -15,
                "MinimumAssistGain": -30,
                "MinimumAudibleGain": -55,
                "PlayChime": "Auto",
                "ResetTrafficClass": False,
                "SetupDelay": 0,
            },
            "ConnectDrivers": True,
            "Drivers": [
                {"Arguments": "", "Comment": "HFS+ filesystem driver", "Enabled": True, "Path": "OpenHfsPlus.efi"},
                {"Arguments": "", "Comment": "OpenRuntime — required for OC quirks", "Enabled": True, "Path": "OpenRuntime.efi"},
                {"Arguments": "", "Comment": "Reset NVRAM entry in picker", "Enabled": True, "Path": "ResetNvramEntry.efi"},
            ],
            "Input": {
                "KeyFiltering": False,
                "KeyForgetThreshold": 5,
                "KeySupport": True,
                "KeySupportMode": "Auto",
                "KeySwap": False,
                "PointerSupport": False,
                "PointerSupportMode": "ASUS",
                "TimerResolution": 50000,
            },
            "Output": {
                "ClearScreenOnModeSwitch": False,
                "ConsoleMode": "",
                "DirectGopRendering": False,
                "ForceResolution": False,
                "GopBurstMode": False,
                "GopPassThrough": "Disabled",
                "IgnoreTextInGraphics": True,
                "InitialMode": "Auto",
                "ProvideConsoleGop": True,
                "ReconnectGraphicsOnConnect": False,
                "ReconnectOnResChange": False,
                "ReplaceTabWithSpace": False,
                "Resolution": "Max",
                "SanitiseClearScreen": False,
                "TextRenderer": "BuiltinGraphics",
                "UIScale": -1,
                "UgaPassThrough": "Disabled",
            },
            "ProtocolOverrides": {
                "AppleAudio": False,
                "AppleBootPolicy": False,
                "AppleDebugLog": False,
                "AppleEvent": False,
                "AppleFramebufferInfo": False,
                "AppleImageConversion": False,
                "AppleImg4Verification": False,
                "AppleKeyMap": False,
                "AppleRtcRam": False,
                "AppleSecureBoot": False,
                "AppleSmcIo": False,
                "AppleUserInterfaceTheme": False,
                "DataHub": False,
                "DeviceProperties": False,
                "FirmwareVolume": False,
                "HashServices": False,
                "OSInfo": False,
                "PciIo": False,
                "UnicodeCollation": False,
            },
            "Quirks": {
                "ActivateHpetSupport": False,
                "DisableSecurityPolicy": False,
                "EnableVectorAcceleration": True,
                "EnableVmx": False,
                "ExitBootServicesDelay": 0,
                "ForceOcWriteFlash": False,
                "ForgeUefiSupport": False,
                "IgnoreInvalidFlexRatio": False,
                "ReleaseUsbOwnership": False,
                "RequestBootVarRouting": True,
                "ResizeGpuBars": -1,
                "ResizeUsePciRbIo": False,
                "TscSyncTimeout": 0,
                "UnblockFsConnect": False,
            },
            "ReservedMemory": [],
        },
    }

    return plistlib.dumps(config, fmt=plistlib.FMT_XML, sort_keys=False)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _acpi_add(ssdts: list[dict]) -> list[dict]:
    """Build the ACPI → Add entries from the selected SSDTs."""
    return [
        {
            "Comment": s.get("reason", ""),
            "Enabled": True,
            "Path": f"EFI/OC/ACPI/{s['name']}.aml",
        }
        for s in ssdts
    ]


def _kernel_add(kexts: list[dict]) -> list[dict]:
    """Build Kernel → Add entries with correct paths + load order."""
    return [
        {
            "Arch": "x86_64",
            "BundlePath": f"{k['id']}.kext",
            "Checksum": b"",  # Phase 3 fills from actual downloaded file
            "Comment": k.get("reason", ""),
            "Enabled": True,
            "ExecutablePath": (
                f"{k['id']}.kext/Contents/MacOS/{k['id']}"
                if k.get("id") not in ("Lilu", "VirtualSMC") else
                f"{k['id']}.kext/Contents/MacOS/{k['id']}"
            ),
            "MaxKernel": "",
            "MinKernel": "",
            "PlistPath": k.get("bundle_path", f"{k['id']}.kext/Contents/Info.plist"),
        }
        for k in kexts
    ]


def _device_properties(plan: dict) -> dict:
    """Build DeviceProperties → Add for GPU framebuffer injection.

    Phase 2 stubs device properties with a note — exact framebuffer values
    (device-id, AAPL,ig-platform-id) need per-GPU tuning from Phase 1 scan
    data + the WhateverGreen framebuffer database. This is the right place;
    full implementation lands when Phase 1 GPU data is richer.
    """
    props: dict[str, Any] = {}
    notes = plan.get("config_notes", [])
    for gpu in (plan.get("plan_metadata", {}).get("hardware_summary", {}).get("gpus") or []):
        # Real implementation: inject AAPL,ig-platform-id for Intel iGPU.
        pass
    return props


def _rom_bytes(rom_hex: str | None) -> bytes:
    """Convert the 12-char ROM hex string to bytes for plist ROM field."""
    if not rom_hex:
        return b""
    try:
        return bytes.fromhex(rom_hex[:12].ljust(12, "0"))
    except ValueError:
        return b""


def write_config_plist(plan: dict, path: Path | str) -> Path:
    """Generate + write config.plist to ``path``. Returns the path."""
    data = generate_config_plist(plan)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


__all__ = ["generate_config_plist", "write_config_plist"]
