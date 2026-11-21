"""Load a ``case.json``, derive the baseline plus each change variant, and
produce a robot-checkable report.
"""

from __future__ import annotations

import copy
import json
from typing import Dict, List, Mapping

from .model import build_plate, parse_bench
from .solver import solve


def load_case(path) -> Dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def apply_change(case: Mapping, change: Mapping) -> Dict:
    """Return a fresh case with ``change['path']`` (dot path) replaced."""
    out = copy.deepcopy(dict(case))
    path = change.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("each change needs a non-empty 'path'")
    if "value" not in change:
        raise ValueError(f"change {path!r} needs a 'value'")
    parts = path.split(".")
    node = out
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"change path {path!r} does not exist")
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        raise KeyError(f"change path {path!r} does not exist")
    node[parts[-1]] = copy.deepcopy(change["value"])
    return out


def build_variants(case: Mapping) -> List[Dict]:
    """Baseline first, then one variant per change, each from the baseline."""
    variants = [{"name": "baseline", "case": copy.deepcopy(dict(case))}]
    for index, change in enumerate(case.get("changes", []), start=1):
        name = f"change{index}:{change.get('path')}"
        variants.append({"name": name, "case": apply_change(case, change)})
    return variants


def run_variant(case: Mapping) -> Dict:
    plate = build_plate(case["plate"])
    bench = parse_bench(case["bench"])
    result = solve(plate, bench)
    return {
        "plate": plate.as_dict(),
        "bench": {
            "cooldown": dict(bench.cooldown),
            "fast": bench.fast,
            "slow": bench.slow,
            "max_changes": bench.max_changes,
        },
        "solve": result.as_dict(),
    }


def check_case(case: Mapping, expected: Mapping) -> Dict:
    """Compare each named variant's minimum total time against ``expected``.

    ``expected`` maps a variant name to the asserted minimum total time (an
    integer) or ``None`` for "no feed exists".
    """
    checks = []
    ok_all = True
    for variant in build_variants(case):
        outcome = run_variant(variant["case"])
        solve_info = outcome["solve"]
        actual = solve_info["total_time"] if solve_info["solved"] else None
        name = variant["name"]
        if name in expected:
            want = expected[name]
            passed = actual == want
            ok_all = ok_all and passed
            checks.append(
                {
                    "variant": name,
                    "expected_min_total": want,
                    "actual_min_total": actual,
                    "solved": solve_info["solved"],
                    "passed": passed,
                }
            )
        else:
            checks.append(
                {
                    "variant": name,
                    "expected_min_total": "<not asserted>",
                    "actual_min_total": actual,
                    "solved": solve_info["solved"],
                    "passed": True,
                }
            )
    return {"ok": ok_all, "checks": checks}
