"""HackInstall core — Phase 2 EFI config generation.

This package is OS-agnostic: it reads a ``hardware_profile.json`` (produced
by Phase 1) and outputs an OpenCore ``EFI/`` folder. Zero imports from
``scanners/`` — the profile dict is the only bridge between phases.

Modules:
  - decisions      : profile + compat_matrix → BuildPlan (the decision layer)
  - smbios_gen     : GenSMBIOS port — valid MLB/serial/UUID/ROM generation
  - kext_selector  : dependency-ordered kext list (Lilu always first)
  - ssdt_builder   : SSDT-PLUG / EC-USBX / etc. selection
  - config_generator : BuildPlan → config.plist (via stdlib plistlib)
  - efi_builder    : top-level orchestrator — writes the whole EFI/ tree
"""
