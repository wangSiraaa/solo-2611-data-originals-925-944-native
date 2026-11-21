"""Music-box paper-tape patching (platemaker) and trial-play (playtest)."""

from .model import (
    PlateError,
    BenchError,
    Patch,
    Plate,
    PlayEvent,
    Bench,
    parse_patch,
    build_plate,
    notes_from_rows,
    strip_thumps,
    parse_bench,
    simulate,
)
from .solver import solve, SolveResult
from .case import load_case, apply_change, build_variants, check_case

__all__ = [
    "PlateError",
    "BenchError",
    "Patch",
    "Plate",
    "PlayEvent",
    "Bench",
    "parse_patch",
    "build_plate",
    "notes_from_rows",
    "strip_thumps",
    "parse_bench",
    "simulate",
    "solve",
    "SolveResult",
    "load_case",
    "apply_change",
    "build_variants",
    "check_case",
]
