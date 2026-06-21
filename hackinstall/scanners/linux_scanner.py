"""Linux hardware scanner — deep & thorough.

Strategy: probe everything available. Uses /sys, /proc, lspci, lscpu,
lsblk, lsusb, dmidecode, and sysfs DRM/ACPI nodes. When root is
available (via sudo), dmidecode provides motherboard serial, UUID,
detailed memory DIMMs, ACPI table listing, and BIOS features.
Without root, the scanner still captures the full PCI/USB/sysfs tree —
fields that require root get a structured warning.
"""
from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

from ..data import normalize_pci_id
from ._cmd import can_sudo, have, is_root, run
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

        # Shorten verbose vendor names at the source so all consumers benefit.
        vendor_name = self._short_vendor(vendor_name)

        return {
            "slot": raw.get("Slot", ""),
            "class_name": re.sub(r"\s*\[[0-9a-f]{4}]\s*$", "", class_field).strip(),
            "class_id": class_id,
            "category": _PCI_CLASSES.get(class_id, "other"),
            "name": device_name,
            "vendor_name": vendor_name,
            "pci_id": pci_id,
            "revision": raw.get("Rev", ""),
            "subvendor": raw.get("SVendor", ""),
        }

    @staticmethod
    def _short_vendor(name: str) -> str:
        """Map verbose lspci vendor strings to canonical short forms."""
        short = {
            "Intel Corporation": "Intel",
            "Advanced Micro Devices, Inc.": "AMD",
            "NVIDIA Corporation": "Nvidia",
            "Realtek Semiconductor Co., Ltd.": "Realtek",
            "Broadcom Inc. and subsidiaries": "Broadcom",
            "Qualcomm Atheros": "Qualcomm Atheros",
            "Qualcomm Technologies Inc.": "Qualcomm",
        }
        return short.get(name, name)

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

        # Stepping + microcode from /proc/cpuinfo (root-free, per-core).
        stepping, microcode, family = self._cpu_stepping_microcode()

        # Full CPU flags for hackintosh compatibility checks.
        all_flags = self._cpu_all_flags()
        notable_flags = self._cpu_flags()

        # Model ID from /proc/cpuinfo.
        model_id = self._cpuinfo_field("model")

        # Per-core frequency range from sysfs (detects P-core vs E-core on
        # Intel 12th gen+).
        core_freq_map = self._per_core_frequencies()
        has_hybrid = len(set(
            (v.get("max_mhz", 0) for v in core_freq_map.values())
        )) > 1 if core_freq_map else False

        # Governor and energy preference.
        governor = self._cpu_governor()

        # CPUID from /proc/cpuinfo.
        cpuid = self._cpuinfo_field("cpuid level")

        return {
            "name": name,
            "vendor": vendor,
            "cores": physical_cores or None,
            "threads": logical_threads or None,
            "sockets": sockets,
            "base_clock_ghz": self._float(fields.get("CPU max MHz")),
            "min_clock_ghz": self._float(fields.get("CPU min MHz")),
            "current_mhz": self._float(fields.get("CPU MHz")),
            "virtualization": virt,
            "flags": notable_flags,
            "all_flags": all_flags,
            "stepping": stepping,
            "cpu_family": family,
            "model_id": model_id,
            "cpuid_level": cpuid,
            "microcode": microcode,
            "architecture": fields.get("Architecture", "").strip() or None,
            "byte_order": fields.get("Byte Order", "").strip() or None,
            "op_modes": fields.get("CPU op-mode(s)", "").strip() or None,
            "bogomips": self._float_raw(fields.get("BogoMIPS")),
            "l1d_cache": fields.get("L1d cache", "").strip() or None,
            "l1i_cache": fields.get("L1i cache", "").strip() or None,
            "l2_cache": fields.get("L2 cache", "").strip() or None,
            "l3_cache": fields.get("L3 cache", "").strip() or None,
            "numa_nodes": _int("NUMA node(s)"),
            "governor": governor,
            "hybrid_cores": has_hybrid,
            "core_frequencies": core_freq_map or None,
        }

    @staticmethod
    def _cpu_stepping_microcode() -> tuple[int | None, str | None, str | None]:
        """Pull stepping, family, and microcode revision from /proc/cpuinfo."""
        try:
            text = Path("/proc/cpuinfo").read_text()
        except OSError:
            return None, None, None
        stepping = family = microcode = None
        for line in text.splitlines():
            if stepping is None and line.lower().startswith("stepping"):
                m = re.search(r":\s*(\d+)", line)
                stepping = int(m.group(1)) if m else None
            elif family is None and line.lower().startswith("cpu family"):
                m = re.search(r":\s*(\d+)", line)
                family = m.group(1) if m else None
            elif microcode is None and line.lower().startswith("microcode"):
                m = re.search(r":\s*(0x[0-9a-f]+)", line)
                microcode = m.group(1) if m else None
            if all(v is not None for v in (stepping, family, microcode)):
                break
        return stepping, microcode, family

    @staticmethod
    def _cpu_flags() -> list[str]:
        """Pull notable CPU flags relevant to Hackintosh compatibility."""
        try:
            text = Path("/proc/cpuinfo").read_text()
            m = re.search(r"^flags\s*:\s*(.+)$", text, re.MULTILINE)
            if m:
                # Extended set: everything macOS cares about.
                interesting = {
                    "vmx", "svm",           # Virtualization
                    "aes", "aes-ni",        # AES acceleration
                    "avx", "avx2", "avx512f",  # Vector extensions
                    "sse4_1", "sse4_2", "ssse3",  # SSE (macOS minimum)
                    "smep", "smap",          # Security
                    "rdrand", "rdseed",      # Random
                    "fma", "f16c",           # Floating point
                    "popcnt",               # Population count
                    "xsave", "xsaveopt",    # Extended state save
                    "pcid",                 # Process-context IDs
                    "msr",                  # Model-specific registers
                    "tsc", "tsc_deadline_timer", "constant_tsc",  # Timestamp
                    "nx",                   # No-execute
                    "ht",                   # Hyper-threading
                    "est", "tm2",           # Thermal/SpeedStep
                }
                return sorted(set(m.group(1).split()) & interesting)
        except OSError:
            pass
        return []

    @staticmethod
    def _cpu_all_flags() -> list[str]:
        """Return ALL CPU flags from /proc/cpuinfo."""
        try:
            text = Path("/proc/cpuinfo").read_text()
            m = re.search(r"^flags\s*:\s*(.+)$", text, re.MULTILINE)
            if m:
                return sorted(set(m.group(1).split()))
        except OSError:
            pass
        return []

    @staticmethod
    def _cpuinfo_field(field_name: str) -> str | None:
        """Read a single field from /proc/cpuinfo (first core only)."""
        try:
            text = Path("/proc/cpuinfo").read_text()
            m = re.search(rf"^{re.escape(field_name)}\s*:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
            return m.group(1).strip() if m else None
        except OSError:
            return None

    @staticmethod
    def _per_core_frequencies() -> dict[str, dict]:
        """Read per-core min/max frequencies from sysfs cpufreq.

        Detects hybrid (P-core/E-core) architectures like Intel Alder Lake+
        where different cores have different max frequencies.
        """
        result: dict[str, dict] = {}
        cpufreq = Path("/sys/devices/system/cpu")
        if not cpufreq.exists():
            return result
        for cpu_dir in sorted(cpufreq.glob("cpu[0-9]*")):
            freq_dir = cpu_dir / "cpufreq"
            if not freq_dir.exists():
                continue
            try:
                max_freq = int((freq_dir / "cpuinfo_max_freq").read_text().strip()) // 1000
                min_freq = int((freq_dir / "cpuinfo_min_freq").read_text().strip()) // 1000
                result[cpu_dir.name] = {"max_mhz": max_freq, "min_mhz": min_freq}
            except (OSError, ValueError):
                continue
        return result

    @staticmethod
    def _cpu_governor() -> str | None:
        """Read the current CPU frequency governor."""
        try:
            return (Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
                    .read_text().strip())
        except OSError:
            return None

    @staticmethod
    def _float(mhz_str: str | None) -> float | None:
        if not mhz_str:
            return None
        try:
            return round(float(mhz_str.strip()) / 1000.0, 2)
        except ValueError:
            return None

    @staticmethod
    def _float_raw(val_str: str | None) -> float | None:
        """Parse a raw float string (not MHz → GHz conversion)."""
        if not val_str:
            return None
        try:
            return round(float(val_str.strip()), 2)
        except ValueError:
            return None

    # ─── GPU ─────────────────────────────────────────────────────────────

    def _scan_gpu(self) -> list:
        gpus = []
        all_gpus = self._by_category("gpu")
        has_multiple = len(all_gpus) > 1
        for dev in all_gpus:
            vendor = dev["vendor_name"]
            # device-id is the second half of pci_id (e.g. 8086:1916 → 1916).
            device_id = None
            if dev.get("pci_id") and ":" in dev["pci_id"]:
                device_id = "0x" + dev["pci_id"].split(":")[1].lower()
            # iGPU vs dGPU: Intel GPUs are almost always integrated. AMD/Nvidia
            # on the same system as an Intel GPU = discrete.
            is_igpu = vendor == "Intel" and not (
                has_multiple and dev["class_id"] == "0302"
            )

            # Deep GPU probing from sysfs DRM + kernel driver.
            gpu_drm = self._gpu_drm_info(dev)
            gpu_driver = self._gpu_kernel_driver(dev)

            gpus.append({
                "name": dev["name"],
                "vendor": vendor,
                "pci_id": dev["pci_id"],
                "device_id": device_id,
                "revision": dev.get("revision"),
                "class": dev["class_name"],
                "class_id": dev["class_id"],
                "slot": dev["slot"],
                "subvendor": dev.get("subvendor"),
                "is_integrated": is_igpu,
                "is_discrete": not is_igpu,
                "vram_mb": self._gpu_vram_mb(dev),
                # Deep fields.
                "kernel_driver": gpu_driver,
                "drm_card": gpu_drm.get("card"),
                "drm_render": gpu_drm.get("render"),
                "drm_driver": gpu_drm.get("driver"),
                "drm_connector_count": gpu_drm.get("connector_count"),
                "drm_connectors": gpu_drm.get("connectors"),
                "gpu_total_mem_mb": gpu_drm.get("total_mem_mb"),
            })
        if not gpus:
            self.warn(field="gpu", message="No GPU detected via PCI class 0300/0302.")
        return gpus

    def _gpu_kernel_driver(self, dev: dict) -> str | None:
        """Read the kernel driver in use for a PCI device."""
        slot = dev.get("slot", "")
        driver_link = Path(f"/sys/bus/pci/devices/0000:{slot}/driver")
        try:
            return driver_link.resolve().name if driver_link.exists() else None
        except OSError:
            return None

    def _gpu_drm_info(self, dev: dict) -> dict:
        """Deep DRM info: card node, render node, connectors."""
        slot = dev.get("slot", "")
        result: dict = {}
        for card_dir in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
            device_link = card_dir / "device"
            if not device_link.exists():
                continue
            try:
                real = device_link.resolve().name
                if slot and slot not in real:
                    continue
            except OSError:
                continue
            result["card"] = f"/dev/dri/{card_dir.name}"
            # Driver name.
            try:
                drv = (card_dir / "device" / "driver").resolve().name
                result["driver"] = drv
            except OSError:
                pass
            # Render node.
            render = Path(f"/dev/dri/renderD{128 + int(card_dir.name.replace('card', ''))}")
            if render.exists():
                result["render"] = str(render)
            # Connectors.
            connectors = []
            for conn_dir in sorted(card_dir.glob(f"{card_dir.name}-*")):
                status_file = conn_dir / "status"
                try:
                    status = status_file.read_text().strip() if status_file.exists() else "unknown"
                except OSError:
                    status = "unknown"
                connectors.append({
                    "name": conn_dir.name.replace(f"{card_dir.name}-", ""),
                    "status": status,
                })
            result["connectors"] = connectors
            result["connector_count"] = len(connectors)
            # Total memory (AMD/Intel via DRM mem_info or gt/mem_total).
            for mem_path in (
                card_dir / "device" / "mem_info_vram_total",
                card_dir / "device" / "resource1",
            ):
                try:
                    if "mem_info" in str(mem_path):
                        val = int(mem_path.read_text().strip())
                        result["total_mem_mb"] = val // (1024 * 1024)
                    else:
                        size = mem_path.stat().st_size
                        if size > 0:
                            result["total_mem_mb"] = size // (1024 * 1024)
                except (OSError, ValueError):
                    continue
            break
        return result

    @staticmethod
    def _gpu_vram_mb(dev: dict) -> int | None:
        """Best-effort VRAM from sysfs drm. Works for some iGPUs/dGPUs."""
        slot = (dev.get("slot") or "").replace(":", "").replace(".", "")
        import glob as _glob
        for card in sorted(_glob.glob("/sys/class/drm/card*/device")):
            try:
                uevent = Path(card).joinpath("uevent").read_text()
            except OSError:
                continue
            if slot and slot not in uevent.replace("0000:", ""):
                continue
            for mem_file in ("mem_info_vram_total", "resource1", "resource1_hi"):
                p = Path(card) / mem_file
                try:
                    if "mem_info" in mem_file:
                        val = int(p.read_text().strip())
                        if val > 0:
                            return val // (1024 * 1024)
                    else:
                        size = int(p.stat().st_size)
                        if size > 0:
                            return size // (1024 * 1024)
                except (OSError, ValueError):
                    continue
        return None

    # ─── Audio ───────────────────────────────────────────────────────────

    def _scan_audio(self) -> dict:
        # Enumerate ALL audio codecs across all sound cards.
        codecs = self._read_all_audio_codecs()
        primary_codec = codecs[0] if codecs else None

        if not primary_codec:
            self.warn(
                field="audio.codec",
                message=(
                    "Could not read HDA codec from /proc/asound. "
                    "AppleALC layout-id will need to be set manually."
                ),
            )

        # Also detect HDMI/DP audio controllers from PCI.
        hdmi_audio = []
        for dev in self._pci_devices():
            if dev["class_id"] == "0403":  # Audio device
                name_lower = (dev.get("name") or "").lower()
                if "hdmi" in name_lower or "displayport" in name_lower or "dp" in name_lower:
                    hdmi_audio.append({
                        "name": dev["name"],
                        "vendor": dev["vendor_name"],
                        "pci_id": dev["pci_id"],
                        "slot": dev["slot"],
                    })

        # Number of ALSA cards.
        alsa_cards = self._count_alsa_cards()

        return {
            "codec": primary_codec["codec"] if primary_codec else None,
            "codec_id": primary_codec["codec_id"] if primary_codec else None,
            "all_codecs": codecs,
            "hdmi_audio_devices": hdmi_audio or None,
            "alsa_card_count": alsa_cards,
            "source": "/proc/asound/card*/codec#*",
        }

    @staticmethod
    def _read_all_audio_codecs() -> list[dict]:
        """Parse ALL HDA codecs across all sound cards."""
        codecs: list[dict] = []
        for codec_file in sorted(glob.glob("/proc/asound/card*/codec#*")):
            try:
                text = Path(codec_file).read_text(errors="replace")
            except OSError:
                continue
            codec_match = re.search(r"^Codec:\s*(.+)$", text, re.MULTILINE)
            vid_match = re.search(r"^Vendor Id:\s*0x([0-9a-f]{8})", text, re.MULTILINE)
            subsystem_match = re.search(r"^Subsystem Id:\s*0x([0-9a-f]{8})", text, re.MULTILINE)
            revision_match = re.search(r"^Revision Id:\s*0x([0-9a-f]+)", text, re.MULTILINE)
            if codec_match and vid_match:
                codec_name = codec_match.group(1).strip()
                raw = vid_match.group(1)
                codec_id = normalize_pci_id(raw[:4], raw[4:])
                codecs.append({
                    "codec": codec_name,
                    "codec_id": codec_id,
                    "subsystem_id": subsystem_match.group(1) if subsystem_match else None,
                    "revision": revision_match.group(1) if revision_match else None,
                    "source": codec_file,
                })
        return codecs

    @staticmethod
    def _count_alsa_cards() -> int:
        """Count the number of ALSA sound cards."""
        try:
            text = Path("/proc/asound/cards").read_text()
            return len(re.findall(r"^\s*\d+\s+\[", text, re.MULTILINE))
        except OSError:
            return 0

    # ─── Ethernet ────────────────────────────────────────────────────────

    def _scan_ethernet(self) -> list:
        eths = []
        for dev in self._by_category("ethernet"):
            # Deep: read driver, MAC, link speed from sysfs.
            iface_info = self._eth_iface_info(dev)
            eths.append({
                "name": dev["name"],
                "vendor": dev["vendor_name"],
                "pci_id": dev["pci_id"],
                "slot": dev["slot"],
                "subvendor": dev.get("subvendor"),
                "revision": dev.get("revision"),
                "kernel_driver": iface_info.get("driver"),
                "interface": iface_info.get("interface"),
                "mac_address": iface_info.get("mac"),
                "link_speed_mbps": iface_info.get("speed"),
                "link_up": iface_info.get("operstate") == "up",
            })
        return eths

    def _eth_iface_info(self, dev: dict) -> dict:
        """Read interface details from sysfs for a PCI ethernet device."""
        slot = dev.get("slot", "")
        result: dict = {}
        net_path = Path(f"/sys/bus/pci/devices/0000:{slot}/net")
        if net_path.exists():
            for iface_dir in net_path.iterdir():
                result["interface"] = iface_dir.name
                try:
                    result["mac"] = (iface_dir / "address").read_text().strip()
                except OSError:
                    pass
                try:
                    result["speed"] = int((iface_dir / "speed").read_text().strip())
                except (OSError, ValueError):
                    pass
                try:
                    result["operstate"] = (iface_dir / "operstate").read_text().strip()
                except OSError:
                    pass
                break
        # Kernel driver.
        driver_link = Path(f"/sys/bus/pci/devices/0000:{slot}/driver")
        try:
            result["driver"] = driver_link.resolve().name if driver_link.exists() else None
        except OSError:
            pass
        return result

    # ─── USB controllers ─────────────────────────────────────────────────

    def _scan_usb_controllers(self) -> list:
        ctrls = []
        for dev in self._by_category("usb_controller"):
            # Deep: read controller type (xHCI/EHCI/OHCI) and port count.
            ctrl_info = self._usb_controller_info(dev)
            ctrls.append({
                "name": dev["name"],
                "vendor": dev["vendor_name"],
                "pci_id": dev["pci_id"],
                "slot": dev["slot"],
                "subvendor": dev.get("subvendor"),
                "revision": dev.get("revision"),
                "controller_type": ctrl_info.get("type"),
                "kernel_driver": ctrl_info.get("driver"),
                "port_count": ctrl_info.get("port_count"),
                "needs_usb_map": True,  # macOS 15-port limit — always map
            })
        return ctrls

    def _usb_controller_info(self, dev: dict) -> dict:
        """Detect xHCI/EHCI/OHCI type and port count."""
        result: dict = {}
        slot = dev.get("slot", "")
        # Driver name reveals type.
        driver_link = Path(f"/sys/bus/pci/devices/0000:{slot}/driver")
        try:
            if driver_link.exists():
                drv = driver_link.resolve().name
                result["driver"] = drv
                if "xhci" in drv.lower():
                    result["type"] = "xHCI (USB 3.x)"
                elif "ehci" in drv.lower():
                    result["type"] = "EHCI (USB 2.0)"
                elif "ohci" in drv.lower():
                    result["type"] = "OHCI (USB 1.1)"
                elif "uhci" in drv.lower():
                    result["type"] = "UHCI (USB 1.1)"
        except OSError:
            pass
        # Count USB ports under this controller.
        usb_path = Path(f"/sys/bus/pci/devices/0000:{slot}")
        if usb_path.exists():
            ports = list(usb_path.glob("usb*/*/port*"))
            result["port_count"] = len(ports) if ports else None
        return result

    # ─── Wireless (WiFi + Bluetooth) ─────────────────────────────────────

    def _scan_wireless(self) -> dict:
        wifi_devs = self._by_category("wifi")
        # Enumerate ALL wifi cards, not just the first.
        all_wifi: list[dict] = []
        for w in wifi_devs:
            wifi_info = {
                "chip": w["name"],
                "vendor": w["vendor_name"],
                "pci_id": w["pci_id"],
                "slot": w["slot"],
                "subvendor": w.get("subvendor"),
                "revision": w.get("revision"),
            }
            # Read kernel driver and interface.
            driver_link = Path(f"/sys/bus/pci/devices/0000:{w['slot']}/driver")
            try:
                wifi_info["kernel_driver"] = driver_link.resolve().name if driver_link.exists() else None
            except OSError:
                wifi_info["kernel_driver"] = None
            # Read interface name.
            net_path = Path(f"/sys/bus/pci/devices/0000:{w['slot']}/net")
            if net_path.exists():
                for iface in net_path.iterdir():
                    wifi_info["interface"] = iface.name
                    break
            all_wifi.append(wifi_info)

        wifi = all_wifi[0] if all_wifi else None
        if not wifi:
            self.warn(field="wireless.wifi", message="No wireless PCI device found.")

        bt_devices = self._detect_all_bluetooth()
        bt = bt_devices[0] if bt_devices else {}

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
            "wifi_driver": wifi.get("kernel_driver") if wifi else None,
            "wifi_interface": wifi.get("interface") if wifi else None,
            "wifi_support": wifi_support,
            "wifi_kext": wifi_kext,
            "all_wifi_cards": all_wifi if len(all_wifi) > 1 else None,
            "bluetooth_chip": bt.get("name"),
            "bt_usb_id": bt.get("usb_id"),
            "bt_vendor": bt.get("vendor"),
            "bt_kext": "IntelBluetoothFirmware.kext" if bt else None,
            "all_bluetooth": bt_devices if len(bt_devices) > 1 else None,
            "airdrop_support": is_broadcom,
        }

    def _detect_all_bluetooth(self) -> list[dict]:
        """Enumerate ALL Bluetooth devices (USB). Not just the first."""
        devices: list[dict] = []
        out, _ = run(["lsusb"])
        for line in out.splitlines():
            low = line.lower()
            if "bluetooth" in low or "bcm2045" in low or "0a12:" in low or "8087:0" in low:
                m = re.search(r"ID\s+([0-9a-f]{4}):([0-9a-f]{4})", line)
                usb_id = normalize_pci_id(m.group(1), m.group(2)) if m else None
                name = re.sub(r"^Bus\s+\d+\s+Device\s+\d+:\s*ID\s+[0-9a-f:]+\s*", "", line).strip()
                vendor_id = m.group(1) if m else None
                vendor = {
                    "8087": "Intel", "0489": "Foxconn", "0a5c": "Broadcom",
                    "0cf3": "Qualcomm Atheros", "13d3": "IMC", "0bda": "Realtek",
                }.get(vendor_id, "Unknown")
                devices.append({"name": name, "usb_id": usb_id, "vendor": vendor})
        return devices

    # ─── Motherboard / BIOS / Chassis ────────────────────────────────────

    def _scan_motherboard(self) -> dict:
        dmi = self._read_dmi_sys()
        chassis_type = self._chassis_type(dmi.get("chassis_type"))
        model = dmi.get("board_name") or dmi.get("product_name") or ""
        chipset = self._guess_chipset()

        # Deep: full chipset name from ISA/LPC bridge.
        chipset_full = self._full_chipset_name()

        # Deep: dmidecode for serial, UUID, BIOS features (needs root).
        dmi_deep = self._dmidecode_board_info()

        # Deep: ACPI tables available (DSDT, SSDT, etc.).
        acpi_tables = self._list_acpi_tables()

        # Deep: IOMMU status.
        iommu = self._iommu_status()

        return {
            "vendor": dmi.get("board_vendor") or dmi.get("sys_vendor"),
            "model": model,
            "product_name": dmi.get("product_name"),
            "product_version": dmi.get("product_version"),
            "board_version": dmi.get("board_version"),
            "sys_vendor": dmi.get("sys_vendor"),
            "chipset": chipset,
            "chipset_full": chipset_full,
            "bios_version": dmi.get("bios_version"),
            "bios_vendor": dmi.get("bios_vendor"),
            "bios_date": dmi.get("bios_date"),
            "chassis_type": chassis_type,
            "chassis_type_raw": dmi.get("chassis_type"),
            "has_ec": chassis_type in ("laptop", "desktop"),
            # Deep fields (root).
            "board_serial": dmi_deep.get("board_serial"),
            "system_serial": dmi_deep.get("system_serial"),
            "system_uuid": dmi_deep.get("system_uuid"),
            "bios_rom_size": dmi_deep.get("bios_rom_size"),
            "bios_features": dmi_deep.get("bios_features"),
            "acpi_tables": acpi_tables,
            "iommu_enabled": iommu.get("enabled"),
            "iommu_type": iommu.get("type"),
            "iommu_groups": iommu.get("group_count"),
        }

    def _dmidecode_board_info(self) -> dict:
        """Root-backed upgrade: serial numbers, UUID, BIOS features."""
        result: dict = {}
        # Board serial.
        out, rc = run(["dmidecode", "-s", "baseboard-serial-number"], as_root=True)
        if rc == 0 and out.strip():
            self.used_root = True
            result["board_serial"] = out.strip()
        # System serial.
        out, rc = run(["dmidecode", "-s", "system-serial-number"], as_root=True)
        if rc == 0 and out.strip():
            result["system_serial"] = out.strip()
        # System UUID.
        out, rc = run(["dmidecode", "-s", "system-uuid"], as_root=True)
        if rc == 0 and out.strip():
            result["system_uuid"] = out.strip()
        # BIOS ROM size + features.
        out, rc = run(["dmidecode", "-t", "bios"], as_root=True)
        if rc == 0 and out:
            self.used_root = True
            rom_m = re.search(r"ROM Size:\s*(.+)", out)
            if rom_m:
                result["bios_rom_size"] = rom_m.group(1).strip()
            # Collect BIOS characteristics.
            features: list[str] = []
            in_chars = False
            for line in out.splitlines():
                if "Characteristics:" in line:
                    in_chars = True
                    continue
                if in_chars:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("Handle") and not stripped.startswith("BIOS"):
                        if re.match(r"^[A-Z]|^[a-z]", stripped):
                            features.append(stripped)
                    elif not stripped:
                        in_chars = False
            result["bios_features"] = features or None
        return result

    @staticmethod
    def _list_acpi_tables() -> list[str] | None:
        """List ACPI tables present in /sys/firmware/acpi/tables."""
        acpi_path = Path("/sys/firmware/acpi/tables")
        if not acpi_path.exists():
            return None
        tables: list[str] = []
        try:
            for child in sorted(acpi_path.iterdir()):
                tables.append(child.name)
        except PermissionError:
            pass
        return tables or None

    @staticmethod
    def _iommu_status() -> dict:
        """Detect IOMMU (VT-d / AMD-Vi) status."""
        result: dict = {"enabled": False, "type": None, "group_count": None}
        # Check kernel command line for iommu.
        try:
            cmdline = Path("/proc/cmdline").read_text()
            if "iommu=on" in cmdline or "intel_iommu=on" in cmdline or "amd_iommu=on" in cmdline:
                result["enabled"] = True
        except OSError:
            pass
        # Check dmesg for IOMMU (may need root).
        iommu_path = Path("/sys/class/iommu")
        if iommu_path.exists():
            children = list(iommu_path.iterdir())
            if children:
                result["enabled"] = True
                first = children[0].name
                if "dmar" in first.lower():
                    result["type"] = "Intel VT-d"
                elif "ivhd" in first.lower() or "amd" in first.lower():
                    result["type"] = "AMD-Vi"
        # Count IOMMU groups.
        iommu_groups = Path("/sys/kernel/iommu_groups")
        if iommu_groups.exists():
            try:
                groups = [d for d in iommu_groups.iterdir() if d.is_dir()]
                result["group_count"] = len(groups)
                if groups:
                    result["enabled"] = True
            except PermissionError:
                pass
        return result

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

    def _full_chipset_name(self) -> str | None:
        """Return the full ISA/LPC bridge or host bridge name as chipset detail."""
        for dev in self._pci_devices():
            if dev["class_id"] == "0601":  # ISA bridge — most descriptive
                return dev["name"]
        for dev in self._pci_devices():
            if dev["class_id"] == "0600":  # Host bridge
                return dev["name"]
        return None

    # ─── Storage ─────────────────────────────────────────────────────────

    def _scan_storage(self) -> list:
        disks: list[dict] = []
        # Extended lsblk columns for deeper info.
        out, _ = run(["lsblk", "-J", "-d", "-o",
                       "NAME,SIZE,TYPE,MODEL,VENDOR,TRAN,ROTA,SERIAL,REV,FSTYPE,PTTYPE,HOTPLUG,STATE"])
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

            # Deep: read NVMe-specific info from sysfs.
            dev_name = blk.get("name", "")
            nvme_info = self._nvme_deep_info(dev_name) if tran == "nvme" else {}

            # Partition table type.
            pt_type = blk.get("pttype") or None

            disks.append({
                "name": name.strip(),
                "device": f"/dev/{dev_name}",
                "size_gb": self._bytes_to_gb(blk.get("size")),
                "type": disk_type,
                "rotational": blk.get("rota") == "1" or blk.get("rota") is True,
                "transport": tran or None,
                "vendor": (blk.get("vendor") or "").strip() or None,
                "serial": (blk.get("serial") or "").strip() or None,
                "firmware_rev": (blk.get("rev") or "").strip() or None,
                "partition_table": pt_type,
                "hotplug": blk.get("hotplug"),
                "state": blk.get("state"),
                # NVMe deep info.
                "nvme_model": nvme_info.get("model"),
                "nvme_firmware": nvme_info.get("firmware_rev"),
                "nvme_serial": nvme_info.get("serial"),
                "nvme_pcie_speed": nvme_info.get("pcie_speed"),
            })
        return disks

    @staticmethod
    def _nvme_deep_info(dev_name: str) -> dict:
        """Read NVMe-specific details from sysfs."""
        result: dict = {}
        # /sys/block/nvme0n1/device/ has model, firmware_rev, serial.
        dev_path = Path(f"/sys/block/{dev_name}/device")
        for field in ("model", "firmware_rev", "serial"):
            try:
                val = (dev_path / field).read_text().strip()
                if val:
                    result[field] = val
            except OSError:
                continue
        # PCIe link speed.
        # NVMe controller is at /sys/block/nvmeXn1/device/device (PCI device).
        pci_dev = dev_path / "device"
        if pci_dev.exists():
            try:
                speed = (pci_dev / "current_link_speed").read_text().strip()
                result["pcie_speed"] = speed
            except OSError:
                pass
        return result

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
        # Deep: get available/free/swap from /proc/meminfo.
        meminfo = self._meminfo_details()
        # Memory type/speed/slots need dmidecode (root). Try root-backed upgrade.
        details = self._dmidecode_memory()
        if not details:
            self.warn(
                field="memory",
                message=(
                    "Memory type/speed/slots need dmidecode (requires root). "
                    "Re-run with sudo for full memory details."
                ),
                needs_root=True,
            )
        return {
            "total_gb": total_gb,
            "available_gb": meminfo.get("available_gb"),
            "swap_total_gb": meminfo.get("swap_total_gb"),
            "type": details.get("type"),
            "speed_mhz": details.get("speed"),
            "configured_speed_mhz": details.get("configured_speed"),
            "slots_used": details.get("slots_used"),
            "slots_total": details.get("slots_total"),
            "max_capacity_gb": details.get("max_capacity_gb"),
            "form_factor": details.get("form_factor"),
            "dimms": details.get("dimms"),
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

    @staticmethod
    def _meminfo_details() -> dict:
        """Read additional memory info from /proc/meminfo."""
        result: dict = {}
        try:
            text = Path("/proc/meminfo").read_text()
            for key, target in [("MemAvailable", "available_gb"), ("SwapTotal", "swap_total_gb")]:
                m = re.search(rf"^{key}:\s+(\d+)", text, re.MULTILINE)
                if m:
                    result[target] = int(int(m.group(1)) / 1024 / 1024)
        except OSError:
            pass
        return result

    def _dmidecode_memory(self) -> dict:
        """Root-backed upgrade: full DIMM details."""
        out, rc = run(["dmidecode", "-t", "memory"], as_root=True)
        if rc != 0 or not out:
            return {}
        self.used_root = True

        types: set[str] = set()
        speeds: list[int] = []
        configured_speeds: list[int] = []
        form_factors: set[str] = set()
        max_capacity: str | None = None
        slots_total = 0
        slots_used = 0

        # Parse individual DIMM entries.
        dimms: list[dict] = []
        current_dimm: dict = {}
        in_device = False

        for line in out.splitlines():
            stripped = line.strip()

            # Track Memory Array for max capacity.
            if stripped.startswith("Maximum Capacity:"):
                max_capacity = stripped.split(":", 1)[1].strip()

            if stripped.startswith("Memory Device"):
                if current_dimm and current_dimm.get("size"):
                    dimms.append(current_dimm)
                current_dimm = {}
                in_device = True
                slots_total += 1
                continue

            if in_device and ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip()
                if key == "Size":
                    current_dimm["size"] = val
                    if "No Module" not in val and val != "Unknown":
                        slots_used += 1
                elif key == "Type" and val != "Unknown":
                    current_dimm["type"] = val
                    types.add(val)
                elif key == "Speed" and val != "Unknown":
                    current_dimm["speed"] = val
                    m = re.search(r"(\d+)", val)
                    if m:
                        speeds.append(int(m.group(1)))
                elif key == "Configured Memory Speed" and val != "Unknown":
                    current_dimm["configured_speed"] = val
                    m = re.search(r"(\d+)", val)
                    if m:
                        configured_speeds.append(int(m.group(1)))
                elif key == "Manufacturer" and val != "Unknown":
                    current_dimm["manufacturer"] = val
                elif key == "Part Number" and val.strip():
                    current_dimm["part_number"] = val
                elif key == "Serial Number" and val != "Unknown":
                    current_dimm["serial"] = val
                elif key == "Form Factor" and val != "Unknown":
                    current_dimm["form_factor"] = val
                    form_factors.add(val)
                elif key == "Locator":
                    current_dimm["locator"] = val
                elif key == "Rank" and val != "Unknown":
                    current_dimm["rank"] = val

        # Append last DIMM.
        if current_dimm and current_dimm.get("size"):
            dimms.append(current_dimm)

        # Filter out empty slots from dimms list.
        populated = [d for d in dimms if "No Module" not in d.get("size", "")]

        # Parse max capacity.
        max_cap_gb = None
        if max_capacity:
            m = re.search(r"(\d+)\s*(GB|TB)", max_capacity, re.IGNORECASE)
            if m:
                val = int(m.group(1))
                max_cap_gb = val * 1024 if m.group(2).upper() == "TB" else val

        return {
            "type": "/".join(sorted(types)) if types else None,
            "speed": min(speeds) if speeds else None,
            "configured_speed": min(configured_speeds) if configured_speeds else None,
            "slots_used": slots_used or None,
            "slots_total": slots_total or None,
            "max_capacity_gb": max_cap_gb,
            "form_factor": "/".join(sorted(form_factors)) if form_factors else None,
            "dimms": populated or None,
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
        # Modern Intel (Z390+, 300-series+) and all AMD Ryzen have native NVRAM.
        host_bridge = next(
            (d for d in self._pci_devices() if d["class_id"] == "0600"), None
        )
        chipset = self._guess_chipset() or ""
        modern = any(chip in chipset for chip in ("Z390", "Z490", "Z590", "Z690", "Z790",
                                                   "B6", "B7", "H6", "H7", "X5", "B5", "A5", "A6"))

        # Deep: check if EFI variables are accessible (indicates UEFI runtime).
        efi_vars_path = Path("/sys/firmware/efi/efivars")
        efi_vars_accessible = efi_vars_path.exists()
        efi_var_count = None
        if efi_vars_accessible:
            try:
                efi_var_count = sum(1 for _ in efi_vars_path.iterdir())
            except PermissionError:
                pass

        # Deep: check NVRAM type from the host bridge vendor.
        nvram_type = None
        if host_bridge:
            hb_vendor = (host_bridge.get("vendor_name") or "").lower()
            if "intel" in hb_vendor:
                nvram_type = "native" if modern else "emulated (SSDT-PMC)"
            elif "amd" in hb_vendor:
                nvram_type = "native"  # All AMD Ryzen have native NVRAM

        recommendation = None
        if not modern and chipset:
            recommendation = (
                "Older chipset detected — use SSDT-PMC.aml or OpenCore's "
                "emulated NVRAM (Misc → Boot → LauncherOption = Full)."
            )

        return {
            "native_nvram": modern or None,
            "use_emulated": not modern if chipset else None,
            "type": nvram_type,
            "recommendation": recommendation,
            "efi_vars_accessible": efi_vars_accessible,
            "efi_var_count": efi_var_count,
            "host_bridge": host_bridge.get("name") if host_bridge else None,
        }

    # ─── Display ports (heuristic from GPU presence) ────────────────────

    def _scan_display_ports(self) -> dict:
        gpus = self._by_category("gpu")
        has_dgpu = len(gpus) > 1
        has_igpu = any("Intel" in g["vendor_name"] for g in gpus)

        # Deep: enumerate DRM connectors to detect actual display outputs.
        connectors: list[dict] = []
        hdmi_count = 0
        dp_count = 0
        vga_count = 0
        edp_count = 0
        dvi_count = 0

        drm_path = Path("/sys/class/drm")
        if drm_path.exists():
            for conn_dir in sorted(drm_path.glob("card*-*")):
                name = conn_dir.name
                # Skip the card itself (card0, card1); we want card0-HDMI-A-1 etc.
                if re.match(r"^card\d+$", name):
                    continue
                # Parse connector type from name: card0-HDMI-A-1, card0-DP-1, etc.
                conn_type = re.sub(r"^card\d+-", "", name)
                status = "unknown"
                try:
                    status_file = conn_dir / "status"
                    if status_file.exists():
                        status = status_file.read_text().strip()
                except OSError:
                    pass
                # Detect resolution if enabled.
                modes: list[str] = []
                try:
                    modes_file = conn_dir / "modes"
                    if modes_file.exists():
                        raw = modes_file.read_text().strip()
                        if raw:
                            modes = raw.splitlines()[:5]  # Top 5 modes
                except OSError:
                    pass
                connectors.append({
                    "name": conn_type,
                    "status": status,
                    "modes": modes or None,
                })
                ct = conn_type.upper()
                if "HDMI" in ct:
                    hdmi_count += 1
                elif ct.startswith("DP") or "DISPLAYPORT" in ct:
                    dp_count += 1
                elif "VGA" in ct:
                    vga_count += 1
                elif "EDP" in ct:
                    edp_count += 1
                elif "DVI" in ct:
                    dvi_count += 1

        return {
            "hdmi": hdmi_count or None,
            "displayport": dp_count or None,
            "vga": vga_count or None,
            "edp": edp_count or None,
            "dvi": dvi_count or None,
            "total_connectors": len(connectors),
            "connectors": connectors or None,
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

    # ─── Full USB device enumeration ──────────────────────────────────────

    def _scan_usb_devices(self) -> list[dict]:
        """Enumerate ALL USB devices via lsusb — not just Bluetooth.

        Hackintosh-relevant USB devices beyond BT: webcams (UVC), SD card
        readers, fingerprint readers, internal hubs. These all matter for
        USB port mapping (macOS 15-port limit) and need to be mapped.
        """
        devices: list[dict] = []
        out, _ = run(["lsusb"])
        if not out:
            self.warn(field="usb_devices", message="lsusb returned nothing.",
                      severity="info")
            return devices
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            # Format: "Bus 001 Device 003: ID 8087:0a2b Intel Corp. wireless"
            m = re.match(
                r"Bus\s+(\d+)\s+Device\s+(\d+):\s*ID\s+([0-9a-f]{4}):([0-9a-f]{4})\s*(.*)",
                line, re.IGNORECASE,
            )
            if not m:
                continue
            bus, dev_num, vid, pid, name = m.groups()
            low = name.lower()
            # Classify by common hackintosh-relevant keywords + known vendor IDs.
            category = "other"
            if "bluetooth" in low or "bt" in low or "wireless" in low:
                category = "bluetooth"
            elif "camera" in low or "webcam" in low or "uvc" in low:
                category = "camera"
            elif "sd " in low or "card reader" in low or "multicard" in low:
                category = "card_reader"
            elif "fingerprint" in low or "biometric" in low:
                category = "biometric"
            elif "hub" in low:
                category = "hub"
            elif vid in ("046d", "045e", "1532"):  # Logitech/Microsoft/Razer
                category = "input"
            devices.append({
                "bus": int(bus),
                "device": int(dev_num),
                "usb_id": normalize_pci_id(vid, pid),
                "name": name.strip(),
                "category": category,
            })
        return devices

    # ─── All PCI devices (unfiltered) ─────────────────────────────────────

    def _scan_all_pci(self) -> list[dict]:
        """Capture EVERY PCI device, not just the filtered classes.

        The category-filtered scanners above (GPU, ethernet, etc.) capture the
        obvious hackintosh components. But unknown devices — SD card readers,
        serial/UART controllers, platform trust modules, thermal subsystems —
        can cause kernel panics if macOS has no driver and no SSDT covers them.
        Recording the full tree gives Phase 2 the complete picture.
        """
        all_devs: list[dict] = []
        for dev in self._pci_devices():
            all_devs.append({
                "slot": dev.get("slot"),
                "class": dev.get("class_name"),
                "class_id": dev.get("class_id"),
                "category": dev.get("category"),
                "name": dev.get("name"),
                "vendor": dev.get("vendor_name"),
                "pci_id": dev.get("pci_id"),
                "subvendor": dev.get("subvendor"),
                "revision": dev.get("revision"),
            })
        return all_devs

    # ─── Boot mode + partition table ──────────────────────────────────────

    def _scan_boot_info(self) -> dict:
        """Detect UEFI/Legacy boot mode + disk partition tables.

        OpenCore REQUIRES UEFI + GPT. Detecting Legacy/MBR here lets Phase 2
        warn the user to convert before attempting install.
        """
        # UEFI check: /sys/firmware/efi exists iff booted via EFI.
        efi_path = Path("/sys/firmware/efi")
        is_efi = efi_path.exists()

        # Partition table per disk (GPT vs MBR/dos).
        partitions: list[dict] = []
        for disk in self._scan_storage():
            dev = (disk.get("device") or "").replace("/dev/", "")
            if not dev:
                continue
            pt_type = self._blkid_ptable(dev)
            partitions.append({
                "device": disk.get("device"),
                "name": disk.get("name"),
                "table": pt_type,  # 'gpt', 'dos', or None
            })

        return {
            "efi_booted": is_efi,
            "mode": "UEFI" if is_efi else "Legacy (CSM)",
            "secure_boot": self._secure_boot_status(),
            "partition_tables": partitions,
            "note": None if is_efi else (
                "System booted in Legacy/CSM mode. OpenCore requires UEFI — "
                "enable UEFI in BIOS before macOS install."
            ),
        }

    @staticmethod
    def _blkid_ptable(dev_name: str) -> str | None:
        """Read partition table type from /sys/block/<dev>/device or lsblk."""
        # /sys/block/sda doesn't expose PT type directly; parse `lsblk <dev>`.
        try:
            out, _ = run(["lsblk", f"/dev/{dev_name}", "-J", "-o", "PTTYPE"])
            data = json.loads(out) if out else {}
            for blk in data.get("blockdevices", []):
                return (blk.get("pttype") or "").lower() or None
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    @staticmethod
    def _secure_boot_status() -> bool | None:
        """Read Secure Boot status from efivarfs if present."""
        var = Path("/sys/firmware/efi/efivars/SecureBoot-8be4df61-92ca-11d2-aa0d-00e098032b8c")
        if not var.exists():
            return None
        try:
            data = var.read_bytes()
            # The SecureBoot var is 1 byte flag at offset 4 (after 4-byte attrs).
            return bool(data[4]) if len(data) > 4 else None
        except OSError:
            return None

    # ─── Battery (laptop) ─────────────────────────────────────────────────

    def _scan_battery(self) -> dict:
        """Detect battery presence — drives SMCBatteryManager kext + SMBIOS.

        Laptops need SMCBatteryManager.kext for battery status to work in
        macOS. Desktops/servers have no battery. Detecting it here lets Phase
        2 add the kext and pick the right SMBIOS chassis.
        """
        bat_path = Path("/sys/class/power_supply")
        batteries: list[str] = []
        ac_only = True
        if bat_path.exists():
            for child in bat_path.iterdir():
                name = child.name
                try:
                    ptype = (child / "type").read_text().strip()
                except OSError:
                    continue
                if ptype == "Battery":
                    batteries.append(name)
                    ac_only = False
        present = bool(batteries)
        capacity = None
        if present:
            try:
                energy_full = int((bat_path / batteries[0] / "energy_full").read_text())
                charge_full_design = int((bat_path / batteries[0] / "energy_full_design").read_text())
                capacity = round(energy_full / charge_full_design * 100) if charge_full_design else None
            except (OSError, ValueError, ZeroDivisionError):
                pass
        return {
            "present": present,
            "count": len(batteries),
            "names": batteries or None,
            "health_pct": capacity,
            "needs_smbat_kext": present,
        }

    # ─── Network MAC addresses (for SMBIOS ROM) ───────────────────────────

    def _scan_network_macs(self) -> dict:
        """Capture NIC MAC addresses — used as the SMBIOS ROM field.

        GenSMBIOS can use a real NIC MAC as the ROM (board-id), which is more
        realistic for iServices than a random one. We capture the primary
        ethernet MAC; WiFi MACs are usually randomised and skipped.
        """
        macs: dict[str, str] = {}
        net_path = Path("/sys/class/net")
        primary_eth = None
        if net_path.exists():
            for iface in sorted(net_path.iterdir()):
                name = iface.name
                if name == "lo":
                    continue
                try:
                    mac = (iface / "address").read_text().strip()
                except OSError:
                    continue
                if mac and mac != "00:00:00:00:00:00":
                    macs[name] = mac
                    # Prefer physical ethernet (enp/eth) over wireless (wlp/wlan).
                    if primary_eth is None and name.startswith(("enp", "eth", "eno")):
                        primary_eth = mac
        return {
            "interfaces": macs or None,
            "primary_mac": primary_eth,
            "note": (
                "Primary ethernet MAC can be used as SMBIOS ROM for realistic "
                "iServices identity." if primary_eth else
                "No wired ethernet MAC found — ROM will be random."
            ),
        }

    # ─── TPM / fTPM ───────────────────────────────────────────────────────

    def _scan_tpm(self) -> dict:
        """Detect TPM 2.0 / fTPM presence.

        macOS Sonoma+ on some hardware benefits from or conflicts with TPM.
        Detecting it informs Secure Boot + Apple Secure Boot config decisions.
        """
        # /sys/class/tpm/tpm0 exists if a TPM is enumerated.
        tpm_path = Path("/sys/class/tpm")
        present = False
        version = None
        if tpm_path.exists():
            for child in tpm_path.iterdir():
                if child.name.startswith("tpm"):
                    present = True
                    # TPM version from /sys/class/tpm/tpm0/tpm_version_major
                    try:
                        version = (child / "tpm_version_major").read_text().strip()
                    except OSError:
                        version = "unknown"
                    break
        return {
            "present": present,
            "version_major": version,
            "ftp_amd": None,  # refined by CPU vendor check in Phase 2
        }

    # ─── Webcam / front camera ────────────────────────────────────────────

    def _scan_camera(self) -> dict:
        """Detect webcam presence (USB Video Class or MIPI).

        Laptops have a built-in webcam that shows up as a UVC USB device or
        via /dev/video*. Important for USB mapping.
        """
        video_devs = list(Path("/dev").glob("video*"))
        # Cross-ref USB enumeration for UVC cameras.
        usb_cams: list[str] = []
        out, _ = run(["lsusb"])
        if out:
            for line in out.splitlines():
                low = line.lower()
                if "camera" in low or "webcam" in low or "uvc" in low:
                    name = re.sub(r"^Bus\s+\d+\s+Device\s+\d+:\s*ID\s+[0-9a-f:]+\s*", "", line).strip()
                    if name:
                        usb_cams.append(name)
        present = bool(video_devs) or bool(usb_cams)
        return {
            "present": present,
            "video_devices": [str(p) for p in video_devs] or None,
            "usb_cameras": usb_cams or None,
        }

    # ─── CPU cache sizes ──────────────────────────────────────────────────

    def _scan_cpu_caches(self) -> dict:
        """Read L1/L2/L3 cache sizes from sysfs (root-free)."""
        caches: dict[str, int | None] = {"l1_data_kb": None, "l1_inst_kb": None,
                                          "l2_kb": None, "l3_kb": None}
        cpu_cache = Path("/sys/devices/system/cpu/cpu0/cache")
        if not cpu_cache.exists():
            return caches
        for idx_dir in cpu_cache.iterdir():
            if not idx_dir.name.startswith("index"):
                continue
            try:
                level = (idx_dir / "level").read_text().strip()
                ctype = (idx_dir / "type").read_text().strip()
                size_str = (idx_dir / "size").read_text().strip()
            except OSError:
                continue
            size_kb = self._cache_kb(size_str)
            if not size_kb:
                continue
            if level == "1":
                if ctype == "Data":
                    caches["l1_data_kb"] = size_kb
                elif ctype == "Instruction":
                    caches["l1_inst_kb"] = size_kb
            elif level == "2":
                caches["l2_kb"] = size_kb
            elif level == "3":
                caches["l3_kb"] = size_kb
        return caches

    @staticmethod
    def _cache_kb(size_str: str) -> int | None:
        """'32K' / '256K' / '4M' → KB integer."""
        m = re.match(r"(\d+)([KM])", size_str, re.IGNORECASE)
        if not m:
            return None
        val = int(m.group(1))
        unit = m.group(2).upper()
        return val * 1024 if unit == "M" else val
