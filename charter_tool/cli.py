"""Command line front end.

Usage
-----

    python -m charter_tool roster  case.json [--case NAME] [--out DIR] [--json]
    python -m charter_tool charter case.json [--case NAME] [--out DIR] [--json]
    python -m charter_tool analyze case.json [--out DIR] [--json]
    python -m charter_tool member  case.json MEMBER MOTION [--case NAME] [--json]
    python -m charter_tool reopen  signing.json [--json]

``roster`` and ``charter`` are the two business entry points.  ``analyze``
runs every base/variant case and prints a comparison.  ``member`` answers
whether one named person was entitled to vote on one motion at its cutoff.
``reopen`` re-reads a saved signing record and checks its seal.

Materials may be passed as ``-`` to read JSON from standard input.  Output is
human-readable text unless ``--json`` is given; ``--out`` writes local files
that can be reopened later.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import charter as charter_mod
from . import materials as materials_mod
from . import pipeline
from . import roster as roster_mod
from .util import MaterialError, canonical_json


def _load(path: str) -> dict[str, Any]:
    if path == "-":
        try:
            data = json.loads(sys.stdin.read())
        except json.JSONDecodeError as exc:
            raise MaterialError("invalid_json", f"stdin is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise MaterialError("bad_material", "stdin: top level must be an object")
        return data
    return materials_mod.load_material(path)


def _select(envelope: dict[str, Any], name: str | None) -> dict[str, Any]:
    cases = materials_mod.material_cases(envelope)
    if name is None:
        if len(cases) > 1:
            raise MaterialError(
                "case_required",
                "material has variants; choose one with --case "
                f"(available: {', '.join(c['name'] for c in cases)})",
                available=[c["name"] for c in cases],
            )
        return cases[0]
    for case in cases:
        if case["name"] == name:
            return case
    raise MaterialError(
        "unknown_case",
        f"no case named {name!r}",
        available=[c["name"] for c in cases],
    )


def _emit(value: Any, as_json: bool, text: str | None = None) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(text if text is not None else json.dumps(value, ensure_ascii=False, indent=2))


def cmd_roster(args: argparse.Namespace) -> int:
    envelope = _load(args.material)
    case = _select(envelope, args.case)
    product = roster_mod.build_roster(case["material"])
    if args.out:
        path = pipeline.write_json(Path(args.out) / f"{case['name']}.roster.json", product)
        print(f"wrote {path}", file=sys.stderr)
    if args.json:
        _emit(product, True)
    else:
        lines = [f"== roster: {case['name']} ==", f"members: {', '.join(product['members'])}"]
        for mid, snap in product["cutoffs"].items():
            lines.append(
                f"- {mid} cutoff (t={snap['cutoff']['t']}, seq={snap['cutoff']['seq']}): "
                f"eligible={snap['eligible']} ({snap['eligible_count']})"
            )
            for ex in snap["excluded"]:
                lines.append(
                    f"    excluded {ex['member']}: {ex['reason']} "
                    f"(basis {canonical_json(ex['basis'])})"
                )
            ballot = snap["ballot"]
            if ballot["recorded"]:
                lines.append(f"    ballot: {canonical_json(ballot['choices'])}")
            else:
                lines.append("    ballot: not recorded (all eligible count as abstain)")
        _emit(product, False, "\n".join(lines))
    return 0


def cmd_charter(args: argparse.Namespace) -> int:
    envelope = _load(args.material)
    case = _select(envelope, args.case)
    roster = roster_mod.build_roster(case["material"])
    result = charter_mod.build_charter(case["material"], roster)
    if args.out:
        stem = Path(args.out) / case["name"]
        path = pipeline.write_json(Path(f"{stem}.charter.json"), result)
        print(f"wrote {path}", file=sys.stderr)
        if "signing_record" in result:
            spath = pipeline.write_json(Path(f"{stem}.signing.json"), result["signing_record"])
            print(f"wrote {spath}", file=sys.stderr)
    if args.json:
        _emit(result, True)
        return 0
    print(pipeline.render_case({"name": case["name"], "charter": result, "verdict": {
        "signable": result["signable"],
        "unique": result["unique"],
        "final_articles": result["final_articles"],
        "final_digest": result["final_digest"],
        "legal_total_orders": result["motion_order_space"]["legal_total_orders"],
        "outcome_count": len(result["outcomes"]),
        "differing_finals": result["differing_finals"],
    }}))
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    envelope = _load(args.material)
    report = pipeline.analyze_envelope(envelope)
    if args.out:
        for case in report["cases"]:
            saved = pipeline.save_report(case, args.out)
            for kind, path in saved.items():
                print(f"wrote {kind}: {path}", file=sys.stderr)
    if args.json:
        _emit(report, True)
        return 0
    for case in report["cases"]:
        print(pipeline.render_case(case))
        print()
    print("== summary ==")
    for row in report["summary"]:
        if row["signable"]:
            print(
                f"{row['name']}: SIGNABLE {canonical_json(row['final_articles'])} "
                f"({row['legal_total_orders']} legal order(s))"
            )
        else:
            print(
                f"{row['name']}: NOT SIGNABLE -- {row['outcome_count']} distinct finals "
                f"over {row['legal_total_orders']} legal order(s): "
                f"{[canonical_json(f) for f in row['differing_finals']]}"
            )
    return 0


def cmd_member(args: argparse.Namespace) -> int:
    envelope = _load(args.material)
    case = _select(envelope, args.case)
    roster = roster_mod.build_roster(case["material"])
    motion = args.motion
    if motion not in roster["cutoffs"]:
        raise MaterialError(
            "unknown_motion",
            f"motion {motion!r} has no attested roll-call snapshot",
            motion=motion,
            available=sorted(roster["cutoffs"]),
        )
    if args.member not in roster["members"]:
        raise MaterialError(
            "unknown_member",
            f"{args.member!r} is not on the member list",
            member=args.member,
        )
    quorum = case["material"].get("quorum")
    snapshot = roster["cutoffs"][motion]
    ballot = snapshot["ballot"]
    choice = ballot["choices"].get(args.member) if ballot["recorded"] else None
    verdict = roster_mod.eligibility_verdict(snapshot, args.member, choice)
    result = {
        "member": args.member,
        "motion": motion,
        "cutoff": snapshot["cutoff"],
        "eligible": verdict["eligible"],
        "reason": verdict.get("reason"),
        "counted": verdict["counted"],
        "explanation": verdict["explanation"],
        "basis": verdict.get("basis"),
        "ballot_recorded": ballot["recorded"],
        "recorded_choice": choice,
        "tally": roster_mod.tally(snapshot),
        "snapshot_seal": snapshot["sealed"],
    }
    if isinstance(quorum, int):
        result["quorum"] = quorum
        result["quorum_met"] = snapshot["eligible_count"] >= quorum
    if args.json:
        _emit(result, True)
    else:
        state = "ELIGIBLE" if result["eligible"] else f"NOT ELIGIBLE ({result['reason']})"
        print(f"{args.member} on {motion}: {state}")
        print(f"  counted as: {result['counted']} ({result['explanation']})")
        if result["basis"]:
            print(f"  basis: {canonical_json(result['basis'])}")
        print(f"  tally: {canonical_json(result['tally'])}")
    return 0


def cmd_reopen(args: argparse.Namespace) -> int:
    record = pipeline.load_signing_record(args.signing)
    if args.json:
        _emit(record, True)
    else:
        print("signing record verified")
        print(f"  final: {canonical_json(record['final_articles'])}")
        print(f"  digest: {record['final_digest']}")
        print(f"  legal total orders at signing: {record['legal_total_orders']}")
        print(f"  agenda: {record['agenda']}")
        print(f"  roster seal: {record['roster_seal']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="charter_tool",
        description=(
            "Reconstruct attested roll-call rosters and adjudicate charter "
            "amendments from archival material."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("material", help="case/material JSON file, or - for stdin")
        p.add_argument("--case", help="base or variant name to analyse")
        p.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    p_roster = sub.add_parser("roster", help="build the attested roster product")
    add_common(p_roster)
    p_roster.add_argument("--out", help="directory for saved roster file")
    p_roster.set_defaults(func=cmd_roster)

    p_charter = sub.add_parser("charter", help="adjudicate the final charter text")
    add_common(p_charter)
    p_charter.add_argument("--out", help="directory for saved charter/signing files")
    p_charter.set_defaults(func=cmd_charter)

    p_analyze = sub.add_parser("analyze", help="run base and every variant, compare")
    add_common(p_analyze)
    p_analyze.add_argument("--out", help="directory for all saved products")
    p_analyze.set_defaults(func=cmd_analyze)

    p_member = sub.add_parser("member", help="was one member eligible to vote on one motion?")
    add_common(p_member)
    p_member.add_argument("member", help="member id")
    p_member.add_argument("motion", help="motion id")
    p_member.set_defaults(func=cmd_member)

    p_reopen = sub.add_parser("reopen", help="re-read and verify a saved signing record")
    p_reopen.add_argument("signing", help="saved *.signing.json file")
    p_reopen.add_argument("--json", action="store_true")
    p_reopen.set_defaults(func=cmd_reopen)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except MaterialError as exc:
        if getattr(args, "json", False):
            print(json.dumps({"error": exc.as_dict()}, ensure_ascii=False, indent=2))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
