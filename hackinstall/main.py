#!/usr/bin/env python3
"""HackInstall CLI entry point.

Phase 1 commands::

    python -m hackinstall --scan                 # scan + print summary
    python -m hackinstall --scan --output p.json # also write JSON profile
    python -m hackinstall --scan --verbose       # show warnings + tracebacks
    python -m hackinstall --schema               # print the profile schema doc

The summary is a compact human-readable report. The JSON profile is the
contract Phase 2 consumes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .scanners import get_scanner, UnsupportedPlatformError

# ANSI colors — degrade gracefully if not a TTY
_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def _green(t: str) -> str:  return _c("32", t)
def _red(t: str) -> str:    return _c("31", t)
def _amber(t: str) -> str:  return _c("33", t)
def _cyan(t: str) -> str:   return _c("36", t)
def _dim(t: str) -> str:    return _c("2;37", t)
def _bold(t: str) -> str:   return _c("1", t)


def print_summary(profile: dict, verbose: bool = False) -> None:
    """Human-readable scan report."""
    meta = profile.get("scan_metadata", {})
    cpu = profile.get("cpu", {}) or {}
    mobo = profile.get("motherboard", {}) or {}
    gpus = profile.get("gpu", []) or []
    audio = profile.get("audio", {}) or {}
    mem = profile.get("memory", {}) or {}
    warnings = profile.get("warnings", []) or []

    print()
    print(_bold(_violet("  HACKINSTALL") + _dim(f"  v{meta.get('scanner_version','?')}") +
                _dim(f"  ·  {meta.get('host_os','?')}  ·  {meta.get('timestamp','?')}")))
    print(_dim("  " + "─" * 62))

    # CPU
    gen = f" Gen {cpu.get('generation')}" if cpu.get("generation") else ""
    codename = f" ({cpu.get('codename')})" if cpu.get("codename") else ""
    support = _support_badge(cpu.get("macos_support"))
    print(f"  {_bold('CPU')}     {cpu.get('name','?')}{codename}{gen}")
    print(f"          {cpu.get('cores','?')} cores / {cpu.get('threads','?')} threads  ·  "
          f"{cpu.get('vendor','?')}  ·  macOS support: {support}")

    # Motherboard
    print(f"  {_bold('BOARD')}   {mobo.get('vendor','?')} {mobo.get('model','?')}  "
          f"[{mobo.get('chassis_type','?')}]")
    if mobo.get("chipset"):
        print(f"          chipset: {mobo.get('chipset')}  ·  BIOS {mobo.get('bios_version','?')}")

    # GPUs
    for i, gpu in enumerate(gpus):
        label = "GPU" if len(gpus) == 1 else f"GPU[{i}]"
        gsup = _support_badge(gpu.get("macos_support"))
        print(f"  {_bold(label)}    {gpu.get('name','?')}  [{gpu.get('pci_id','—')}]  ·  {gsup}")
        if gpu.get("needs_patch"):
            print(_amber(f"          ⚠ needs patch: {gpu.get('patch_note','see notes')}"))

    # Audio
    if audio.get("codec"):
        lay = audio.get("layout_id")
        lay_s = f"layout-id {lay}" if lay else _amber("no layout-id (manual)")
        print(f"  {_bold('AUDIO')}   {audio['codec']}  [{audio.get('codec_id','—')}]  ·  {lay_s}")
    else:
        print(f"  {_bold('AUDIO')}   {_dim('not detected')}")

    # Network
    for eth in (profile.get("ethernet", []) or []):
        print(f"  {_bold('ETH')}     {eth.get('name','?')}  [{eth.get('pci_id','—')}]  ·  "
              f"{eth.get('kext','?')}")
    wl = profile.get("wireless", {}) or {}
    if wl.get("wifi_chip"):
        print(f"  {_bold('WIFI')}    {wl['wifi_chip']}  [{wl.get('wifi_pci_id','—')}]  ·  "
              f"{_support_badge(wl.get('wifi_support'))}")
    if wl.get("bluetooth_chip"):
        print(f"  {_bold('BT')}      {wl['bluetooth_chip']}  [{wl.get('bt_usb_id','—')}]")

    # Storage
    for d in (profile.get("storage", []) or []):
        rot = "HDD" if d.get("rotational") else "SSD"
        print(f"  {_bold('DISK')}    {d.get('name','?')}  ·  {d.get('size_gb','?')}GB  ·  "
              f"{d.get('type','?')} {rot}")

    # Memory
    if mem.get("total_gb"):
        extra = ""
        if mem.get("type"):
            extra = f"  ·  {mem['type']}"
        if mem.get("speed_mhz"):
            extra += f" @ {mem['speed_mhz']}MT/s"
        print(f"  {_bold('RAM')}     {mem['total_gb']}GB{extra}")

    # USB controllers
    usbs = profile.get("usb_controllers", []) or []
    if usbs:
        print(f"  {_bold('USB')}     {len(usbs)} controller(s) · USB map required")

    # SMBIOS hint
    hint = profile.get("smbios_hint")
    if hint:
        print(f"  {_bold('SMBIOS')}  target hint: {_cyan(hint)}  "
              f"{_dim('(Phase 2 refines)')}")

    # Warnings
    print(_dim("  " + "─" * 62))
    if not warnings:
        print(f"  {_green('✓')} No warnings — full detection.")
    else:
        errs = [w for w in warnings if w["severity"] == "error"]
        warns = [w for w in warnings if w["severity"] == "warn"]
        infos = [w for w in warnings if w["severity"] == "info"]
        print(f"  {_amber('⚠')} {len(warns)} warning(s), {len(errs)} error(s), {len(infos)} info")
        for w in warnings:
            icon = {"error": _red("✗"), "warn": _amber("⚠"), "info": _cyan("ℹ")}[w["severity"]]
            root = _dim(" [needs root]") if w.get("needs_root") else ""
            print(f"    {icon} {w['field']}: {w['message']}{root}")

    if verbose and hasattr(get_scanner, "_last_traceback"):
        pass  # tracebacks handled in scan()
    print()


def _support_badge(level: str | None) -> str:
    if not level:
        return _dim("?")
    styles = {
        "full":    _green("FULL"),
        "partial": _amber("PARTIAL"),
        "native":  _green("NATIVE"),
        "none":    _red("NONE"),
        "dropped": _red("DROPPED"),
        "unknown": _dim("UNKNOWN"),
    }
    return styles.get(level, level)


def _violet(t: str) -> str:
    return _c("35", t)


def cmd_scan(args: argparse.Namespace) -> int:
    try:
        scanner = get_scanner()
    except UnsupportedPlatformError as exc:
        print(_red(f"✗ {exc}"), file=sys.stderr)
        return 2

    print(_dim(f"  → Scanning hardware on {scanner.__class__.__name__}..."))
    try:
        profile = scanner.scan()
    except NotImplementedError as exc:
        print(_red(f"✗ {exc}"), file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(_red(f"✗ Scan failed: {exc}"), file=sys.stderr)
        if args.verbose and hasattr(scanner, "_last_traceback"):
            print(_dim(getattr(scanner, "_last_traceback", "")), file=sys.stderr)
        return 1

    print_summary(profile, verbose=args.verbose)

    if args.output:
        out = Path(args.output)
        with out.open("w", encoding="utf-8") as fh:
            json.dump(profile, fh, indent=2, ensure_ascii=False)
        print(_green(f"  ✓ Wrote {out}"))
        # Root note
        if profile.get("scan_metadata", {}).get("used_root"):
            print(_dim("    (root tools were used for some fields)"))
        else:
            needs_root = [w for w in profile.get("warnings", []) if w.get("needs_root")]
            if needs_root:
                print(_amber(f"    Re-run as root for {len(needs_root)} more field(s)."))

    return 0


def cmd_schema(_: argparse.Namespace) -> int:
    schema_path = Path(__file__).resolve().parent / "SCHEMA.md"
    print(schema_path.read_text(encoding="utf-8"))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate an EFI config from a hardware_profile.json."""
    # Lazy import so 'scan'/'schema' don't pull in the Phase 2 chain.
    from .core import efi_builder
    from .core.exceptions import Blocker

    profile_path = Path(args.profile)
    if not profile_path.exists():
        print(_red(f"✗ Hardware profile not found: {profile_path}"), file=sys.stderr)
        print(_dim("    Run `hackinstall scan --output hardware_profile.json` first."),
              file=sys.stderr)
        return 2

    try:
        with profile_path.open(encoding="utf-8") as fh:
            profile = json.load(fh)
    except json.JSONDecodeError as exc:
        print(_red(f"✗ Invalid JSON in {profile_path}: {exc}"), file=sys.stderr)
        return 2

    out_dir = Path(args.output)
    print(_dim(f"  → Generating EFI from {profile_path.name} "
               f"(target: {args.macos}) → {out_dir}/"))

    try:
        result = efi_builder.build_efi(
            profile, out_dir, macos_target=args.macos
        )
    except Blocker as exc:
        print(_red(f"✗ Blocked: {exc}"), file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(_red(f"✗ Generation failed: {exc}"), file=sys.stderr)
        if args.verbose:
            import traceback
            print(_dim(traceback.format_exc()), file=sys.stderr)
        return 1

    # Report blockers discovered inside the plan (non-raising path).
    if result.blockers:
        print(_red(f"\n  ✗ {len(result.blockers)} blocker(s) — EFI not generated:"))
        for b in result.blockers:
            print(_red(f"    [{b.get('field','?')}] {b.get('reason','?')}"))
        print(_dim(f"\n  See {result.plan_path} for the full decision log."))
        return 3

    # Success report.
    print(_build_summary_box(result))
    print(_green(f"  ✓ Wrote {result.config_path.name} "
                 f"({result.config_path.stat().st_size} bytes)"))
    print(_green(f"  ✓ Wrote {result.plan_path.name} (decision log)"))
    print(_green(f"  ✓ Scaffolded {result.efi_dir}/OC/{{ACPI,Drivers,Kexts,Tools}}/"))

    if result.warnings:
        print(_amber(f"\n  ⚠ {len(result.warnings)} warning(s):"))
        for w in result.warnings:
            root = _dim(" [needs root]") if w.get("needs_root") else ""
            print(_amber(f"    {w.get('field','?')}: {w.get('reason','?')}{root}"))

    print(_dim(f"\n  Next: Phase 3 will download OpenCore + kexts into {result.efi_dir}/"))
    return 0


def _build_summary_box(result) -> str:
    """Compact human-readable summary of the generated EFI."""
    try:
        plan = json.loads(result.plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    meta = plan.get("plan_metadata", {})
    hw = meta.get("hardware_summary", {})
    smbios = plan.get("smbios", {})
    boot_args = plan.get("boot_args", {})

    lines = [
        "",
        _bold(_violet("  HACKINSTALL") + _dim(f"  EFI generation · {meta.get('timestamp','?')}")),
        _dim("  " + "─" * 62),
        f"  {_bold('TARGET')}  macOS {meta.get('macos_target','?')}  ·  "
        f"OpenCore {meta.get('opencore_version','?')}",
        f"  {_bold('CPU')}     {hw.get('cpu','?')} ({hw.get('cpu_codename','?')})",
        f"  {_bold('GPU')}     {', '.join(hw.get('gpus', []) or ['?'])}",
        f"  {_bold('SMBIOS')}  {smbios.get('system_product_name','?')}  "
        + _dim(f"(serial {smbios.get('system_serial','?')[:4]}…)"),
        f"  {_bold('BOOT')}    {boot_args.get(boot_args.get('active', 'debug'), '-v')}",
        f"  {_bold('KEXTS')}   {result.kext_count} kext(s)  ·  "
        f"{_bold('SSDTs')} {result.ssdt_count} ssdt(s)",
        _dim("  " + "─" * 62),
    ]
    return "\n".join(lines)


def cmd_gui(_: argparse.Namespace) -> int:
    """Launch the Flet GUI."""
    try:
        from .gui import run as run_gui
    except ImportError as exc:
        print(_red(f"✗ GUI not available: {exc}"), file=sys.stderr)
        print(_dim("    Install with: pip install flet"), file=sys.stderr)
        return 2
    run_gui()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hackinstall",
        description="HackInstall — one-click macOS-on-PC. Phase 1: scan. Phase 2: generate EFI.",
    )
    p.add_argument("--version", action="version", version=f"hackinstall {__version__}")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("scan", help="Scan hardware and print a summary")
    s.add_argument("-o", "--output", metavar="FILE",
                   help="Write the full hardware_profile.json to FILE")
    s.add_argument("-v", "--verbose", action="store_true",
                   help="Show warning details and tracebacks on failure")
    s.set_defaults(func=cmd_scan)

    g = sub.add_parser("generate",
                       help="Generate an OpenCore EFI from a hardware_profile.json")
    g.add_argument("profile", metavar="PROFILE",
                   help="Path to hardware_profile.json (from `hackinstall scan`)")
    g.add_argument("-o", "--output", metavar="DIR", default="efi_output",
                   help="Output directory for config.plist + EFI/ (default: efi_output)")
    g.add_argument("--macos", default="auto",
                   choices=["auto", "ventura", "sonoma", "sequoia"],
                   help="macOS target version (default: auto-detect from CPU)")
    g.add_argument("-v", "--verbose", action="store_true",
                   help="Show tracebacks on failure")
    g.set_defaults(func=cmd_generate)

    sch = sub.add_parser("schema", help="Print the hardware_profile.json schema doc")
    sch.set_defaults(func=cmd_schema)

    ui = sub.add_parser("gui", help="Launch the graphical interface")
    ui.set_defaults(func=cmd_gui)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    # Default to 'scan' if no subcommand is given (friendly UX).
    raw = argv if argv is not None else sys.argv[1:]
    if not raw or raw[0].startswith("-"):
        raw = ["scan", *raw]
    args = parser.parse_args(raw)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
