"""EFI builder — top-level orchestrator that writes the whole EFI/ tree.

Given a hardware profile, this module:
  1. Runs the decision engine → BuildPlan.
  2. Saves the BuildPlan as build_plan.json (inspectable before flashing).
  3. Generates config.plist.
  4. Scaffolds the EFI/OC directory structure (ACPI, Drivers, Kexts, Tools).
  5. Writes a README into the output folder explaining every file.

Phase 3 fills the binary files (kexts, SSDTs, OpenCore.efi) via the
downloader. Phase 2 produces the structure + config.plist + plan — everything
that's deterministic and inspectable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import decisions
from .config_generator import write_config_plist
from .exceptions import Blocker


@dataclass
class BuildResult:
    """What the EFI builder produced — returned to the CLI for display."""
    output_dir: Path
    plan_path: Path
    config_path: Path
    efi_dir: Path
    blockers: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    kext_count: int = 0
    ssdt_count: int = 0


def build_efi(
    profile: dict,
    output_dir: Path | str,
    *,
    macos_target: str = "auto",
) -> BuildResult:
    """Generate the full EFI structure from a hardware profile.

    Args:
        profile: hardware_profile.json dict from Phase 1.
        output_dir: where to write EFI/ + build_plan.json.
        macos_target: 'auto' or 'ventura'/'sonoma'/'sequoia'.

    Returns a BuildResult describing what was written. If blockers exist,
    config.plist is NOT written (but build_plan.json is, so the user can see
    why generation stopped).
    """
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # 1. Decision engine → BuildPlan
    plan = decisions.build_plan(profile, macos_target=macos_target)

    # 2. Save the BuildPlan (always — even on blocker, so it's inspectable)
    plan_path = out / "build_plan.json"
    with plan_path.open("w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2, ensure_ascii=False)

    result = BuildResult(
        output_dir=out,
        plan_path=plan_path,
        config_path=out / "config.plist",  # may not exist if blocked
        efi_dir=out / "EFI",
        blockers=plan.get("blockers", []),
        warnings=plan.get("warnings", []),
        kext_count=len(plan.get("kexts", [])),
        ssdt_count=len(plan.get("ssdts", [])),
    )

    # 3. If blockers, stop here. Surface them to the caller.
    if plan.get("blockers"):
        return result

    # 4. Generate config.plist
    config_path = write_config_plist(plan, out / "config.plist")
    result.config_path = config_path

    # 5. Scaffold the EFI/OC directory structure
    _scaffold_efi_tree(out / "EFI", plan)

    # 6. Write a README explaining the output
    _write_readme(out, plan)

    return result


def _scaffold_efi_tree(efi_root: Path, plan: dict) -> None:
    """Create EFI/OC/{ACPI,Drivers,Kexts,Tools} + placeholder files.

    Phase 3 downloads the real binaries; here we create the structure and
    .keep files so the layout is visible. We also write a manifest of what
    each directory should contain.
    """
    oc = efi_root / "OC"
    for subdir in ("ACPI", "Drivers", "Kexts", "Tools"):
        d = oc / subdir
        d.mkdir(parents=True, exist_ok=True)

    # ACPI: list expected SSDT .aml files
    acpi_manifest = "# Expected ACPI files (download by Phase 3):\n"
    for s in plan.get("ssdts", []):
        acpi_manifest += f"# {s['name']}.aml  — {s.get('reason','')}\n"
    (oc / "ACPI" / "MANIFEST.txt").write_text(acpi_manifest)

    # Kexts: list expected kext bundles
    kexts_manifest = "# Expected kexts (download by Phase 3), in load order:\n"
    for k in plan.get("kexts", []):
        kexts_manifest += f"# {k['id']}.kext v{k.get('version','?')}  — {k.get('reason','')}\n"
    (oc / "Kexts" / "MANIFEST.txt").write_text(kexts_manifest)

    # Drivers: list expected UEFI drivers
    drivers_manifest = (
        "# Expected UEFI drivers (from OpenCorePkg):\n"
        "# OpenRuntime.efi   — required for OC quirks\n"
        "# OpenHfsPlus.efi   — HFS+ filesystem\n"
        "# ResetNvramEntry.efi — picker entry to reset NVRAM\n"
    )
    (oc / "Drivers" / "MANIFEST.txt").write_text(drivers_manifest)

    # Tools: empty for now
    (oc / "Tools" / ".keep").write_text("")

    # OpenCore.efi goes at EFI/OC/OpenCore.efi (Phase 3 download)
    (oc / "OPENCORE.txt").write_text(
        "# Place OpenCore.efi here (Phase 3 downloads from GitHub Releases).\n"
        f"# Target version: OpenCore {plan['plan_metadata']['opencore_version']}\n"
    )


def _write_readme(out: Path, plan: dict) -> None:
    """Write a human-readable explanation of the generated output."""
    meta = plan.get("plan_metadata", {})
    hw = meta.get("hardware_summary", {})
    smbios = plan.get("smbios", {})
    boot_args = plan.get("boot_args", {})

    lines = [
        f"# HackInstall EFI — generated {meta.get('timestamp','?')}",
        "",
        f"**macOS target:** {meta.get('macos_target','?')}",
        f"**OpenCore:** {meta.get('opencore_version','?')}",
        "",
        "## Hardware",
        f"- CPU: {hw.get('cpu','?')} ({hw.get('cpu_codename','?')}, gen {hw.get('cpu_microarch','?')})",
        f"- GPU(s): {', '.join(hw.get('gpus',[]) or ['?'])}",
        f"- Board: {hw.get('board','?')} [{hw.get('chassis','?')}]",
        "",
        "## SMBIOS",
        f"- Model: `{smbios.get('system_product_name','?')}`",
        f"- Serial: `{smbios.get('system_serial','?')}`",
        f"- MLB: `{smbios.get('mlb','?')}`",
        f"- UUID: `{smbios.get('system_uuid','?')}`",
        f"- ROM: `{smbios.get('rom','?')}`",
        "",
        "  ⚠ **Do NOT share these values publicly.** They are unique to this",
        "  machine. See config.plist → PlatformInfo → Generic.",
        "",
        "## Boot-args",
        f"- Active ({boot_args.get('active','debug')}): `{boot_args.get(boot_args.get('active','debug'),'-v')}`",
        f"- Debug: `{boot_args.get('debug','-v')}`",
        f"- Release: `{boot_args.get('release','-v')}`",
        "",
        "## Kexts (load order)",
    ]
    for k in plan.get("kexts", []):
        lines.append(f"- {k['id']}.kext v{k.get('version','?')} — {k.get('reason','')}")

    lines += [
        "",
        "## SSDTs",
    ]
    for s in plan.get("ssdts", []):
        lines.append(f"- {s['name']}.aml — {s.get('reason','')}")

    lines += [
        "",
        "## Files",
        "- `config.plist` — OpenCore configuration (the main output)",
        "- `build_plan.json` — full decision log (every value explained)",
        "- `EFI/OC/` — directory structure (Phase 3 fills binaries)",
        "",
        "## Next steps (Phase 3)",
        "1. Download OpenCore + kexts into `EFI/OC/`",
        "2. Compile/place SSDT .aml files in `EFI/OC/ACPI/`",
        "3. Copy `EFI/` to the USB drive's EFI partition",
        "4. Copy `config.plist` to `EFI/OC/config.plist`",
    ]

    if plan.get("warnings"):
        lines += ["", "## Warnings"]
        for w in plan["warnings"]:
            lines.append(f"- ⚠ {w.get('field','?')}: {w.get('reason','?')}")

    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")


__all__ = ["build_efi", "BuildResult"]
