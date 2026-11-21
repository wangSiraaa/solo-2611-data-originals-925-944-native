"""End-to-end orchestration: material -> roster -> adjudication -> files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import charter as charter_mod
from . import materials as materials_mod
from . import roster as roster_mod
from .util import MaterialError, canonical_json, digest


def analyze_case(name: str, material: dict[str, Any]) -> dict[str, Any]:
    """Rebuild both products for one material and attach a short verdict."""

    roster = roster_mod.build_roster(material)
    adjudication = charter_mod.build_charter(material, roster)
    return {
        "name": name,
        "material_digest": digest(material),
        "roster": roster,
        "charter": adjudication,
        "verdict": {
            "signable": adjudication["signable"],
            "unique": adjudication["unique"],
            "final_articles": adjudication["final_articles"],
            "final_digest": adjudication["final_digest"],
            "legal_total_orders": adjudication["motion_order_space"][
                "legal_total_orders"
            ],
            "outcome_count": len(adjudication["outcomes"]),
            "differing_finals": adjudication["differing_finals"],
        },
    }


def analyze_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    cases = materials_mod.material_cases(envelope)
    analysed = []
    for case in cases:
        report = analyze_case(case["name"], case["material"])
        report["material"] = case["material"]
        report["variant"] = case["variant"]
        analysed.append(report)
    return {
        "kind": "mixed_case_report",
        "cases": analysed,
        "summary": _summary(analysed),
    }


def _summary(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        verdict = case["verdict"]
        rows.append(
            {
                "name": case["name"],
                "signable": verdict["signable"],
                "final_articles": verdict["final_articles"],
                "legal_total_orders": verdict["legal_total_orders"],
                "outcome_count": verdict["outcome_count"],
                "differing_finals": verdict["differing_finals"],
            }
        )
    return rows


def render_case(report: dict[str, Any]) -> str:
    """Human-readable account used by the CLI's text mode."""

    lines: list[str] = []
    lines.append(f"== case: {report['name']} ==")
    verdict = report["verdict"]
    lines.append(
        f"legal total orders: {verdict['legal_total_orders']}; "
        f"distinct finals: {verdict['outcome_count']}"
    )
    for outcome in report["charter"]["outcomes"]:
        finals = canonical_json(outcome["final_articles"])
        lines.append(
            f"  final {outcome['final_digest'][:12]} {finals} "
            f"({outcome['order_count']} order(s))"
        )
        lines.append(f"    agenda: {outcome['agenda']}")
        for step in outcome["steps"]:
            ballot = step["ballot"]
            lines.append(
                "    - {motion} [{article}]: {reason}; "
                "eligible={eligible_count} yes={yes_count} no={no_count} "
                "abstain={abstain_count}; text {cur!r} -> {after!r}".format(
                    motion=step["motion"],
                    article=step["article"],
                    reason=step["reason"],
                    eligible_count=ballot["eligible_count"],
                    yes_count=ballot["yes_count"],
                    no_count=ballot["no_count"],
                    abstain_count=ballot["abstain_count"],
                    cur=step["current_text"],
                    after=step["current_after"],
                )
            )
    if verdict["signable"]:
        lines.append(
            f"SIGNABLE: {canonical_json(verdict['final_articles'])} "
            f"({verdict['final_digest']})"
        )
    else:
        lines.append("NOT SIGNABLE: legal orders produce differing finals")
        for final in verdict["differing_finals"]:
            lines.append(f"  possible final: {canonical_json(final)}")
    return "\n".join(lines)


def write_json(path: str | Path, value: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return path


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_seal(value: Any) -> bool:
    """Recompute the ``sealed`` digest for a saved artifact."""

    if not isinstance(value, dict) or "sealed" not in value:
        return False
    if value.get("kind") == "charter_signing_record":
        body = {key: item for key, item in value.items() if key != "sealed"}
    else:
        body = {
            key: item
            for key, item in value.items()
            if key not in ("sealed", "signing_record")
        }
    return digest(body) == value["sealed"]


def save_report(report: dict[str, Any], out_dir: str | Path) -> dict[str, str]:
    """Persist a case report, its two products and any signing record."""

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, str] = {}
    name = report["name"]
    saved["report"] = str(write_json(out_dir / f"{name}.report.json", report))
    saved["roster"] = str(
        write_json(out_dir / f"{name}.roster.json", report["roster"])
    )
    saved["charter"] = str(
        write_json(out_dir / f"{name}.charter.json", report["charter"])
    )
    signing = report["charter"].get("signing_record")
    if signing is not None:
        saved["signing_record"] = str(
            write_json(out_dir / f"{name}.signing.json", signing)
        )
    return saved


def load_signing_record(path: str | Path) -> dict[str, Any]:
    """Reopen a saved signing record and verify its seal."""

    record = read_json(path)
    if not isinstance(record, dict) or record.get("kind") != "charter_signing_record":
        raise MaterialError(
            "bad_signing_record",
            f"{path}: not a charter signing record",
            path=str(path),
        )
    record = dict(record)
    record["verified"] = verify_seal(record)
    if not record["verified"]:
        raise MaterialError(
            "broken_seal",
            f"{path}: signing record seal does not verify; it was altered",
            path=str(path),
        )
    return record
