"""Linux hardware scanner.

Strategy: prefer root-free sources (/sys, /proc, lspci, lscpu, lsblk) so the
tool runs unprivileged — critical because the plan's risk register flags
'Linux dd writes to wrong disk' and we want minimal privilege. dmidecode is
used only as a *root-backed upgrade* for memory type/speed; without root we
record a warning and leave those fields null (the profile stays valid).

Tested on: Dell Latitude E5470 (Intel Skylake i5-6300U, HD Graphics 520,
Sunrise Point-LP, Realtek ALC3235, Intel I219-LM, Intel Wireless 8260).
"""
from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

from ..data import normalize_pci_id
from ._cmd import have, run
from .base_scanner import BaseScanner

# PCI class codes → categories. See https://pci-ids.ucw.cz/read/PD
_PCI_CLASSES = {
    "0300": "gpu",          # VGA compatible controller
    "0302": "gpu",          # 3D controller (dGPU in laptops)
    "0280": "wifi",         # Network controller (wireless)
    "0200": "ethernet",     # Ethernet controller
    "0c03": "usb_controller",  # USB controller (any ProgIf)
    "0108": "nvme",         # Non-Volatile memory controller
    "0106": "sata",         # SATA controller
    "0101": "sata",         # IDE-compatible SATA
    "0403": "audio",        # Audio device (HDA)
    "0901": "input",        # Input device (PS/2 etc.)
}


