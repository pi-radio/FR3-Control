"""Where measurement results live, so every script agrees.

    results/
        unit_005/                  everything measured on the board with serial 5
            20260923_182716_lo12_if2_upper_bypass_span1MHz_att35/
                power_sweep.csv, tones.csv, metadata.json, <plots>.png
            power_sweeps_upper_and_lower_....png        (figures built from several runs)
        unit_006/ ...
        instrument_checks/         FieldFox-only tests (no board involved)

The unit folder name is the board's own serial number (GET BOARD SERIAL),
read from the board at measurement time, so data from different units can
never be mixed up by accident, and post-processing across units is just a
walk over results/unit_*/*/. Each run's metadata.json also records
"unit_serial"."""

from __future__ import annotations

import re
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"
INSTRUMENT_CHECKS_DIR = RESULTS_DIR / "instrument_checks"

_UNIT_RE = re.compile(r"^unit_(\d+)$")


def unit_dir(serial: int) -> Path:
    return RESULTS_DIR / f"unit_{serial:03d}"


def unit_of(path: Path) -> int | None:
    """Serial of the unit folder that contains this path, or None."""
    for part in path.resolve().parts:
        m = _UNIT_RE.match(part)
        if m:
            return int(m.group(1))
    return None


def unit_dirs() -> list[Path]:
    return sorted(d for d in RESULTS_DIR.glob("unit_*") if d.is_dir() and _UNIT_RE.match(d.name))


def sweep_runs(unit: int | None = None) -> list[Path]:
    """Run folders that contain a finished power sweep, oldest first (run
    folder names start with their timestamp). All units, or just one."""
    dirs = unit_dirs() if unit is None else [unit_dir(unit)]
    runs = [r for d in dirs if d.exists() for r in d.iterdir()
            if r.is_dir() and (r / "power_sweep.csv").exists() and (r / "metadata.json").exists()]
    return sorted(runs, key=lambda r: r.name)
