"""Shared command-line plumbing for the platemaker and playtest entry points."""

from __future__ import annotations

import json
import sys
from typing import Mapping

from .case import build_variants, run_variant
from .model import BenchError, PlateError, build_plate, parse_bench
from .solver import solve


def _emit(payload) -> None:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def run_plate_command(plate_spec: Mapping) -> int:
    """Build/patch a plate and print its tracks, left edges and strike list."""
    try:
        plate = build_plate(plate_spec)
    except (PlateError, BenchError) as exc:
        _emit({"ok": False, "error": str(exc)})
        return 2
    payload = plate.as_dict()
    payload["ok"] = True
    _emit(payload)
    return 0


def run_play_command(plate_spec: Mapping, bench_spec: Mapping) -> int:
    """Solve one plate + bench and print the fastest feed and audit trail."""
    try:
        plate = build_plate(plate_spec)
        bench = parse_bench(bench_spec)
        result = solve(plate, bench)
    except (PlateError, BenchError, ValueError) as exc:
        _emit({"ok": False, "error": str(exc)})
        return 2
    payload = {
        "ok": True,
        "plate": {
            "columns": plate.columns,
            "tracks": plate.tracks,
            "K": plate.K,
            "play": [e.as_dict() for e in plate.play_events()],
        },
        "bench": {
            "cooldown": dict(bench.cooldown),
            "fast": bench.fast,
            "slow": bench.slow,
            "max_changes": bench.max_changes,
        },
        "solve": result.as_dict(),
    }
    _emit(payload)
    return 0 if result.solved else 1


def run_case_command(case_path) -> int:
    """Run the baseline and every change variant, then print a compact digest."""
    from .case import load_case

    case = load_case(case_path)
    variants = build_variants(case)
    rows = []
    for index, variant in enumerate(variants):
        try:
            outcome = run_variant(variant["case"])
        except (PlateError, BenchError, ValueError) as exc:
            rows.append(
                {
                    "name": variant["name"],
                    "ok": False,
                    "error": str(exc),
                    "index": index,
                }
            )
            continue
        info = outcome["solve"]
        rows.append(
            {
                "name": variant["name"],
                "index": index,
                "ok": True,
                "tracks": outcome["plate"]["tracks"],
                "patch_error": outcome["plate"].get("patch_error"),
                "K": outcome["plate"]["K"],
                "play": outcome["plate"]["play"],
                "contributions": outcome["plate"]["contributions"],
                "min_total": info["total_time"] if info["solved"] else None,
                "solved": info["solved"],
                "reason": info["reason"],
                "start": info["start"],
                "steps": info["steps"],
                "changes": info["changes_used"],
                "max_changes": info["max_changes"],
                "events": info["events"],
            }
        )
    payload = {"ok": all(r.get("ok") for r in rows), "variants": rows}
    _emit(payload)
    return 0 if payload["ok"] else 1
