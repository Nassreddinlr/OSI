"""SMBIOS serial / MLB / UUID / ROM generator.

A Python port of the GenSMBIOS logic. Generates statistically-valid SMBIOS
values that pass Apple's *format* checks:

  - system_serial  : 12 chars (4-char prefix from model table + 8 random)
  - mlb (board id) : 17 chars = system_serial + 5 random alphanumeric (uppercase)
  - system_uuid    : standard UUID v4, uppercased + hyphenated
  - rom            : 12 hex chars (6-byte MAC). Either a real NIC MAC or random.

NOTE on collision risk: these are *format-valid* but may collide with a real
Mac. GenSMBIOS has the same limitation. True uniqueness checking (querying
apple.com/coverage) is a Phase 3 concern — documented in the BuildPlan as a
warning. Users must NOT share generated values publicly.
"""
from __future__ import annotations

import random
import string
import uuid
from typing import Any

from ..data import _load
from .exceptions import BuildWarning

# GenSMBIOS uses this alphabet for the random portion of serials.
# Apple serials are alphanumeric uppercase, no vowels to avoid profanity,
# no 0/O/1/I ambiguity.
_SERIAL_ALPHABET = "0123456789ABCDEFGHJKLMNPQRSTVWXYZ"
_MLB_TAIL_ALPHABET = "0123456789ABCDEFGHJKLMNPQRSTVWXYZ"


def select_model(cpu: dict, motherboard: dict) -> str | None:
    """Pick the SMBIOS Mac model from the selection rules table.

    Returns the model identifier (e.g. ``"iMacPro1,1"``) or ``None`` if no
    rule matches — the caller records a blocker (unsupported CPU/chassis).
    """
    table = _load("smbios_models.json")
    vendor = (cpu.get("vendor") or "").lower()
    chassis = motherboard.get("chassis_type", "desktop")
    generation = cpu.get("generation")

    for rule in table["selection_rules"]:
        m = rule["match"]
        if m.get("vendor") != vendor:
            continue
        if m.get("chassis") != chassis:
            continue
        if "generation_gte" in m:
            if generation is None or generation < m["generation_gte"]:
                continue
        return rule["model"]
    return None


def generate(model: str, *, rom_mac: str | None = None) -> dict[str, Any]:
    """Generate a full SMBIOS value set for ``model``.

    Args:
        model: Mac model identifier (must exist in smbios_models.json).
        rom_mac: optional 12-hex MAC to use as ROM. If None, a random
                locally-administered MAC is generated.

    Returns a dict with: system_product_name, system_serial, mlb,
    system_uuid, rom, board_model, smc_platform. Raises ``BuildWarning`` if
    the model is unknown.
    """
    table = _load("smbios_models.json")
    entry = table["models"].get(model)
    if not entry:
        raise BuildWarning(
            field="smbios.model",
            reason=(
                f"Unknown SMBIOS model '{model}'. Add it to "
                "data/smbios_models.json or pick a supported model."
            ),
        )

    # 12-char system serial: 4-char model prefix + 8 random from alphabet.
    prefix = random.choice(entry["serial_prefix"])  # noqa: S311 — crypto not needed
    body = "".join(random.choices(_SERIAL_ALPHABET, k=8))  # noqa: S311
    system_serial = prefix + body

    # 17-char MLB = system_serial (12) + 5 random.
    mlb_tail = "".join(random.choices(_MLB_TAIL_ALPHABET, k=5))  # noqa: S311
    mlb = system_serial + mlb_tail

    # UUID v4, uppercased with hyphens (Apple's format).
    system_uuid = str(uuid.uuid4()).upper()

    # ROM: prefer a real NIC MAC, else random locally-administered.
    if rom_mac:
        rom = rom_mac.lower().replace(":", "")[:12].ljust(12, "0")
    else:
        # Locally-administered, unicast: second hex digit = 2, 6, A, or E.
        first = random.choice("26AE")  # noqa: S311
        rom = f"02{first}" + "".join(random.choices("0123456789ABCDEF", k=10))  # noqa: S311

    return {
        "system_product_name": model,
        "system_serial": system_serial,
        "mlb": mlb,
        "system_uuid": system_uuid,
        "rom": rom,
        "board_model": entry["board_model"],
        "smc_platform": entry["smc_platform"],
        "_note": (
            "Format-valid serials. NOT verified against Apple's database — "
            "rare collisions possible. See config_notes."
        ),
    }


__all__ = ["select_model", "generate"]
