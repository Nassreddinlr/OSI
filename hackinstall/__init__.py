"""HackInstall — one-click Hackintosh EFI generator.

Phase 1 (this package): deep hardware scanner.
  - LinuxScanner  → lspci + dmidecode + /proc + /sys  (root-free preferred)
  - WindowsScanner → WMI  (Phase 1 stub, full impl target)

Both emit the same ``hardware_profile.json`` — see SCHEMA.md for the contract.
"""

__version__ = "1.0.0-phase1"
__author__ = "HackInstall"
