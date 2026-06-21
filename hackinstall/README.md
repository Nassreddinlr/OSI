# HackInstall — Phase 1: Deep Hardware Scanner

> Part of the [HackInstall Blueprint v2.0](../plan(1).html) — one-click macOS-on-PC installer.

## What this does

Scans every hardware component on a Linux (or Windows, pending) machine and produces a structured `hardware_profile.json` that Phase 2 (EFI Config Generator) consumes. Zero manual input needed — the tool runs unprivileged and detects:

| Component | Detection method | Enrichment |
|---|---|---|
| CPU (model, cores, gen, codename) | `lscpu` + `/proc/cpuinfo` | CPU codename table → `macos_support`, `microarch` |
| GPU (name, PCI ID, support level) | `lspci -vmm -nn` (class 0300) | PCI DB → kext, `needs_agdp_patch` |
| Audio codec + AppleALC layout-id | `/proc/asound/card*/codec#0` | Audio layout table → `layout_id` |
| Ethernet (chip, PCI ID, kext) | `lspci -vmm -nn` (class 0200) | PCI DB → `IntelMausi.kext` / `LucyRTL8125.kext` |
| WiFi + Bluetooth | `lspci` (class 0280) + `lsusb` | PCI DB → `AirportItlwm.kext`, AirDrop support |
| USB controllers (xHCI) | `lspci -vmm -nn` (class 0c03) | Flags `needs_usb_map` |
| Motherboard, BIOS, chassis | `/sys/class/dmi/id/*` | Heuristic → `chassis_type`, chipset |
| Storage (NVMe/SATA/HDD) | `lsblk -J` | Transport detection |
| Memory (total, type, speed) | `/proc/meminfo` + `dmidecode` (root) | Type/speed need root |
| Input (PS/2 detection) | PCI class 0901 | `VoodooPS2.kext` flag |
| NVRAM heuristic | Chipset generation | Native vs emulated NVRAM |
| Display ports | GPU presence | iGPU headless mode |

## Quick start

```bash
cd hackinstall/

# Scan and print a human-readable summary:
python3 -m hackinstall

# Scan + write the full JSON profile:
python3 -m hackinstall --output hardware_profile.json

# Verbose (show warnings + tracebacks):
python3 -m hackinstall --verbose

# Print the schema documentation:
python3 -m hackinstall schema
```

### Dependencies

**Zero external dependencies.** Pure Python 3.11+ using only stdlib (`subprocess`, `json`, `pathlib`, `re`, `glob`, `platform`).

Required system tools (pre-installed on Ubuntu/Kubuntu):
- `lspci` (from `pciutils`)
- `lscpu` (from `util-linux`)
- `lsblk` (from `util-linux`)
- `lsusb` (from `usbutils`)
- `dmidecode` (optional — only needed for memory type/speed/slots)

### Root not required

The scanner runs fully unprivileged. Without root:
- CPU, GPU, audio, ethernet, WiFi, storage, USB, motherboard — **all detected**
- Memory type/speed/slots — **null** with a `needs_root` warning
- NVRAM detection — **heuristic only** (no dmidecode for precise chipset)

Re-run with `sudo` for the 1-2 additional fields.

## Project structure

```
hackinstall/
├── __init__.py          # package metadata
├── __main__.py          # python -m hackinstall entry
├── main.py              # CLI: scan, schema subcommands
├── SCHEMA.md            # hardware_profile.json contract
├── README.md            # this file
│
├── scanners/
│   ├── __init__.py      # get_scanner() platform router
│   ├── base_scanner.py  # abstract base + enrichment logic
│   ├── linux_scanner.py # lspci + /sys + /proc implementation
│   ├── windows_scanner.py # WMI implementation (pending)
│   └── _cmd.py          # subprocess helper
│
└── data/
    ├── __init__.py      # lookup helpers: pci_lookup(), cpu_lookup(), etc.
    ├── pci_ids.json     # hackintosh-relevant PCI devices (GPU, NIC, WiFi, USB)
    ├── cpu_codenames.json  # CPU model → codename/microarch/macOS support
    └── audio_layouts.json  # HDA codec → AppleALC layout-id
```

## Architecture

```
CLI (main.py)
  └→ get_scanner()          # platform router
       ├→ LinuxScanner       # lspci + /sys + /proc (root-free)
       └→ WindowsScanner     # WMI (pending)
            │
            └→ .scan()       # runs all _scan_* sections via _safe()
                 │
                 ├→ base_scanner._enrich_cpu()       # cpu_lookup()
                 ├→ base_scanner._enrich_audio()      # audio_layout()
                 ├→ base_scanner._enrich_pci_device() # pci_lookup()
                 └→ data tables (JSON, no rebuild needed)
                      │
                      └→ hardware_profile.json    # THE CONTRACT
```

**Key design decision:** every `_scan_*` method is wrapped in `_safe()` which catches any exception, substitutes an empty result, and records a structured warning. The profile is **always complete-shaped** — unknown fields are `null`, not missing. Phase 2 treats `null` on required fields as a hard stop with a user-facing message.

## Tested on

- **Dell Latitude E5470** — Intel i5-6300U (Skylake), HD Graphics 520, Realtek ALC3235, Intel I219-LM, Intel Wireless 8260, Sunrise Point-LP chipset, SanDisk X400 SATA SSD

## What's next (Phase 2)

Phase 2 reads `hardware_profile.json` and generates:
- `config.plist` with the right OpenCore quirks, kexts, SSDTs, boot args
- SMBIOS model selection + serial generation
- USB port mapping
- Download OpenCore + kexts from GitHub Releases

See the [full blueprint](../plan(1).html) for the 4-phase roadmap.
