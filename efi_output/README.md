# HackInstall EFI — generated 2026-06-21T18:10:44Z

**macOS target:** ventura
**OpenCore:** 1.0.3

## Hardware
- CPU: Intel(R) Core(TM) i5-6300U CPU @ 2.40GHz (Skylake, gen skylake)
- GPU(s): Skylake-U GT2 [HD Graphics 520]
- Board: Dell Inc. 0VHKV0 [laptop]

## SMBIOS
- Model: `MacBookPro14,1`
- Serial: `C02YAPT74HTX`
- MLB: `C02YAPT74HTXPTACT`
- UUID: `7BEAEA73-9D1D-421A-B9AD-C64F5097B322`
- ROM: `02E7A36645FDF`

  ⚠ **Do NOT share these values publicly.** They are unique to this
  machine. See config.plist → PlatformInfo → Generic.

## Boot-args
- Active (debug): `-v keepsyms=1 debug=0x100`
- Debug: `-v keepsyms=1 debug=0x100`
- Release: `-v igfxfw=2`

## Kexts (load order)
- Lilu.kext v1.6.5 — Kernel patching framework — required by almost all other kexts
- VirtualSMC.kext v1.3.4 — Emulates Apple's SMC chip — required for macOS to boot
- SMCProcessor.kext v1.3.4 — Intel CPU temperature sensors (VirtualSMC plugin)
- SMCSuperIO.kext v1.3.4 — Motherboard fan/voltage sensors (VirtualSMC plugin)
- WhateverGreen.kext v1.6.9 — Intel iGPU patching
- AppleALC.kext v1.9.2 — Audio: Realtek ALC3235, layout-id 28
- IntelMausi.kext v1.0.7 — Ethernet: Ethernet Connection I219-LM
- AirportItlwm.kext v2.2.0 — WiFi: Wireless 8260 (partial support)

## SSDTs
- SSDT-PLUG.aml — Defines CPU power management (plugin-type=1)
- SSDT-EC-USBX.aml — Fake Embedded Controller + USB power properties
- SSDT-GPIO.aml — GPIO controller for PS/2 trackpad/VoodooI2C
- SSDT-PNLF.aml — Backlight control for laptop panels

## Files
- `config.plist` — OpenCore configuration (the main output)
- `build_plan.json` — full decision log (every value explained)
- `EFI/OC/` — directory structure (Phase 3 fills binaries)

## Next steps (Phase 3)
1. Download OpenCore + kexts into `EFI/OC/`
2. Compile/place SSDT .aml files in `EFI/OC/ACPI/`
3. Copy `EFI/` to the USB drive's EFI partition
4. Copy `config.plist` to `EFI/OC/config.plist`

## Warnings
- ⚠ wireless.wifi: Intel WiFi has only partial macOS support (no AirDrop, limited handoff).
- ⚠ smbios.serial: Generated serial is format-valid but may collide with a real Mac. Verify at https://checkcoverage.apple.com before iServices setup — it should return 'invalid' (meaning unused).