class LinuxScanner(BaseScanner):
    """Concrete scanner for Linux (Ubuntu/Kubuntu/Debian family)."""

    # ─── Setup: capture tool versions once ───────────────────────────────

    def __init__(self) -> None:
        super().__init__()
        # Probe versions. lscpu has no --version flag; lsusb's is noisy.
        versionable = {"lspci", "lsblk", "dmidecode"}
        for tool in ("lspci", "lscpu", "lsblk", "dmidecode", "lsusb"):
            if not have(tool):
                continue
            if tool in versionable:
                out, _ = run([tool, "--version"])
                first = (out.splitlines()[0] if out else "").strip()
                if first:
                    self.tool_versions[tool] = first

    # ─── PCI: parsed once, categorized by class ──────────────────────────

    def _parse_lspci(self) -> list[dict]:
        """Parse ``lspci -vmm -nn`` into a list of device dicts.

        -vmm gives colon-separated key:value blocks, -nn appends [vendor:device]
        to both Class and Device lines. We normalize the bracket IDs.
        """
        out, _ = run(["lspci", "-vmm", "-nn"])
        devices: list[dict] = []
        current: dict = {}
        for line in out.splitlines():
            if not line.strip():
                if current:
                    devices.append(self._normalize_pci_entry(current))
                    current = {}
                continue
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            current[key.strip()] = val.strip()
        if current:
            devices.append(self._normalize_pci_entry(current))
        return devices

    @staticmethod
    def _extract_bracket_id(field: str) -> str | None:
        """Pull the trailing ``[hhhh]`` 4-hex token from a -nn field.

        In ``lspci -vmm -nn`` output the Vendor/Device lines each carry ONE
        bare bracketed id (``Vendor: Intel [8086]``, ``Device: ... [1916]``),
        NOT the ``[vendor:device]`` colon form that the default ``lspci -nn``
        uses. We combine vendor+device ourselves in ``_normalize_pci_entry``.
        """
        m = re.search(r"\[([0-9a-f]{4})\]\s*$", field)
        return m.group(1) if m else None

    def _normalize_pci_entry(self, raw: dict) -> dict:
        """Turn one lspci -vmm block into our canonical PCI device shape."""
        class_field = raw.get("Class", "")
        # Class line: 'VGA compatible controller [0300]' — bare 4-hex code.
        class_id = self._extract_bracket_id(class_field) or ""

        # Vendor/Device lines each carry their own bare id; combine to vendor:device.
        vendor_field = raw.get("Vendor", "")
        device_field = raw.get("Device", "")
        vendor_id = self._extract_bracket_id(vendor_field)
        device_id = self._extract_bracket_id(device_field)
        pci_id = normalize_pci_id(vendor_id, device_id) if vendor_id and device_id else None

        # Names are the text before the bracket. Device text may contain a
        # bracketed sub-name too ('Skylake-U GT2 [HD Graphics 520] [1916]')
        # so we strip only the trailing id bracket, preserving the sub-name.
        device_name = re.sub(r"\s*\[[0-9a-f]{4}\]\s*$", "", device_field).strip()
        vendor_name = re.sub(r"\s*\[[0-9a-f]{4}\]\s*$", "", vendor_field).strip()

        return {
            "slot": raw.get("Slot", ""),
            "class_name": re.sub(r"\s*\[[0-9a-f]{4}\]\s*$", "", class_field).strip(),
            "class_id": class_id,
            "category": _PCI_CLASSES.get(class_id, "other"),
            "name": device_name,
            "vendor_name": vendor_name,
            "pci_id": pci_id,
            "revision": raw.get("Rev", ""),
            "subvendor": raw.get("SVendor", ""),
        }

    def _pci_devices(self) -> list[dict]:
        """Cached access to the parsed lspci tree."""
        if not hasattr(self, "_pci_cache"):
            self._pci_cache = self._parse_lspci()
            if not self._pci_cache:
                self.warn(
                    field="pci",
                    message="lspci returned no devices. Is pciutils installed?",
                    severity="error",
                )
        return self._pci_cache

    def _by_category(self, category: str) -> list[dict]:
        return [d for d in self._pci_devices() if d["category"] == category]

    # ─── CPU ─────────────────────────────────────────────────────────────

    def _scan_cpu(self) -> dict:
        out, _ = run(["lscpu"])
        fields = self._parse_colon_blocks(out)
        name = fields.get("Model name", "").strip()
        vendor_raw = fields.get("Vendor ID", "").strip()
        vendor = "Intel" if "GenuineIntel" in vendor_raw else (
            "AMD" if "AuthenticAMD" in vendor_raw else vendor_raw or None
        )

        def _int(key: str) -> int | None:
            try:
                return int(fields.get(key, "0").strip())
            except ValueError:
                return None

        cores = _int("Core(s) per socket")
        sockets = _int("Socket(s)") or 1
        threads_per_core = _int("Thread(s) per core") or 1
        physical_cores = (cores or 0) * sockets
        logical_threads = physical_cores * threads_per_core

        # Virtualization extension (vmx/svm) — relevant to macOS guests later.
        virt = fields.get("Virtualization", "").strip() or None

        return {
            "name": name,
            "vendor": vendor,
            "cores": physical_cores or None,
            "threads": logical_threads or None,
            "sockets": sockets,
            "base_clock_ghz": self._float(fields.get("CPU max MHz")) ,
            "min_clock_ghz": self._float(fields.get("CPU min MHz")),
            "virtualization": virt,
            "flags": self._cpu_flags(),
        }

    @staticmethod
    def _cpu_flags() -> list[str]:
        """Pull notable CPU flags (vmx/svm, aes, avx2, etc.)."""
        try:
            text = Path("/proc/cpuinfo").read_text()
            m = re.search(r"^flags\s*:\s*(.+)$", text, re.MULTILINE)
            if m:
                interesting = {"vmx", "svm", "aes", "avx", "avx2", "avx512f", "smep", "smap"}
                return sorted(set(m.group(1).split()) & interesting)
        except OSError:
            pass
        return []

    @staticmethod
    def _float(mhz_str: str | None) -> float | None:
        if not mhz_str:
            return None
        try:
            return round(float(mhz_str.strip()) / 1000.0, 2)
        except ValueError:
            return None

    # ─── GPU ─────────────────────────────────────────────────────────────

    def _scan_gpu(self) -> list:
        gpus = []
        for dev in self._by_category("gpu"):
            gpus.append({
                "name": dev["name"],
                "vendor": dev["vendor_name"],
                "pci_id": dev["pci_id"],
                "class": dev["class_name"],
                "slot": dev["slot"],
            })
        if not gpus:
            self.warn(field="gpu", message="No GPU detected via PCI class 0300/0302.")
        return gpus

    # ─── Audio ───────────────────────────────────────────────────────────

    def _scan_audio(self) -> dict:
        codec, codec_id = self._read_audio_codec()
        if not codec:
            self.warn(
                field="audio.codec",
                message=(
                    "Could not read HDA codec from /proc/asound. "
                    "AppleALC layout-id will need to be set manually."
                ),
            )
        return {
            "codec": codec,
            "codec_id": codec_id,
            "source": "/proc/asound/card*/codec#0",
        }

    @staticmethod
    def _read_audio_codec() -> tuple[str | None, str | None]:
        """Parse the on-board HDA codec (Realtek/Conexant/etc.)."""
        for codec_file in sorted(glob.glob("/proc/asound/card*/codec#*")):
            try:
                text = Path(codec_file).read_text(errors="replace")
            except OSError:
                continue
            codec_match = re.search(r"^Codec:\s*(.+)$", text, re.MULTILINE)
            vid_match = re.search(r"^Vendor Id:\s*0x([0-9a-f]{8})", text, re.MULTILINE)
            if codec_match and vid_match:
                codec = codec_match.group(1).strip()
                raw = vid_match.group(1)
                # 0x10ec0293 → vendor 10ec, device 0293
                codec_id = normalize_pci_id(raw[:4], raw[4:])
                return codec, codec_id
        return None, None

    # ─── Ethernet ────────────────────────────────────────────────────────

    def _scan_ethernet(self) -> list:
        eths = []
        for dev in self._by_category("ethernet"):
            eths.append({
                "name": dev["name"],
                "vendor": dev["vendor_name"],
                "pci_id": dev["pci_id"],
                "slot": dev["slot"],
            })
        return eths

    # ─── USB controllers ─────────────────────────────────────────────────

    def _scan_usb_controllers(self) -> list:
        ctrls = []
        for dev in self._by_category("usb_controller"):
            ctrls.append({
                "name": dev["name"],
                "vendor": dev["vendor_name"],
                "pci_id": dev["pci_id"],
                "slot": dev["slot"],
                "needs_usb_map": True,  # macOS 15-port limit — always map
            })
        return ctrls

    # ─── Wireless (WiFi + Bluetooth) ─────────────────────────────────────

    def _scan_wireless(self) -> dict:
        wifi_devs = self._by_category("wifi")
        wifi = None
        if wifi_devs:
            w = wifi_devs[0]
            wifi = {
                "chip": w["name"],
                "vendor": w["vendor_name"],
                "pci_id": w["pci_id"],
            }
        else:
            self.warn(field="wireless.wifi", message="No wireless PCI device found.")

        bt = self._detect_bluetooth()

        # Look up macOS support + kext for the wifi chip from the curated DB.
        wifi_support = None
        wifi_kext = None
        if wifi and wifi["pci_id"]:
            from ..data import pci_lookup
            entry = pci_lookup(wifi["pci_id"])
            if entry:
                wifi_support = entry.get("macos_support")
                wifi_kext = entry.get("kext")

        # Broadcom cards (natively supported) enable AirDrop; Intel/Realtek don't.
        is_broadcom = bool(wifi and "broadcom" in (wifi.get("vendor") or "").lower())

        return {
            "wifi_chip": wifi["chip"] if wifi else None,
            "wifi_pci_id": wifi["pci_id"] if wifi else None,
            "wifi_vendor": wifi["vendor"] if wifi else None,
            "wifi_support": wifi_support,
            "wifi_kext": wifi_kext,
            "bluetooth_chip": bt.get("name"),
            "bt_usb_id": bt.get("usb_id"),
            "bt_kext": "IntelBluetoothFirmware.kext" if bt else None,
            "airdrop_support": is_broadcom,
        }

    def _detect_bluetooth(self) -> dict:
        """Bluetooth is usually USB-internal, not PCI. Check lsusb."""
        out, _ = run(["lsusb"])
        for line in out.splitlines():
            low = line.lower()
            if "bluetooth" in low or "bcm2045" in low or "0a12:" in low or "8087:0" in low:
                m = re.search(r"ID\s+([0-9a-f]{4}):([0-9a-f]{4})", line)
                usb_id = normalize_pci_id(m.group(1), m.group(2)) if m else None
                name = re.sub(r"^Bus\s+\d+\s+Device\s+\d+:\s*ID\s+[0-9a-f:]+\s*", "", line).strip()
                return {"name": name, "usb_id": usb_id}
        return {}

    # ─── Motherboard / BIOS / Chassis ────────────────────────────────────

    def _scan_motherboard(self) -> dict:
        dmi = self._read_dmi_sys()
        chassis_type = self._chassis_type(dmi.get("chassis_type"))
        model = dmi.get("board_name") or dmi.get("product_name") or ""
        chipset = self._guess_chipset()
        return {
            "vendor": dmi.get("board_vendor") or dmi.get("sys_vendor"),
            "model": model,
            "product_name": dmi.get("product_name"),
            "chipset": chipset,
            "bios_version": dmi.get("bios_version"),
            "bios_vendor": dmi.get("bios_vendor"),
            "bios_date": dmi.get("bios_date"),
            "chassis_type": chassis_type,
            "has_ec": chassis_type in ("laptop", "desktop"),
        }

    @staticmethod
    def _read_dmi_sys() -> dict[str, str]:
        """Root-free DMI reads from /sys/class/dmi/id (works on most distros)."""
        base = Path("/sys/class/dmi/id")
        out: dict[str, str] = {}
        if not base.exists():
            return out
        for key in (
            "board_vendor", "board_name", "board_version",
            "bios_vendor", "bios_version", "bios_date",
            "product_name", "product_version",
            "sys_vendor", "chassis_type",
        ):
            p = base / key
            try:
                out[key] = p.read_text().strip()
            except OSError:
                out[key] = ""
        return out

    @staticmethod
    def _chassis_type(raw: str | None) -> str:
        """DMI chassis_type is numeric (3=desktop, 9/10=laptop...). Map to a label."""
        if not raw:
            return "unknown"
        try:
            t = int(raw)
        except ValueError:
            return "unknown"
        laptops = {8, 9, 10, 11, 14, 30, 31, 32}
        desktops = {3, 4, 5, 6, 7, 15, 16, 24}
        servers = {17, 18, 22, 23, 25, 27, 28, 29}
        if t in laptops:
            return "laptop"
        if t in desktops:
            return "desktop"
        if t in servers:
            return "server"
        return "unknown"

    def _guess_chipset(self) -> str | None:
        """Best-effort chipset from the ISA/LPC bridge or host bridge name."""
        for dev in self._pci_devices():
            if dev["class_id"] in ("0601", "0600"):  # ISA bridge / Host bridge
                name = dev["name"]
                m = re.search(r"(Z\d{3}|B\d{3}|X\d{3}|H\d{3}|Q\d{3}|Sunrise|Cannon|Comet|Alder|Raptor)", name, re.IGNORECASE)
                if m:
                    return m.group(1)
        return None

    # ─── Storage ─────────────────────────────────────────────────────────

    def _scan_storage(self) -> list:
        disks: list[dict] = []
        out, _ = run(["lsblk", "-J", "-d", "-o", "NAME,SIZE,TYPE,MODEL,VENDOR,TRAN,ROTA"])
        if not out:
            self.warn(field="storage", message="lsblk returned nothing; storage list may be incomplete.")
            return disks
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            self.warn(field="storage", message="lsblk JSON parse failed.")
            return disks

        for blk in data.get("blockdevices", []):
            if blk.get("type") != "disk":
                continue
            name = blk.get("model") or blk.get("name", "")
            tran = blk.get("tran") or ""
            disk_type = "NVMe" if tran == "nvme" else ("SATA" if tran in ("sata", "ata") else tran.upper() or "UNKNOWN")
            disks.append({
                "name": name.strip(),
                "device": f"/dev/{blk.get('name','')}",
                "size_gb": self._bytes_to_gb(blk.get("size")),
                "type": disk_type,
                "rotational": blk.get("rota") == "1",
                "transport": tran or None,
                "vendor": blk.get("vendor"),
            })
        return disks

    @staticmethod
    def _bytes_to_gb(size_str: str | None) -> int | None:
        """lsblk size is human string like '238.5G' — coerce to integer GB."""
        if not size_str:
            return None
        m = re.match(r"([\d.]+)([KMGT]?B?)", size_str, re.IGNORECASE)
        if not m:
            return None
        val = float(m.group(1))
        unit = m.group(2).upper()
        mult = {"": 1, "B": 1, "K": 2**10, "KB": 2**10, "M": 2**20, "MB": 2**20,
                "G": 2**30, "GB": 2**30, "T": 2**40, "TB": 2**40}.get(unit, 1)
        return int(val * mult / 2**30) if mult >= 2**30 else int(val)

    # ─── Memory ──────────────────────────────────────────────────────────

    def _scan_memory(self) -> dict:
        total_gb = self._meminfo_total_gb()
        # Memory type/speed/slots need dmidecode (root). Try root-backed upgrade.
        details = self._dmidecode_memory()
        if not details:
            self.warn(
                field="memory",
                message=(
                    "Memory type/speed/slots need dmidecode (requires root). "
                    "Re-run as root or with passwordless sudo for full details."
                ),
                needs_root=True,
            )
        return {
            "total_gb": total_gb,
            "type": details.get("type"),
            "speed_mhz": details.get("speed"),
            "slots_used": details.get("slots"),
        }

    @staticmethod
    def _meminfo_total_gb() -> int | None:
        try:
            text = Path("/proc/meminfo").read_text()
            m = re.search(r"^MemTotal:\s+(\d+)", text, re.MULTILINE)
            if m:
                return int(int(m.group(1)) / 1024 / 1024)
        except OSError:
            pass
        return None

    def _dmidecode_memory(self) -> dict:
        """Root-backed upgrade: returns {} if no passwordless sudo."""
        out, rc = run(["dmidecode", "-t", "memory"], as_root=True)
        if rc != 0 or not out:
            return {}
        self.used_root = True
        types: set[str] = set()
        speeds: list[int] = []
        for line in out.splitlines():
            if line.strip().startswith("Type:") and "Unknown" not in line:
                types.add(line.split("Type:")[1].strip())
            if line.strip().startswith("Speed:") and "Unknown" not in line:
                m = re.search(r"(\d+)\s+MT/s", line)
                if m:
                    speeds.append(int(m.group(1)))
        return {
            "type": "/".join(sorted(types)) if types else None,
            "speed": min(speeds) if speeds else None,
            "slots": len(speeds) or None,
        }

    # ─── Input devices (PS/2 detection) ──────────────────────────────────

    def _scan_input_devices(self) -> dict:
        ps2 = self._has_ps2_controller()
        return {
            "keyboard_bus": "PS/2" if ps2 else "USB",
            "mouse_bus": "PS/2" if ps2 else "USB",
            "ps2_present": ps2,
            "note": "PS/2 keyboard/mouse require VoodooPS2.kext" if ps2 else None,
        }

    def _has_ps2_controller(self) -> bool:
        """True only if a real PS/2 controller (PCI class 0901) is present.

        Don't trust /sys/bus/serio alone — laptops expose serio devices for
        their keyboard/touchpad controllers even with no PS/2 ports. PCI class
        0901 is the reliable signal that VoodooPS2 is actually needed.
        """
        return any(d["category"] == "input" for d in self._pci_devices())

    # ─── NVRAM heuristic (refined in Phase 2) ────────────────────────────

    def _scan_nvram(self) -> dict:
        cpu = {}  # populated by _enrich_cpu later; use a cheap heuristic here
        # Modern Intel (Z390+, 300-series+) and all AMD Ryzen have native NVRAM.
        host_bridge = next(
            (d for d in self._pci_devices() if d["class_id"] == "0600"), None
        )
        chipset = self._guess_chipset() or ""
        modern = any(chip in chipset for chip in ("Z390", "Z490", "Z590", "Z690", "Z790",
                                                   "B6", "B7", "H6", "H7", "X5", "B5", "A5", "A6"))
        return {
            "native_nvram": modern or None,
            "use_emulated": not modern if chipset else None,
            "note": "Phase 2 refines this from CPU/chipset generation" if not modern else None,
        }

    # ─── Display ports (heuristic from GPU presence) ────────────────────

    def _scan_display_ports(self) -> dict:
        gpus = self._by_category("gpu")
        has_dgpu = len(gpus) > 1
        has_igpu = any("Intel" in g["vendor_name"] for g in gpus)
        return {
            "hdmi": None,          # can't enumerate from userspace reliably
            "displayport": None,
            "igpu_headless": has_dgpu and has_igpu,
            "imessage_ready": False,  # needs proper MLB/ROM — Phase 2
        }

    # ─── Shared parser ───────────────────────────────────────────────────

    @staticmethod
    def _parse_colon_blocks(text: str) -> dict[str, str]:
        """Parse 'Key: Value' lines (lscpu, lspci blocks) into a flat dict."""
        out: dict[str, str] = {}
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            out[key.strip()] = val.strip()
        return out
