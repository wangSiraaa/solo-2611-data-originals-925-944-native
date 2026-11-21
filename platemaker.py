#!/usr/bin/env python3.11
"""Platemaker entry point: patch a paper tape and list distinct tooth strikes.

Usage:
    python3.11 platemaker.py --tracks T=10101 --heads T:C:0
    python3.11 platemaker.py --plate-file plate.json
    python3.11 platemaker.py --case case.json          # prints the whole run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from musicbox.cli import run_plate_command, run_case_command  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Patch a music-box paper tape and list the distinct strikes."
    )
    parser.add_argument("--case", help="run the whole case.json benchmark")
    parser.add_argument("--plate-file", help="JSON file holding just a plate object")
    parser.add_argument(
        "--tracks",
        action="append",
        default=[],
        metavar="NAME=BITS",
        help="a track, e.g. T=10101 (repeat for several tracks)",
    )
    parser.add_argument(
        "--heads",
        action="append",
        default=[],
        metavar="TRACK:TOOTH:OFFSET",
        help="a read head, e.g. T:C:0 (repeat for several heads)",
    )
    parser.add_argument(
        "--patch",
        action="append",
        default=[],
        metavar="TRACK:START:BITS",
        help="a patch applied in the given order, e.g. T:1:1",
    )
    args = parser.parse_args(argv)

    if args.case:
        return run_case_command(args.case)

    if not args.tracks and not args.plate_file:
        parser.error("provide --case, --plate-file, or at least one --tracks/--heads")

    plate_spec = {}
    if args.plate_file:
        with open(args.plate_file, "r", encoding="utf-8") as fh:
            plate_spec = json.load(fh)
    if args.tracks:
        tracks = {}
        for spec in args.tracks:
            name, sep, bits = spec.partition("=")
            if not sep or not name:
                parser.error(f"bad --tracks value {spec!r}; expected NAME=BITS")
            tracks[name] = bits
        plate_spec["tracks"] = tracks
    if args.heads:
        heads = []
        for spec in args.heads:
            parts = spec.split(":")
            if len(parts) != 3:
                parser.error(f"bad --heads value {spec!r}; expected TRACK:TOOTH:OFFSET")
            track, tooth, offset = parts
            if not offset.isdigit():
                parser.error(f"bad offset in --heads value {spec!r}")
            heads.append({"track": track, "tooth": tooth, "offset": int(offset)})
        plate_spec["heads"] = heads
    if args.patch:
        patches = []
        for spec in args.patch:
            parts = spec.split(":")
            if len(parts) != 3 or not parts[1].isdigit():
                parser.error(f"bad --patch value {spec!r}; expected TRACK:START:BITS")
            patches.append({"track": parts[0], "start": int(parts[1]), "bits": parts[2]})
        plate_spec["patches"] = patches

    return run_plate_command(plate_spec)


if __name__ == "__main__":
    raise SystemExit(main())
