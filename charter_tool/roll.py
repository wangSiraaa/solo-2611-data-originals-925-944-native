"""Roll-record ledger: revision arbitration and chronological folding.

Rules implemented here (from the task statement):

* every record has a stable ``id`` and a positive-integer ``rev``;
* for one ``id`` only the highest ``rev`` is used;
* that highest revision may be ``kind=cancel`` and then retracts the whole
  original record; a cancel line need only carry ``id`` and ``rev``;
* otherwise ``kind`` is one of ``in``/``out``/``recuse``/``unrecuse`` and the
  last two must name a ``motion``;
* two records sharing ``(id, rev)`` but differing in content are refused;
* surviving records take effect by ``(t, seq)`` and that order key may not
  collide;
* initially everybody is *out* and holds no recusal; attendance and each
  motion's recusal are independent booleans;
* leaving after arriving ends attendance only -- recusals persist, and a
  later arrival inherits them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .util import MaterialError, is_int, safe_ref

KINDS_WITH_MOTION = ("recuse", "unrecuse")
KINDS_PLAIN = ("in", "out")
PLAIN_FIELDS = ("id", "rev", "t", "seq", "member", "kind")
MOTION_FIELDS = PLAIN_FIELDS + ("motion",)
CANCEL_FIELDS = ("id", "rev", "kind")


@dataclass
class RollEvent:
    """One effective record, folded into the roster history."""

    ref: dict[str, Any]
    t: int
    seq: int
    member: str
    kind: str
    motion: str | None
    present_after: bool
    recused_after: frozenset[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "record": self.ref,
            "present": self.present_after,
            "recused": sorted(self.recused_after),
        }


@dataclass
class FoldState:
    present: bool
    recused: frozenset[str]
    present_at: dict[str, Any] = field(default_factory=dict)
    reasons: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class Ledger:
    members: list[str]
    records: list[dict[str, Any]]          # effective, ordered records
    events: list[RollEvent]
    trace: dict[str, list[RollEvent]]
    log: list[dict[str, Any]]
    cancels: list[dict[str, Any]] = field(default_factory=list)


def _check_member_name(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise MaterialError("bad_member", f"{where}: member must be a non-empty string")
    return value


def _check_int(value: Any, where: str, *, positive: bool = False) -> int:
    if not is_int(value) or (positive and value < 1):
        raise MaterialError(
            "bad_number",
            f"{where}: expected a {'positive ' if positive else ''}integer",
            value=value,
        )
    return value


def _record_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Reduce a raw record to the fields that define its meaning."""

    kind = raw.get("kind")
    if kind == "cancel":
        return {"id": raw.get("id"), "rev": raw.get("rev"), "kind": "cancel"}
    base = {key: raw.get(key) for key in PLAIN_FIELDS}
    if kind in KINDS_WITH_MOTION:
        base["motion"] = raw.get("motion")
    return base


