# hardware_profile.json — Schema Contract

This is the **shared contract** between `linux_scanner.py` and `windows_scanner.py`.
Both scanners MUST produce a structurally identical dict. Phase 2 (EFI generator)
reads this and nothing else — it has zero knowledge of the host OS.

## Principles

1. **Never crash.** If a field cannot be detected, set it to `null` and append
   an entry to `warnings[]` explaining what failed and why. Phase 2 treats a
   `null` on a required field as a hard stop with a user-facing message.
2. **IDs over names.** PCI IDs (`"8086:156f"`) are stable; marketing names are
   not. Where both exist, store both. Phase 2 keys off the ID.
3. **Root-free first.** Prefer `/sys` and `/proc` on Linux so the scanner runs
   unprivileged. `dmidecode` is a root-backed upgrade, not the primary path.
4. **Warnings are structured.** Each has `field`, `message`, `severity`
   (`info`/`warn`/`error`), and optional `needs_root` flag.

## Top-level shape

```jsonc
{
  "scan_metadata": { ... },   // how/when/where this was produced
  "cpu":            { ... },   // single object
  "gpu":            [ ... ],   // array — a machine can have iGPU + dGPU
  "audio":          { ... },
  "ethernet":       [ ... ],
  "usb_controllers":[ ... ],
  "wireless":       { ... },   // wifi + bluetooth grouped
  "motherboard":    { ... },
  "storage":        [ ... ],
  "memory":         { ... },
  "input_devices":  { ... },
  "nvram":          { ... },   // heuristic, refined in Phase 2
  "display_ports":  { ... },   // heuristic from GPU caps
  "warnings":       [ ... ]    // every detection gap, structured
}
```

## Field reference

### scan_metadata
| key | type | source | example |
|---|---|---|---|
| `host_os` | str | `platform.system()` | `"Linux"` |
| `host_release` | str | `platform.version()` | `"6.8.0-22-generic"` |
| `scanner_version` | str | `hackinstall.__version__` | `"1.0.0-phase1"` |
| `timestamp` | str | ISO 8601 UTC | `"2026-06-20T21:30:00Z"` |
| `used_root` | bool | did we invoke root-only tools? | `false` |
| `tool_versions` | obj | versions of lspci/dmidecode used | `{}` |

### cpu
| key | type | notes |
|---|---|---|
| `name` | str | raw model string |
| `vendor` | str | `"Intel"` / `"AMD"` |
| `generation` | int\|null | Intel = first digit of iN-XYZ; AMD via lookup |
| `codename` | str\|null | `"Skylake"`, `"Alder Lake"`, `"Zen 3"` |
| `microarch` | str\|null | `"skylake"`, `"zen3"` — for Phase 2 quirks |
| `cores` | int | physical cores |
| `threads` | int | logical processors |
| `has_igpu` | bool\|null | heuristic from model/codename |
| `amd_zen` | int\|null | AMD only: zen generation 1–5 |
| `macos_support` | str | `"full"`/`"partial"`/`"dropped"`/`"none"` |

### gpu[] (array)
| key | type | notes |
|---|---|---|
| `name` | str | from lspci/WMI |
| `vendor` | str | `"Intel"`/`"AMD"`/`"Nvidia"` |
| `pci_id` | str | `"8086:1916"` |
| `class` | str | PCI class name |
| `navi_gen` \| `gen` | str\|null | `"Navi 21"`, `"Skylake GT2"` |
| `macos_support` | str | support level |
| `needs_agdp_patch` | bool\|null | true for Navi/RX GPUs |

### audio
| key | type | notes |
|---|---|---|
| `codec` | str\|null | `"Realtek ALC3235"` |
| `codec_id` | str\|null | normalized `"10ec:0293"` |
| `layout_id` | int\|null | AppleALC layout-id |
| `kext` | str | always `"AppleALC.kext"` |

### ethernet[] / usb_controllers[] / storage[]
Each entry: `{ name/chip, pci_id, vendor, kext, needs_patch, ... }`
plus component-specific keys (e.g. `port_count` for USB, `type` for storage).

### wireless
| key | type | notes |
|---|---|---|
| `wifi_chip` | str\|null | |
| `wifi_pci_id` | str\|null | |
| `wifi_support` | str | `"full"`/`"partial"`/`"none"`/`"native"` |
| `bluetooth_chip` | str\|null | |
| `bt_pci_id` / `bt_usb_id` | str\|null | |
| `bt_kext` | str\|null | |
| `airdrop_support` | bool | needs Broadcom card |

### motherboard
| key | type | notes |
|---|---|---|
| `vendor` / `model` / `chipset` | str | chipset parsed from model/board family |
| `has_ec` | bool | true on desktops/laptops (embedded controller) |
| `bios_version` / `bios_vendor` | str | |
| `chassis_type` | str | `"laptop"`/`"desktop"`/`"server"` — drives SMBIOS target |

### memory
| key | type | notes |
|---|---|---|
| `total_gb` | int | from `/proc/meminfo` or WMI |
| `type` | str\|null | `"DDR4"` — **needs root on Linux** |
| `speed_mhz` | int\|null | **needs root on Linux** |
| `slots_used` | int\|null | **needs root on Linux** |

### warnings[]
```jsonc
{ "field": "memory.type", "severity": "warn",
  "message": "Could not read memory type (dmidecode needs root). Re-run as root for DDR version.",
  "needs_root": true }
```
