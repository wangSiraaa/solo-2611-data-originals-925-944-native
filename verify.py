#!/usr/bin/env python3.11
"""Re-runnable verification for the music-box plate + bench tasks.

Run:  python3.11 verify.py [--case case.json] [--quick]

It checks, without trusting the solver's own claims:
  * the stated benchmark (baseline 7, patched 4, extra change 6);
  * patching semantics (order, later wins, out-of-range rejection);
  * left-edge -> tick mapping, K, and same-(tick,tooth) de-duplication;
  * the solver against an exhaustive brute force on many small random plates;
  * the cooldown "exactly equal is allowed" boundary;
  * the two extra demonstrations (two heads on one tooth, too-slow comb).
"""

from __future__ import annotations

import argparse
import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from musicbox.case import build_variants, check_case, load_case, run_variant  # noqa: E402
from musicbox.model import (  # noqa: E402
    BenchError,
    PlateError,
    build_plate,
    parse_bench,
    simulate,
)
from musicbox.solver import solve  # noqa: E402

import json  # noqa: E402

DEMOS = Path(__file__).resolve().parent / "demos"

FAILS = []


def check(cond, label, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(label)


# --------------------------------------------------------------------------
# 1. Benchmark
# --------------------------------------------------------------------------


def check_benchmark(case_path):
    case = load_case(case_path)
    variants = build_variants(case)
    results = {}
    for variant in variants:
        outcome = run_variant(variant["case"])
        results[variant["name"]] = outcome

    baseline = results["baseline"]
    check(
        baseline["plate"]["play"] == [{"time": 0, "tooth": "C"}, {"time": 2, "tooth": "C"}, {"time": 4, "tooth": "C"}],
        "baseline strike positions are 0, 2, 4",
        baseline["plate"]["play"],
    )
    check(baseline["solve"]["solved"] and baseline["solve"]["total_time"] == 7,
          "baseline minimum total time is 7", baseline["solve"]["total_time"])

    patched = results["change1:plate.patches"]
    check(patched["plate"]["tracks"] == {"T": "11101"},
          "patch fills column 1 and the merged run is 11101", patched["plate"]["tracks"])
    check(patched["plate"]["play"] == [{"time": 0, "tooth": "C"}, {"time": 4, "tooth": "C"}],
          "merged long hole strikes only at 0 and 4", patched["plate"]["play"])
    check(patched["solve"]["solved"] and patched["solve"]["total_time"] == 4,
          "patched minimum total time is 4", patched["solve"]["total_time"])

    more = results["change2:bench.max_changes"]
    check(more["plate"]["tracks"] == {"T": "10101"},
          "extra-change variant keeps the original tape", more["plate"]["tracks"])
    check(more["solve"]["solved"] and more["solve"]["total_time"] == 6,
          "extra change with original tape gives minimum 6", more["solve"]["total_time"])

    # The declarative expected-value gate used by the case runner.
    expected = {
        "baseline": 7,
        "change1:plate.patches": 4,
        "change2:bench.max_changes": 6,
    }
    report = check_case(case, expected)
    check(report["ok"], "declarative check_case agrees on all three variants",
          report["checks"])
    return results


# --------------------------------------------------------------------------
# 2. Patching semantics
# --------------------------------------------------------------------------


def check_patching():
    # Later patch wins.
    plate = build_plate({
        "tracks": {"T": "00000"},
        "patches": [
            {"track": "T", "start": 1, "bits": "11"},
            {"track": "T", "start": 2, "bits": "0"},
        ],
        "heads": [{"track": "T", "tooth": "C", "offset": 0}],
    })
    check(plate.tracks["T"] == "01000", "later patch overrides earlier at the same column", plate.tracks)
    check(plate.original_tracks["T"] == "00000", "original tape is retained", plate.original_tracks)

    # A patch fully overwriting a run leaves the earlier strike positions in the
    # audit trail; here the raw left edges come purely from the patched tape.
    check(plate.notes()["T"] == [1], "left edge recomputed after patching", plate.notes())

    # Out-of-range patches are rejected.
    for start, bits in [(-1, "1"), (4, "11"), (5, "1")]:
        try:
            build_plate({
                "tracks": {"T": "00000"},
                "patches": [{"track": "T", "start": start, "bits": bits}],
                "heads": [{"track": "T", "tooth": "C", "offset": 0}],
            })
        except PlateError:
            check(True, f"out-of-range patch start={start} bits={bits!r} rejected")
        else:
            check(False, f"out-of-range patch start={start} bits={bits!r} rejected")

    # Unknown track rejected.
    try:
        build_plate({
            "tracks": {"T": "000"},
            "patches": [{"track": "X", "start": 0, "bits": "1"}],
            "heads": [],
        })
    except PlateError:
        check(True, "patch on unknown track rejected")
    else:
        check(False, "patch on unknown track rejected")


# --------------------------------------------------------------------------
# 3. K, offsets, de-duplication
# --------------------------------------------------------------------------


def check_k_and_dedup():
    # Offset shifts a strike; K = last column + max offset even with no sound at K.
    plate = build_plate({
        "tracks": {"T": "10000"},
        "heads": [{"track": "T", "tooth": "C", "offset": 2}],
    })
    check(plate.K == 6, "K = last column (4) + max offset (2) = 6", plate.K)
    check([e.as_dict() for e in plate.play_events()] == [{"time": 2, "tooth": "C"}],
          "offset shifts the strike to tick 2")

    # Two heads, same tooth, same tick: one sound, both sources retained.
    plate = build_plate({
        "tracks": {"A": "10101", "B": "10101"},
        "heads": [
            {"track": "A", "tooth": "C", "offset": 0},
            {"track": "B", "tooth": "C", "offset": 0},
        ],
    })
    play = [e.as_dict() for e in plate.play_events()]
    check(play == [{"time": 0, "tooth": "C"}, {"time": 2, "tooth": "C"}, {"time": 4, "tooth": "C"}],
          "same-tooth simultaneous strikes collapse to one sound", play)
    contribs = plate.contributions()
    check(len(contribs) == 6, "both heads' strikes remain in the audit trail", len(contribs))
    check(all(c[1] == "C" for c in contribs), "all contributions keep the tooth label")

    # A distinct tooth at the same tick is a separate sound.
    plate = build_plate({
        "tracks": {"A": "1000", "B": "1000"},
        "heads": [
            {"track": "A", "tooth": "C", "offset": 0},
            {"track": "B", "tooth": "D", "offset": 0},
        ],
    })
    play = [e.as_dict() for e in plate.play_events()]
    check(play == [{"time": 0, "tooth": "C"}, {"time": 0, "tooth": "D"}],
          "different teeth at one tick stay separate", play)


# --------------------------------------------------------------------------
# 4. Cooldown boundary and change counting
# --------------------------------------------------------------------------


def check_bench_rules():
    plate = build_plate({
        "tracks": {"T": "101"},
        "heads": [{"track": "T", "tooth": "C", "offset": 0}],
    })
    events = plate.play_events()

    # Exactly equal to cooldown must sound.
    bench = parse_bench({"cooldown": {"C": 2}, "fast": 1, "slow": 2, "max_changes": 0})
    sim = simulate(plate.K, events, bench, [1, 1])
    check(sim["ok"] and sim["played"][1]["since_previous"] == 2,
          "interval exactly equal to cooldown is allowed", sim["played"])

    # One under is a miss.
    bench = parse_bench({"cooldown": {"C": 3}, "fast": 1, "slow": 2, "max_changes": 0})
    sim = simulate(plate.K, events, bench, [1, 1])
    check(not sim["ok"] and sim["missed"], "interval under cooldown is a miss", sim["missed"])

    # Change counting: adjacent equal lengths cost nothing; each switch costs one.
    bench = parse_bench({"cooldown": {}, "fast": 1, "slow": 2, "max_changes": 10})
    for steps, want in [([1, 1, 1], 0), ([1, 2, 2], 1), ([1, 2, 1], 2), ([2, 2, 1], 1)]:
        sim = simulate(len(steps), [], bench, steps)
        check(sim["changes"] == want, f"changes in {steps} == {want}", sim["changes"])

    # max_changes is enforced by the simulator.
    bench = parse_bench({"cooldown": {}, "fast": 1, "slow": 2, "max_changes": 1})
    try:
        simulate(3, [], bench, [1, 2, 1])
    except BenchError:
        check(True, "simulator rejects a feed beyond max_changes")
    else:
        check(False, "simulator rejects a feed beyond max_changes")


# --------------------------------------------------------------------------
# 5. Brute-force optimality cross-check
# --------------------------------------------------------------------------


def brute_force(plate, bench):
    """Exhaustively try every feed; return the min total or None."""
    K = plate.K
    events = plate.play_events()
    best = None
    for steps in itertools.product((bench.fast, bench.slow), repeat=K):
        try:
            sim = simulate(K, events, bench, steps)
        except BenchError:
            continue
        if sim["ok"] and (best is None or sim["total_time"] < best):
            best = sim["total_time"]
    return best


def rand_plate(rng):
    columns = rng.randint(1, 8)
    n_tracks = rng.randint(1, 3)
    tracks = {}
    for i in range(n_tracks):
        tracks[f"T{i}"] = "".join(rng.choice("01") for _ in range(columns))
    n_heads = rng.randint(1, 3)
    heads = []
    for _ in range(n_heads):
        heads.append(
            {
                "track": rng.choice(list(tracks)),
                "tooth": rng.choice("CDE"[: rng.randint(1, 3)]),
                "offset": rng.randint(0, 2),
            }
        )
    return {"tracks": tracks, "heads": heads}


def rand_bench(rng):
    fast = rng.randint(1, 2)
    slow = fast + rng.randint(1, 2)
    cooldown = {tooth: rng.randint(0, 6) for tooth in "CDE"}
    return {
        "cooldown": cooldown,
        "fast": fast,
        "slow": slow,
        "max_changes": rng.randint(0, 3),
    }


def check_bruteforce(trials, seed=1234):
    rng = random.Random(seed)
    mismatches = 0
    tested = 0
    for _ in range(trials):
        spec = rand_plate(rng)
        bench_spec = rand_bench(rng)
        plate = build_plate(spec)
        if plate.K > 12:  # keep brute force cheap
            continue
        bench = parse_bench(bench_spec)
        got = solve(plate, bench)
        want = brute_force(plate, bench)
        tested += 1
        got_time = got.total_time if got.solved else None
        if got_time != want:
            mismatches += 1
            print("  mismatch:", spec, bench_spec, "solver=", got_time, "brute=", want)
        elif got.solved:
            # The solver's own feed must reproduce the claimed total.
            sim = simulate(plate.K, plate.play_events(), bench, got.steps)
            if not sim["ok"] or sim["total_time"] != got.total_time:
                mismatches += 1
                print("  bad feed:", spec, bench_spec, got.steps, sim)
    check(mismatches == 0, f"solver matches brute force on {tested} random plates",
          f"{mismatches} mismatches")
    return tested


# --------------------------------------------------------------------------
# 6. Extra demonstrations from the brief
# --------------------------------------------------------------------------


def check_extra_demos():
    # (a) Two heads on the same tooth striking together.
    plate = build_plate({
        "tracks": {"A": "10101", "B": "10101"},
        "heads": [
            {"track": "A", "tooth": "C", "offset": 0},
            {"track": "B", "tooth": "C", "offset": 0},
        ],
    })
    bench = parse_bench({"cooldown": {"C": 3}, "fast": 1, "slow": 2, "max_changes": 1})
    res = solve(plate, bench)
    check(res.solved and res.total_time == 7,
          "two heads on one tooth: dedup keeps the baseline total 7", res.total_time)
    check(res.events and all(e["tooth"] == "C" for e in res.events),
          "two-head demo only sounds tooth C")
    check(len(plate.contributions()) == 6,
          "two-head demo records all six source strikes")

    # (b) A comb whose tooth rebounds too slowly for any feed to re-sound it.
    plate = build_plate({
        "tracks": {"T": "101"},
        "heads": [{"track": "T", "tooth": "C", "offset": 0}],
    })
    bench = parse_bench({"cooldown": {"C": 9}, "fast": 1, "slow": 2, "max_changes": 5})
    res = solve(plate, bench)
    check(not res.solved, "too-slow comb is reported unsolvable", res.reason)
    check(res.reason is not None and "no feed" in res.reason,
          "unsolvable result explains why", res.reason)
    check(brute_force(plate, bench) is None,
          "brute force agrees the too-slow comb has no feed")


# --------------------------------------------------------------------------


def check_demo_files():
    """The two extra demonstrations, exactly as delivered on disk."""
    with open(DEMOS / "two_heads_same_tooth.json", "r", encoding="utf-8") as fh:
        two = json.load(fh)
    plate = build_plate(two["plate"])
    bench = parse_bench(two["bench"])
    res = solve(plate, bench)
    check(res.solved and res.total_time == 7,
          "demo file: two heads share one tooth and still total 7", res.total_time)
    check(len(plate.contributions()) == 6 and len(plate.play_events()) == 3,
          "demo file: 6 source strikes collapse to 3 sounds",
          (len(plate.contributions()), len(plate.play_events())))

    with open(DEMOS / "slow_comb_unsolvable.json", "r", encoding="utf-8") as fh:
        slow = json.load(fh)
    plate = build_plate(slow["plate"])
    bench = parse_bench(slow["bench"])
    res = solve(plate, bench)
    check(not res.solved and brute_force(plate, bench) is None,
          "demo file: too-slow comb is unsolvable", res.reason)


# --------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify the music-box deliverables.")
    parser.add_argument("--case", default=str(Path(__file__).with_name("case.json")))
    parser.add_argument("--quick", action="store_true", help="fewer random trials")
    args = parser.parse_args(argv)

    check_benchmark(args.case)
    check_patching()
    check_k_and_dedup()
    check_bench_rules()
    check_bruteforce(200 if args.quick else 600)
    check_extra_demos()
    check_demo_files()

    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) FAILED:")
        for name in FAILS:
            print("  -", name)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
