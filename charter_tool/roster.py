"""The attested roster product, one sealed snapshot per motion cutoff."""

from __future__ import annotations

from typing import Any

from . import roll
from .util import MaterialError, digest, is_int


def build_roster(material: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct the roster from archival material only.

    The consumer receives this product, the source material and the meeting
    papers; it may not add missing attendees of its own.
    """

    members = material.get("members")
    ledger = roll.build_ledger(members, material.get("roll"))

    cutoffs = material.get("cutoffs")
    if not isinstance(cutoffs, dict) or not cutoffs:
        raise MaterialError("bad_cutoffs", "cutoffs must be a non-empty object")

    votes = material.get("votes", {})
    if not isinstance(votes, dict):
        raise MaterialError("bad_votes", "votes must be an object keyed by motion")

    motions = material.get("motions")
    if not isinstance(motions, list) or not motions:
        raise MaterialError("bad_motions", "motions must be a non-empty list")
    motion_ids = [m.get("id") for m in motions if isinstance(m, dict)]
    if any(not isinstance(mid, str) or not mid for mid in motion_ids):
        raise MaterialError("bad_motion", "every motion needs a non-empty id")

    snapshots: dict[str, Any] = {}
    for motion_id in motion_ids:
        if motion_id not in cutoffs:
            raise MaterialError(
                "missing_cutoff",
                f"motion {motion_id!r} has no independently recorded cutoff",
                motion=motion_id,
            )
        t, seq = _parse_cutoff(cutoffs[motion_id], motion_id)
        snap = roll.eligible_at(ledger, list(members), motion_id, t, seq)
        snap["motion"] = motion_id
        snap["ballot"] = _ballot_for(votes.get(motion_id), members, motion_id)
        snap["sealed"] = digest(
            {
                "members": members,
                "motion": motion_id,
                "cutoff": [t, seq],
                "eligible": snap["eligible"],
                "excluded": snap["excluded"],
                "ballot": snap["ballot"],
            }
        )
        snapshots[motion_id] = snap

    product = {
        "kind": "attested_roster",
        "members": list(members),
        "cutoffs": snapshots,
        "roll_events": [
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
        ],
        "cancelled": ledger.cancels,
    }
    product["sealed"] = digest(product)
    return product


def _parse_cutoff(raw: Any, motion_id: str) -> tuple[int, int]:
    if (
        not isinstance(raw, (list, tuple))
        or len(raw) != 2
        or not is_int(raw[0])
        or not is_int(raw[1])
    ):
        raise MaterialError(
            "bad_cutoff",
            f"cutoff for motion {motion_id!r} must be [t, seq] integers",
            motion=motion_id,
            value=raw,
        )
    return int(raw[0]), int(raw[1])


def _ballot_for(raw: Any, members: list[str], motion_id: str) -> dict[str, Any]:
    if raw is None:
        return {"recorded": False, "choices": {}, "motion": motion_id}
    if not isinstance(raw, dict):
        raise MaterialError("bad_ballot", f"votes for {motion_id!r} must be an object")
    choices: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in members:
            raise MaterialError(
                "unknown_voter",
                f"votes for {motion_id!r} mention unknown member {key!r}",
                motion=motion_id,
                member=key,
            )
        if value not in ("yes", "no", "abstain"):
            # "missing" is represented by absence, never by a stray value.
            raise MaterialError(
                "bad_vote",
                f"vote by {key!r} on {motion_id!r} must be yes/no/abstain",
                motion=motion_id,
                member=key,
                value=value,
            )
        choices[key] = value
    return {"recorded": True, "choices": choices, "motion": motion_id}


def eligibility_verdict(
    snapshot: dict[str, Any], member: str, choice: Any
) -> dict[str, Any]:
    """Whether *member* could vote on this motion and how the ballot reads.

    Distinguishes "did not raise a hand" from "was not eligible".
    """

    if member not in snapshot["eligible"]:
        excluded = next(
            (e for e in snapshot["excluded"] if e["member"] == member), None
        )
        return {
            "member": member,
            "eligible": False,
            "reason": excluded["reason"] if excluded else "unknown",
            "counted": None,
            "explanation": "not_eligible",
            "basis": excluded,
        }
    ballot = snapshot["ballot"]
    if not ballot["recorded"]:
        return {
            "member": member,
            "eligible": True,
            "counted": "abstain",
            "explanation": "ballot_not_recorded",
            "choice": None,
        }
    if member in ballot["choices"]:
        return {
            "member": member,
            "eligible": True,
            "counted": ballot["choices"][member],
            "explanation": "recorded",
            "choice": ballot["choices"][member],
        }
    return {
        "member": member,
        "eligible": True,
        "counted": "abstain",
        "explanation": "no_hand_raised",
        "choice": None,
    }


def tally(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Tally the eligible ballots for one motion."""

    ballot = snapshot["ballot"]
    choices = ballot["choices"] if ballot["recorded"] else {}
    yes: list[str] = []
    no: list[str] = []
    abstain: list[str] = []
    for member in snapshot["eligible"]:
        choice = choices.get(member, "abstain")
        if choice == "yes":
            yes.append(member)
        elif choice == "no":
            no.append(member)
        else:
            abstain.append(member)
    return {
        "motion": snapshot["motion"],
        "ballot_recorded": bool(ballot["recorded"]),
        "eligible": list(snapshot["eligible"]),
        "eligible_count": len(snapshot["eligible"]),
        "yes": yes,
        "no": no,
        "abstain": abstain,
        "yes_count": len(yes),
        "no_count": len(no),
        "abstain_count": len(abstain),
        "ineligible_ballots": sorted(
            m for m in choices if m not in set(snapshot["eligible"])
        ),
    }
