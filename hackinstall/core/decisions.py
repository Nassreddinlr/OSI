"""Decision engine — turns a hardware profile into a BuildPlan.

This is the brain of Phase 2. It reads ``hardware_profile.json`` + the
compatibility matrix and produces a fully-resolved ``BuildPlan`` dict that
``config_generator.py`` turns into config.plist.

Responsibilities:
  1. Check for blockers (unsupported CPU/GPU combinations).
  2. Pick the macOS target version (respects hardware limits).
  3. Select quirks by CPU microarchitecture.
  4. Build boot-args from GPU type.
  5. Delegate to smbios_gen, kext_selector, ssdt_builder.
  6. Record every decision as a human-readable note.

Every decision is traceable: each note explains *why* a value was chosen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import __version__
from ..data import _load
from . import kext_selector, smbios_gen, ssdt_builder
from .exceptions import Blocker

_OC_VERSION = "1.0.3"


def build_plan(profile: dict, macos_target: str = "auto") -> dict[str, Any]:
    """Produce a BuildPlan from a hardware profile.

    Args:
        profile: the hardware_profile.json dict from Phase 1.
        macos_target: one of 'auto', 'ventura', 'sonoma', 'sequoia'.

    Returns the BuildPlan dict. May raise ``Blocker`` on hard stops; callers
    should catch and surface the message.
    """
    cpu = profile.get("cpu", {}) or {}
    gpus = profile.get("gpu", []) or []
    motherboard = profile.get("motherboard", {}) or {}
    wireless = profile.get("wireless", {}) or {}
    memory = profile.get("memory", {}) or {}

    blockers: list[dict] = []
    warnings: list[dict] = []
    notes: list[str] = []

    # ── 1. Hard-stop checks ──────────────────────────────────────────────
    _check_cpu_support(cpu, blockers, notes)
    _check_gpu_support(gpus, blockers, notes)

    # ── 2. macOS target version ──────────────────────────────────────────
    target = _resolve_macos_target(macos_target, cpu, notes)

    # ── 3. Quirks by microarchitecture ───────────────────────────────────
    quirks = _select_quirks(cpu, notes)

    # ── 4. Boot-args from GPU ────────────────────────────────────────────
    boot_args = _build_boot_args(gpus, cpu, notes)

    # ── 5. Kexts ─────────────────────────────────────────────────────────
    kexts = kext_selector.select_kexts(profile)

    # ── 6. SSDTs ─────────────────────────────────────────────────────────
    ssdts = ssdt_builder.select_ssdts(profile)

    # ── 7. SMBIOS ────────────────────────────────────────────────────────
    smbios, smbios_warnings = _generate_smbios(cpu, motherboard, notes)

    # ── 8. Soft warnings (non-blocking) ──────────────────────────────────
    _collect_warnings(memory, wireless, profile, warnings)

    plan: dict[str, Any] = {
        "plan_metadata": {
            "generated_from": "hardware_profile.json",
            "macos_target": target,
            "opencore_version": _OC_VERSION,
            "decisions_version": __version__,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hardware_summary": {
                "cpu": cpu.get("name"),
                "cpu_codename": cpu.get("codename"),
                "cpu_microarch": cpu.get("microarch"),
                "gpus": [g.get("name") for g in gpus],
                "board": f"{motherboard.get('vendor','?')} {motherboard.get('model','?')}",
                "chassis": motherboard.get("chassis_type"),
            },
        },
        "smbios": smbios,
        "kexts": kexts,
        "boot_args": boot_args,
        "quirks": quirks,
        "ssdts": ssdts,
        "acpi_patches": [],  # binary ACPI renames — Phase 2 leaves empty
        "config_notes": notes,
        "blockers": blockers,
        "warnings": warnings + smbios_warnings,
    }
    return plan


# ─── Blocker checks ───────────────────────────────────────────────────────────

def _check_cpu_support(cpu: dict, blockers: list, notes: list) -> None:
    """Block if the CPU has no macOS support at all."""
    support = cpu.get("macos_support")
    if support == "none":
        blockers.append({
            "field": "cpu.macos_support",
            "reason": (
                f"CPU '{cpu.get('name','?')}' has no macOS support "
                f"({cpu.get('codename','?')} / {cpu.get('microarch','?')}). "
                "macOS cannot run on this processor."
            ),
        })
    elif support == "dropped":
        notes.append(
            f"CPU '{cpu.get('name','?')}' ({cpu.get('codename','?')}, gen {cpu.get('generation','?')}) "
            "was dropped from recent macOS. Targeting Ventura (macOS 13) as the "
            "latest installable version."
        )


def _check_gpu_support(gpus: list, blockers: list, notes: list) -> None:
    """Block only if a GPU has zero macOS support across ALL versions.

    A 'dropped' GPU (Skylake iGPU) still works on Ventura — so it's not a
    blocker, it just constrains the macOS target. Only 'none' (e.g. Nvidia
    Turing/Ampere) is a hard stop, because no macOS version has a driver.
    """
    if not gpus:
        blockers.append({
            "field": "gpu",
            "reason": "No GPU detected. Cannot configure display output.",
        })
        return

    # 'none' = no driver in any macOS version (Nvidia post-Kepler).
    truly_dead = [g for g in gpus if g.get("macos_support") == "none"]
    # 'dropped' = works on older targets, forces macOS downgrade.
    dropped = [g for g in gpus if g.get("macos_support") == "dropped"]
    usable = [g for g in gpus if g.get("macos_support") in ("full", "partial", "native")]

    # If every GPU is truly dead, there's no display path at all.
    if truly_dead and not usable and not dropped:
        worst = truly_dead[0]
        blockers.append({
            "field": "gpu.macos_support",
            "reason": (
                f"GPU '{worst.get('name','?')}' ({worst.get('pci_id','?')}) has no macOS support. "
                f"{worst.get('gpu_gen','')} — no driver exists in any macOS version."
            ),
        })
    # If the only usable GPUs are 'dropped', we can still proceed but must
    # target an older macOS (handled by _resolve_macos_target).
    for g in dropped:
        notes.append(
            f"GPU '{g.get('name','?')}' was dropped from recent macOS — "
            "target will be constrained to Ventura (macOS 13)."
        )
    for g in truly_dead:
        notes.append(
            f"GPU '{g.get('name','?')}' is unsupported in macOS — "
            "it will be ignored; relying on other GPU(s)."
        )


# ─── macOS target resolution ──────────────────────────────────────────────────

def _resolve_macos_target(requested: str, cpu: dict, notes: list) -> str:
    """Resolve the macOS target, respecting CPU drop history."""
    matrix = _load("compat_matrix.json")
    if requested not in ("auto",):
        if requested not in matrix["macos_targets"]:
            raise Blocker(
                field="macos_target",
                reason=f"Unknown macOS target '{requested}'. Use: ventura, sonoma, sequoia.",
            )
        return requested

    support = cpu.get("macos_support")
    if support == "dropped":
        return "ventura"  # last version supporting Skylake/Kaby Lake
    if support == "partial":
        return "sonoma"
    return "sequoia"


# ─── Quirk selection ──────────────────────────────────────────────────────────

def _select_quirks(cpu: dict, notes: list) -> dict:
    """Pick Kernel + Booter quirks by CPU microarchitecture."""
    matrix = _load("compat_matrix.json")
    vendor = (cpu.get("vendor") or "").lower()
    microarch = cpu.get("microarch", "")

    # Kernel quirks: look up by microarch (skylake, zen3, alder_lake, etc.)
    kq_table = matrix.get("kernel_quirks_by_microarch", {}).get(vendor, {})
    kernel_quirks = dict(kq_table.get(microarch, {
        # Safe defaults if the microarch isn't in the table yet.
        "AppleXcpmExtraMsrs": False, "AppleCpuPmCfgLock": False, "AppleXcpmCfgLock": False,
    }))
    # Universal kernel quirks.
    kernel_quirks.update({
        "DisableIoMapper": vendor == "amd",
        "PanicNoKextDump": True,
        "PowerTimeoutKernelPanic": True,
    })
    notes.append(
        f"Kernel quirks for {vendor}/{microarch}: "
        f"AppleXcpmCfgLock={kernel_quirks.get('AppleXcpmCfgLock')}, "
        f"DisableIoMapper={kernel_quirks.get('DisableIoMapper')}."
    )

    # Booter quirks: vendor-level only.
    bq_table = matrix.get("booter_quirks_by_cpu", {}).get(vendor, {})
    booter_quirks = {k: v for k, v in bq_table.items() if not k.startswith("_")}
    notes.append(f"Booter quirks: {len(booter_quirks)} entries for {vendor}.")

    return {
        "Kernel": kernel_quirks,
        "Booter": booter_quirks,
        "UEFI": {"ConnectDrivers": True},
    }


# ─── Boot-args ────────────────────────────────────────────────────────────────

def _build_boot_args(gpus: list, cpu: dict, notes: list) -> dict:
    """Assemble boot-args from GPU type + CPU."""
    matrix = _load("compat_matrix.json")
    args_table = matrix.get("boot_args_by_gpu", {})

    gpu_args: list[str] = []
    for gpu in gpus:
        vendor = (gpu.get("vendor") or "").lower()
        gpu_gen = (gpu.get("gpu_gen") or "").lower()
        support = gpu.get("macos_support")

        if vendor == "intel" and support in ("full", "partial", "dropped"):
            # Map GPU gen to the microarch key.
            for key in ("skylake", "kaby_lake", "coffee_lake", "comet_lake", "alder_lake"):
                if key in gpu_gen.replace(" gt2", "").replace(" gt1", "").replace(" ", "_"):
                    val = args_table.get("intel_igpu", {}).get(key, "")
                    if val and val not in gpu_args:
                        gpu_args.append(val)
                    break
        elif vendor == "amd":
            gen = gpu.get("gpu_gen", "")
            pikera = "agdpmod=pikera"
            if "Navi 3" in gen or "Navi 21" in gen or "Navi 22" in gen or "Navi 23" in gen or "Navi 31" in gen or "Navi 32" in gen or "Navi 33" in gen or "Navi 10" in gen or "Navi 14" in gen:
                if pikera not in gpu_args:
                    gpu_args.append(args_table.get("amd_navi", pikera))
            elif "Polaris" in gen or "Vega" in gen:
                if pikera not in gpu_args:
                    gpu_args.append(args_table.get("amd_polaris", pikera))

    debug = "-v keepsyms=1 debug=0x100"
    release = ("-v " + " ".join(gpu_args)).strip()

    if gpu_args:
        notes.append(f"GPU boot-args: {' '.join(gpu_args)} (applied via WhateverGreen).")

    return {
        "debug": debug,
        "release": release,
        "active": "debug",  # start in debug mode — user switches after first boot
    }


# ─── SMBIOS ───────────────────────────────────────────────────────────────────

def _generate_smbios(cpu: dict, motherboard: dict, notes: list) -> tuple[dict, list]:
    """Generate the SMBIOS values, returning (smbios_dict, warnings)."""
    warnings: list[dict] = []
    model = smbios_gen.select_model(cpu, motherboard)
    if not model:
        warnings.append({
            "field": "smbios.model",
            "reason": (
                f"No SMBIOS model rule for {cpu.get('vendor','?')} "
                f"gen {cpu.get('generation','?')} {motherboard.get('chassis_type','?')}. "
                "Using iMacPro1,1 as a safe fallback."
            ),
        })
        model = "iMacPro1,1"
    smbios = smbios_gen.generate(model)
    notes.append(
        f"SMBIOS model: {model} (board {smbios['board_model']}). "
        "Serial/MLB are format-valid but NOT verified against Apple's database."
    )
    warnings.append({
        "field": "smbios.serial",
        "reason": (
            "Generated serial is format-valid but may collide with a real Mac. "
            "Verify at https://checkcoverage.apple.com before iServices setup — "
            "it should return 'invalid' (meaning unused)."
        ),
    })
    return smbios, warnings


# ─── Warnings ─────────────────────────────────────────────────────────────────

def _collect_warnings(memory: dict, wireless: dict, profile: dict, warnings: list) -> None:
    """Collect non-blocking warnings from undetected/soft fields."""
    if not memory.get("type"):
        warnings.append({
            "field": "memory.type",
            "reason": "Memory type/speed undetected (scanner needs root). SMBIOS unaffected.",
            "needs_root": True,
        })
    if wireless.get("wifi_support") == "partial":
        warnings.append({
            "field": "wireless.wifi",
            "reason": "Intel WiFi has only partial macOS support (no AirDrop, limited handoff).",
        })


__all__ = ["build_plan"]
