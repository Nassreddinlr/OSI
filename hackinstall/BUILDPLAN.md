# BuildPlan — the internal decision contract for Phase 2

## Why this exists

Phase 2 has two jobs that **must stay separate**:

1. **Decide** what the EFI needs (kexts, quirks, SSDTs, SMBIOS, boot-args).
2. **Write** that decision into `config.plist` + the `EFI/` folder.

This file documents #1 — the **BuildPlan**. It is a plain Python dict that
the decision engine (`core/decisions.py`) produces and the plist generator
(`core/config_generator.py`) consumes. Keeping them separate means:

- The BuildPlan can be printed/inspected before writing any files → **no surprises**.
- The decision engine has zero filesystem/plist knowledge → **unit-testable**.
- Each rule in `compat_matrix.json` maps to a BuildPlan field → **auditable**.

## Shape

```jsonc
{
  "plan_metadata": {
    "generated_from": "hardware_profile.json",
    "macos_target": "ventura",
    "opencore_version": "1.0.3",
    "decisions_version": "1.0.0",
    "timestamp": "2026-06-21T...",
    "hardware_summary": { ... }
  },

  "smbios": {
    "model": "iMacPro1,1",
    "serial": "C02X...",
    "board_serial": "C02X...",      // MLB — 17-char (serial + 5 hex)
    "uuid": "A8B3...",
    "rom": "001122334455",
    "system_product_name": "iMacPro1,1",
    "system_uuid": "...",
    "mlb": "...",
    "system_serial": "..."
  },

  "kexts": [
    // DEPENDENCY-ORDERED. Lilu ALWAYS first, VirtualSMC second.
    { "id": "Lilu", "version": "1.6.5", "reason": "core: kernel patching framework" }
  ],

  "boot_args": {
    "debug":   "-v keepsyms=1 debug=0x100",
    "release": "-v",
    "active":  "debug"
  },

  "quirks": {
    "Kernel": {
      "AppleXcpmCfgLock": false,
      "DisableIoMapper": false,
      "PanicNoKextDump": true,
      "PowerTimeoutKernelPanic": true
    },
    "Booter": {
      "AvoidRuntimeDefrag": true,
      "ProvideCustomSlide": true,
      "RebuildAppleMemoryMap": true,
      "SyncRuntimePermissions": true
    }
  },

  "ssdts": [
    { "name": "SSDT-PLUG", "when": "always (Intel)", "source": "bundled" }
  ],

  "acpi_patches": [],

  "config_notes": [
    "Intel Skylake (gen 6): macOS support DROPPED in Sonoma 14.4+."
  ],

  "blockers": [],
  "warnings": []
}
```

## How a field flows from hardware → BuildPlan → config.plist

Example: CFG Lock.

```
hardware_profile.json
  cpu.vendor = "Intel"
                 ↓
compat_matrix.json
  quirks.intel.skylake.AppleXcpmCfgLock = true
                 ↓
decisions.py
  BuildPlan.quirks.Kernel.AppleXcpmCfgLock = true
                 ↓
config_generator.py
  writes: <key>AppleXcpmCfgLock</key><true/>
```

## Blockers vs warnings

A **blocker** is a hard stop — EFI generation should not complete:
- CPU with `macos_support: "none"` or `"dropped"` with no compatible target.

A **warning** is soft — proceed but surface to user:
- Memory type unknown (needs root), WiFi partial support.
