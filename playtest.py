#!/usr/bin/env python3.11
"""Trial-play entry point: find the fastest feed that sounds every strike.

Usage:
    python3.11 playtest.py --case case.json
    python3.11 playtest.py --plate-file out.json --bench-file bench.json
    python3.11 playtest.py --tracks T=10101 --heads T:C:0 \
        --cooldown C=3 --fast 1 --slow 2 --max-changes 1
    cat play.json | python3.11 playtest.py --play-file -   # read a platemaker dump
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from musicbox.cli import run_case_command, run_play_command  # noqa: E402

PLATE_KEYS = ("columns", "tracks", "patches", "heads")


def _plate_part(loaded):
    """Pull just the plate-object fields out of a raw plate or a dump."""
    loaded = loaded.get("plate", loaded)
    if not isinstance(loaded, dict):
        return loaded
    return {k: loaded[k] for k in PLATE_KEYS if k in loaded}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Find the fastest fast/slow feed so every strike sounds."
    )
    parser.add_argument("--case", help="run the whole case.json benchmark")
    parser.add_argument("--plate-file", help="JSON plate object (or platemaker dump)")
    parser.add_argument("--play-file", help="JSON platemaker dump (may be '-')")
    parser.add_argument("--bench-file", help="JSON bench object")
    parser.add_argument("--tracks", action="append", default=[], metavar="NAME=BITS")
    parser.add_argument("--heads", action="append", default=[], metavar="TRACK:TOOTH:OFFSET")
    parser.add_argument("--patch", action="append", default=[], metavar="TRACK:START:BITS")
    parser.add_argument("--cooldown", action="append", default=[], metavar="TOOTH=N")
    parser.add_argument("--fast", type=int)
    parser.add_argument("--slow", type=int)
    parser.add_argument("--max-changes", type=int)
    args = parser.parse_args(argv)

    if args.case:
        return run_case_command(args.case)

    plate_spec = {}
    bench_spec = {}
    if args.play_file:
        stream = sys.stdin if args.play_file == "-" else open(args.play_file, "r", encoding="utf-8")
        with stream:
            dumped = json.load(stream)
        plate_spec = _plate_part(dumped)
        if isinstance(dumped.get("bench"), dict):
            bench_spec.update(dumped["bench"])
    if args.plate_file:
        with open(args.plate_file, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        plate_spec = _plate_part(loaded)
        if isinstance(loaded.get("bench"), dict):
            bench_spec.update(loaded["bench"])
    if args.bench_file:
        with open(args.bench_file, "r", encoding="utf-8") as fh:
            bench_spec.update(json.load(fh))
    if args.tracks:
        tracks = {}
        for spec in args.tracks:
            name, sep, bits = spec.partition("=")
            if not sep or not name:
                parser.error(f"bad --tracks value {spec!r}")
            tracks[name] = bits
        plate_spec["tracks"] = tracks
    if args.heads:
        heads = []
        for spec in args.heads:
            parts = spec.split(":")
            if len(parts) != 3 or not parts[2].isdigit():
                parser.error(f"bad --heads value {spec!r}")
            heads.append({"track": parts[0], "tooth": parts[1], "offset": int(parts[2])})
        plate_spec["heads"] = heads
    if args.patch:
        patches = []
        for spec in args.patch:
            parts = spec.split(":")
            if len(parts) != 3 or not parts[1].isdigit():
                parser.error(f"bad --patch value {spec!r}")
            patches.append({"track": parts[0], "start": int(parts[1]), "bits": parts[2]})
        plate_spec["patches"] = patches
    if args.cooldown:
        cooldown = {}
        for spec in args.cooldown:
            tooth, sep, value = spec.partition("=")
            if not sep or not tooth or not value.isdigit():
                parser.error(f"bad --cooldown value {spec!r}; expected TOOTH=N")
            cooldown[tooth] = int(value)
        bench_spec["cooldown"] = cooldown
    if args.fast is not None:
        bench_spec["fast"] = args.fast
    if args.slow is not None:
        bench_spec["slow"] = args.slow
    if args.max_changes is not None:
        bench_spec["max_changes"] = args.max_changes

    if not plate_spec or "fast" not in bench_spec or "slow" not in bench_spec:
        parser.error(
            "need a plate (--case/--play-file/--plate-file/--tracks) and a bench "
            "(bench with fast+slow via --bench-file or --fast/--slow)"
        )
    return run_play_command(plate_spec, bench_spec)


if __name__ == "__main__":
    raise SystemExit(main())
