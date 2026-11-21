import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from charter_tool import materials as materials_mod  # noqa: E402
from charter_tool import pipeline  # noqa: E402
from charter_tool.util import MaterialError, canonical_json  # noqa: E402


def _load_any(path: str) -> tuple[dict, str | None]:
    """Accept a case envelope, a bare material, or a saved case report."""

    data = materials_mod.load_material(path)
    if isinstance(data.get("material"), dict) and "name" in data:
        return data["material"], data["name"]
    return data, None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="reopen",
        description="Rebuild a case from saved material and reopen a signing record.",
    )
    parser.add_argument("material", help="saved case/material/report JSON")
    parser.add_argument("--case", help="base or variant name")
    parser.add_argument("--signing", help="saved *.signing.json to verify and re-derive")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    envelope, saved_name = _load_any(args.material)
    cases = materials_mod.material_cases(envelope)
    if saved_name and not args.case:
        cases[0]["name"] = saved_name
    chosen = cases[0]
    if args.case:
        chosen = next((c for c in cases if c["name"] == args.case), None)
        if chosen is None:
            print(
                f"error: no case named {args.case!r} ({[c['name'] for c in cases]})",
                file=sys.stderr,
            )
            return 2
    report = pipeline.analyze_case(chosen["name"], chosen["material"])
    out = {"name": chosen["name"], "verdict": report["verdict"]}
    if args.signing:
        record = pipeline.load_signing_record(args.signing)
        out["signing_record"] = record
        out["matches_rebuilt"] = (
            record["final_articles"] == report["charter"]["final_articles"]
            and record["roster_seal"] == report["roster"]["sealed"]
        )
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"rebuilt {chosen['name']}: {canonical_json(report['verdict']['final_articles'])}")
        if args.signing:
            print(f"signing seal verified: {out['signing_record']['verified']}")
            print(f"matches rebuilt: {out['matches_rebuilt']}")
    return 0 if out.get("matches_rebuilt", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
