"""Windows hardware scanner (WMI implementation).

Phase 1 scope per the blueprint: the Linux scanner is the primary deliverable
and is fully runnable. The Windows scanner shares the *same* base class and
output contract, so it plugs into the same pipeline. This file is a working
scaffold: the structure and every ``_scan_*`` signature match LinuxScanner,
and the implementations raise ``NotImplementedError`` with a clear message so
the platform router fails gracefully on Windows.

Full implementation lands when Phase 1 is validated on Linux. The WMI query
table is already documented in the blueprint's platform-comparison section.
"""
from __future__ import annotations

from .base_scanner import BaseScanner


class WindowsScanner(BaseScanner):
    """WMI-backed scanner. Full implementation pending Phase 1 validation.

    When implemented, each method will use ``wmi.query("SELECT ... FROM Win32_*")``
    and normalize to the same shape ``LinuxScanner`` produces. The enrichment
    layer in ``BaseScanner`` is shared, so kext/codec/macOS-support lookups
    work identically on both platforms.
    """

    _TODO = (
        "WindowsScanner not yet implemented. Phase 1 delivers LinuxScanner "
        "first. See SCHEMA.md — output contract is identical to LinuxScanner."
    )

    def __init__(self) -> None:
        super().__init__()
        # WMI is Windows-only; importing here keeps Linux installs dependency-free.
        raise NotImplementedError(self._TODO)

    def _scan_cpu(self) -> dict:
        raise NotImplementedError(self._TODO)

    def _scan_gpu(self) -> list:
        raise NotImplementedError(self._TODO)

    def _scan_audio(self) -> dict:
        raise NotImplementedError(self._TODO)

    def _scan_ethernet(self) -> list:
        raise NotImplementedError(self._TODO)

    def _scan_usb_controllers(self) -> list:
        raise NotImplementedError(self._TODO)

    def _scan_wireless(self) -> dict:
        raise NotImplementedError(self._TODO)

    def _scan_motherboard(self) -> dict:
        raise NotImplementedError(self._TODO)

    def _scan_storage(self) -> list:
        raise NotImplementedError(self._TODO)

    def _scan_memory(self) -> dict:
        raise NotImplementedError(self._TODO)

    def _scan_input_devices(self) -> dict:
        raise NotImplementedError(self._TODO)

    def _scan_nvram(self) -> dict:
        raise NotImplementedError(self._TODO)

    def _scan_display_ports(self) -> dict:
        raise NotImplementedError(self._TODO)

    # Deep-scan sections (Phase 1.5).
    def _scan_all_pci(self) -> list | dict:
        raise NotImplementedError(self._TODO)

    def _scan_usb_devices(self) -> list | dict:
        raise NotImplementedError(self._TODO)

    def _scan_battery(self) -> dict:
        raise NotImplementedError(self._TODO)

    def _scan_boot_info(self) -> dict:
        raise NotImplementedError(self._TODO)

    def _scan_network_macs(self) -> dict:
        raise NotImplementedError(self._TODO)

    def _scan_tpm(self) -> dict:
        raise NotImplementedError(self._TODO)

    def _scan_camera(self) -> dict:
        raise NotImplementedError(self._TODO)

    def _scan_cpu_caches(self) -> dict:
        raise NotImplementedError(self._TODO)