def arbitrate(
    members: list[str], raw_roll: Any
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve revisions and cancels; return effective records + cancel log."""

    if not isinstance(raw_roll, list):
        raise MaterialError("bad_roll", "roll must be a list of records")

    member_set = set(members)
    seen_ids: set[str] = set()
    by_id: dict[str, list[dict[str, Any]]] = {}

    for index, raw in enumerate(raw_roll):
        where = f"roll[{index}]"
        if not isinstance(raw, dict):
            raise MaterialError("bad_record", f"{where}: record must be an object")
        rid = raw.get("id")
        if not isinstance(rid, str) or not rid:
            raise MaterialError("bad_id", f"{where}: id must be a non-empty string")
        _check_int(raw.get("rev"), where, positive=True)
        by_id.setdefault(rid, []).append(raw)
        seen_ids.add(rid)

    effective: list[dict[str, Any]] = []
    cancel_log: list[dict[str, Any]] = []
    order_keys: dict[tuple[int, int], str] = {}

    for rid in sorted(by_id):
        rows = by_id[rid]
        top_rev = max(r["rev"] for r in rows)
        top = [r for r in rows if r["rev"] == top_rev]

        # Same id + same rev must agree field-for-field, else refuse.
        fingerprints = {_fingerprint(r) for r in top}
        if len(fingerprints) > 1:
            raise MaterialError(
                "conflicting_revision",
                f"record {rid!r} rev {top_rev} has conflicting texts",
                id=rid,
                rev=top_rev,
                texts=sorted(fingerprints),
            )

        chosen = top[0]
        kind = chosen.get("kind")
        if kind == "cancel":
            cancel_log.append(
                {
                    "id": rid,
                    "rev": top_rev,
                    "cancels": [safe_ref(r) for r in rows if r["rev"] < top_rev],
                }
            )
            continue

        record = _validate_effective(rid, chosen, member_set)
        key = (record["t"], record["seq"])
        if key in order_keys:
            raise MaterialError(
                "duplicate_order_key",
                f"t/seq order key {key} is used by both "
                f"{order_keys[key]!r} and {rid!r}",
                t=key[0],
                seq=key[1],
                ids=[order_keys[key], rid],
            )
        order_keys[key] = rid
        effective.append(record)

    effective.sort(key=lambda r: (r["t"], r["seq"]))
    return effective, cancel_log


def _fingerprint(raw: dict[str, Any]) -> str:
    from .util import canonical_json

    return canonical_json(_record_fields(raw))


def _validate_effective(
    rid: str, raw: dict[str, Any], member_set: set[str]
) -> dict[str, Any]:
    where = f"record {rid!r}"
    kind = raw.get("kind")
    _check_int(raw.get("t"), where)
    _check_int(raw.get("seq"), where)
    member = _check_member_name(raw.get("member"), where)
    if member not in member_set:
        raise MaterialError(
            "unknown_member", f"{where}: {member!r} is not on the member list", member=member
        )
    if kind in KINDS_PLAIN:
        record = {
            "id": rid,
            "rev": raw["rev"],
            "t": raw["t"],
            "seq": raw["seq"],
            "member": member,
            "kind": kind,
        }
    elif kind in KINDS_WITH_MOTION:
        motion = raw.get("motion")
        if not isinstance(motion, str) or not motion:
            raise MaterialError(
                "missing_motion", f"{where}: {kind!r} must name a motion", id=rid
            )
        record = {
            "id": rid,
            "rev": raw["rev"],
            "t": raw["t"],
            "seq": raw["seq"],
            "member": member,
            "kind": kind,
            "motion": motion,
        }
    else:
        raise MaterialError(
            "bad_kind",
            f"{where}: kind must be in/out/recuse/unrecuse/cancel, got {kind!r}",
            id=rid,
            kind=kind,
        )
    return record


def fold(
    members: list[str], records: Iterable[dict[str, Any]]
) -> Ledger:
    """Apply effective records in time order to produce the roster history."""

    records = list(records)
    present: dict[str, bool] = {m: False for m in members}
    recused: dict[str, set[str]] = {m: set() for m in members}
    present_at: dict[str, Any] = {m: {"initial": True, "state": False} for m in members}
    reasons: dict[str, dict[str, Any]] = {
        m: {"code": "initial_out", "basis": {"initial": True, "state": False}}
        for m in members
    }
    trace: dict[str, list[RollEvent]] = {m: [] for m in members}
    events: list[RollEvent] = []

    for rec in records:
        m = rec["member"]
        kind = rec["kind"]
        if kind == "in":
            present[m] = True
            present_at[m] = safe_ref(rec)
            reasons[m] = {"code": "in", "basis": safe_ref(rec)}
        elif kind == "out":
            present[m] = False
            present_at[m] = safe_ref(rec)
            reasons[m] = {"code": "out", "basis": safe_ref(rec)}
        elif kind == "recuse":
            recused[m].add(rec["motion"])
        elif kind == "unrecuse":
            recused[m].discard(rec["motion"])
        event = RollEvent(
            ref=safe_ref(rec),
            t=rec["t"],
            seq=rec["seq"],
            member=m,
            kind=kind,
            motion=rec.get("motion"),
            present_after=present[m],
            recused_after=frozenset(recused[m]),
        )
        events.append(event)
        trace[m].append(event)

    return Ledger(
        members=list(members),
        records=records,
        events=events,
        trace=trace,
        log=[
            {
                "id": r["id"],
                "rev": r["rev"],
                "kind": r["kind"],
                "t": r["t"],
                "seq": r["seq"],
                "member": r["member"],
                **({"motion": r["motion"]} if "motion" in r else {}),
            }
            for r in records
        ],
    )


def replay_to(ledger: Ledger, t: int, seq: int) -> dict[str, FoldState]:
    """Fold all effective records whose order key is at or before (t, seq)."""

    present: dict[str, bool] = {m: False for m in ledger.members}
    recused: dict[str, set[str]] = {m: set() for m in ledger.members}
    present_at: dict[str, Any] = {
        m: {"initial": True, "state": False} for m in ledger.members
    }
    reasons: dict[str, dict[str, Any]] = {
        m: {"code": "initial_out", "basis": {"initial": True, "state": False}}
        for m in ledger.members
    }

    for rec in ledger.records:
        if (rec["t"], rec["seq"]) > (t, seq):
            break
        m = rec["member"]
        if rec["kind"] == "in":
            present[m] = True
            present_at[m] = safe_ref(rec)
            reasons[m] = {"code": "in", "basis": safe_ref(rec)}
        elif rec["kind"] == "out":
            present[m] = False
            present_at[m] = safe_ref(rec)
            reasons[m] = {"code": "out", "basis": safe_ref(rec)}
        elif rec["kind"] == "recuse":
            recused[m].add(rec["motion"])
        elif rec["kind"] == "unrecuse":
            recused[m].discard(rec["motion"])

    return {
        m: FoldState(
            present=present[m],
            recused=frozenset(recused[m]),
            present_at=present_at[m],
            reasons=reasons[m],
        )
        for m in ledger.members
    }


def eligible_at(
    ledger: Ledger, members: list[str], motion: str, t: int, seq: int
) -> dict[str, Any]:
    """Snapshot eligibility for one motion at one cutoff.

    A voter is eligible iff present at the cutoff and not currently recused
    from this motion. Attendees who are present but recused, and attendees
    who never arrived, are separated and each carries the concrete record
    that establishes the status.
    """

    states = replay_to(ledger, t, seq)
    eligible: list[str] = []
    excluded: list[dict[str, Any]] = []
    for m in members:
        state = states[m]
        if not state.present:
            excluded.append(
                {
                    "member": m,
                    "reason": "absent",
                    "present": False,
                    "recused": False,
                    "basis": state.present_at,
                }
            )
            continue
        if motion in state.recused:
            basis = _recusal_basis(ledger, m, motion, t, seq)
            excluded.append(
                {
                    "member": m,
                    "reason": "recused",
                    "present": True,
                    "recused": True,
                    "basis": state.present_at,
                    "recusal": basis,
                }
            )
            continue
        eligible.append(m)

    eligible_set = set(eligible)
    voters = [
        {
            "member": m,
            "eligible": m in eligible_set,
            "present": states[m].present,
            "recused": motion in states[m].recused,
            "present_basis": states[m].present_at,
            "recusal_basis": _recusal_basis(ledger, m, motion, t, seq)
            if motion in states[m].recused
            else None,
            "trace": [
                e.as_dict()
                for e in ledger.trace[m]
                if (e.t, e.seq) <= (t, seq)
            ],
        }
        for m in members
    ]

    return {
        "cutoff": {"t": t, "seq": seq},
        "eligible": eligible,
        "eligible_count": len(eligible),
        "excluded": excluded,
        "voters": voters,
        "effective_records": [
            {
                "id": r["id"],
                "rev": r["rev"],
                "t": r["t"],
                "seq": r["seq"],
                "member": r["member"],
                "kind": r["kind"],
                **({"motion": r["motion"]} if "motion" in r else {}),
            }
            for r in ledger.records
            if (r["t"], r["seq"]) <= (t, seq)
        ],
    }


def _recusal_basis(
    ledger: Ledger, member: str, motion: str, t: int, seq: int
) -> dict[str, Any]:
    """The recuse record still in force, or the unrecuse that cleared it."""

    last_set: dict[str, Any] | None = None
    last_clear: dict[str, Any] | None = None
    for rec in ledger.records:
        if (rec["t"], rec["seq"]) > (t, seq):
            break
        if rec["member"] != member:
            continue
        if rec.get("motion") != motion:
            continue
        if rec["kind"] == "recuse":
            last_set = safe_ref(rec)
            last_clear = None
        elif rec["kind"] == "unrecuse":
            last_clear = safe_ref(rec)
            last_set = None
    if last_set is not None:
        return {"active": True, "record": last_set}
    if last_clear is not None:
        return {"active": False, "record": last_clear}
    return {"active": False, "record": None}


def build_ledger(members: list[str], raw_roll: Any) -> Ledger:
    if not isinstance(members, list) or not members:
        raise MaterialError("bad_members", "members must be a non-empty list")
    clean: list[str] = []
    for index, name in enumerate(members):
        name = _check_member_name(name, f"members[{index}]")
        if name in clean:
            raise MaterialError("duplicate_member", f"duplicate member {name!r}")
        clean.append(name)
    records, cancels = arbitrate(clean, raw_roll)
    ledger = fold(clean, records)
    ledger.cancels = cancels
    return ledger
