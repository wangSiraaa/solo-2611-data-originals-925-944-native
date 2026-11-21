"""Charter amendment engine: legal orders, admission, votes, final text.

The independently recorded roll-call cutoff for every motion is taken from
the attested roster.  Only the *order* in which same-day conditional
amendments are claimed is uncertain.  We enumerate every legal total order
compatible with the "must be handled before" slips, replay each one, and
group the results by final article text.

A motion is admitted only when the article's current text equals the text
on the slip in full.  A motion passes only when

* the number of eligible voters at its cutoff reaches the quorum, and
* yes votes strictly exceed the no votes actually cast by eligible voters.

Abstentions (including a missing ballot / no hand raised) never enter the
yes-vs-no comparison, and an all-abstention motion does not pass.  A motion
that fails the roll call or the vote leaves the article unchanged; a motion
whose ``old`` text no longer matches is simply not admitted.

The librarian may issue a signed charter only if *all* legal orders yield
the same final text.  When they diverge, two (or more) distinct finals are
returned together with a legal agenda, per-motion reasons and ballots.
"""

from __future__ import annotations

from typing import Any, Iterable

from . import roster as roster_mod
from .util import MaterialError, canonical_json, clone, digest, is_int


def build_charter(material: dict[str, Any], roster: dict[str, Any] | None = None) -> dict[str, Any]:
    """Adjudicate the charter from material and its attested roster."""

    if roster is None:
        roster = roster_mod.build_roster(material)

    motions_raw = material.get("motions")
    if not isinstance(motions_raw, list):
        raise MaterialError("bad_motions", "motions must be a list")
    motions = _validate_motions(motions_raw)

    articles_raw = material.get("articles")
    if not isinstance(articles_raw, dict):
        raise MaterialError("bad_articles", "articles must be an object")
    articles: dict[str, Any] = {}
    for key, value in articles_raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise MaterialError(
                "bad_article", "article names and texts must be strings", article=key
            )
        articles[key] = value

    for motion in motions:
        if motion["article"] not in articles:
            raise MaterialError(
                "unknown_article",
                f"motion {motion['id']!r} targets an article absent from the charter",
                motion=motion["id"],
                article=motion["article"],
            )
        if motion["id"] not in roster["cutoffs"]:
            raise MaterialError(
                "missing_cutoff",
                f"motion {motion['id']!r} has no attested roll-call snapshot",
                motion=motion["id"],
            )

    quorum = material.get("quorum")
    if not is_int(quorum) or quorum < 0:
        raise MaterialError("bad_quorum", "quorum must be a non-negative integer")

    before = _validate_before(material.get("before", []), {m["id"] for m in motions})
    orders = _legal_orders([m["id"] for m in motions], before)

    motion_by_id = {m["id"]: m for m in motions}
    results: list[dict[str, Any]] = []
    for order in orders:
        results.append(_simulate(order, motion_by_id, articles, roster, quorum))

    groups: dict[str, dict[str, Any]] = {}
    for result in results:
        key = canonical_json(result["final_articles"])
        group = groups.setdefault(
            key,
            {
                "final_articles": result["final_articles"],
                "orders": [],
                "order_count": 0,
                "processes": {},
                "representative": None,
            },
        )
        group["orders"].append(result["agenda"])
        group["order_count"] += 1
        proc_key = canonical_json(result["process"])
        proc = group["processes"].setdefault(
            proc_key,
            {
                "process": result["process"],
                "agenda": result["agenda"],
                "steps": result["steps"],
                "count": 0,
            },
        )
        proc["count"] += 1
        if group["representative"] is None or result["agenda"] < group["representative"][
            "agenda"
        ]:
            group["representative"] = result

    outcome_groups = []
    for key in sorted(groups):
        group = groups[key]
        reps = sorted(
            group["processes"].values(), key=lambda p: (p["agenda"], p["process"])
        )
        first = reps[0]
        outcome_groups.append(
            {
                "final_articles": group["final_articles"],
                "final_digest": digest(group["final_articles"]),
                "order_count": group["order_count"],
                "distinct_processes": len(group["processes"]),
                "agenda": first["agenda"],
                "steps": first["steps"],
                "ballots": first["steps"],
                "witnesses": [
                    {
                        "agenda": p["agenda"],
                        "process": p["process"],
                        "count": p["count"],
                    }
                    for p in reps
                ],
            }
        )

    unique = len(outcome_groups) == 1
    adjudication: dict[str, Any] = {
        "kind": "charter_adjudication",
        "quorum": quorum,
        "before": [list(pair) for pair in before],
        "motion_order_space": {
            "legal_total_orders": len(orders),
            "orders": [list(o) for o in orders],
            "orders_digest": digest([list(o) for o in orders]),
        },
        "initial_articles": articles,
        "motions": motions,
        "outcomes": outcome_groups,
        "unique": unique,
        "signable": unique,
        "final_articles": outcome_groups[0]["final_articles"] if unique else None,
        "final_digest": outcome_groups[0]["final_digest"] if unique else None,
        "differing_finals": [] if unique else [g["final_articles"] for g in outcome_groups],
        "roster_seal": roster.get("sealed"),
    }
    if unique:
        adjudication["signing_record"] = {
            "kind": "charter_signing_record",
            "final_articles": outcome_groups[0]["final_articles"],
            "final_digest": outcome_groups[0]["final_digest"],
            "motion_order_space_digest": adjudication["motion_order_space"][
                "orders_digest"
            ],
            "legal_total_orders": len(orders),
            "roster_seal": roster.get("sealed"),
            "agenda": outcome_groups[0]["agenda"],
            "witness_processes": len(outcome_groups[0]["witnesses"]),
        }
        adjudication["signing_record"]["sealed"] = digest(
            adjudication["signing_record"]
        )
    else:
        adjudication["contested"] = {
            "differing_finals": [
                {
                    "final_articles": g["final_articles"],
                    "final_digest": g["final_digest"],
                    "agenda": g["agenda"],
                    "order_count": g["order_count"],
                    "steps": g["steps"],
                    "witnesses": g["witnesses"],
                }
                for g in outcome_groups
            ]
        }
    adjudication["sealed"] = digest(
        {k: v for k, v in adjudication.items() if k not in ("sealed", "signing_record")}
    )
    return adjudication


def _validate_motions(raw: list[Any]) -> list[dict[str, str]]:
    seen: set[str] = set()
    motions: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        where = f"motions[{index}]"
        if not isinstance(item, dict):
            raise MaterialError("bad_motion", f"{where}: motion must be an object")
        mid = item.get("id")
        if not isinstance(mid, str) or not mid:
            raise MaterialError("bad_motion", f"{where}: id must be a non-empty string")
        if mid in seen:
            raise MaterialError(
                "duplicate_motion", f"motion id {mid!r} is not unique", motion=mid
            )
        seen.add(mid)
        for field in ("article", "old", "next"):
            if not isinstance(item.get(field), str):
                raise MaterialError(
                    "bad_motion",
                    f"{where}: {field} must be a string",
                    motion=mid,
                    field=field,
                )
        motions.append(
            {
                "id": mid,
                "article": item["article"],
                "old": item["old"],
                "next": item["next"],
            }
        )
    return motions


def _validate_before(raw: Any, motion_ids: set[str]) -> list[tuple[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MaterialError("bad_before", "before must be a list of [a, b] pairs")
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, pair in enumerate(raw):
        if (
            not isinstance(pair, (list, tuple))
            or len(pair) != 2
            or not all(isinstance(x, str) for x in pair)
        ):
            raise MaterialError(
                "bad_before",
                f"before[{index}] must be a pair of motion ids",
                value=pair,
            )
        a, b = pair
        for mid in (a, b):
            if mid not in motion_ids:
                raise MaterialError(
                    "unknown_motion_in_before",
                    f"before slip names unknown motion {mid!r}",
                    motion=mid,
                )
        if (a, b) not in seen:
            seen.add((a, b))
            pairs.append((a, b))
    return pairs


def _cycle(nodes: list[str], edges: list[tuple[str, str]]) -> list[str] | None:
    adjacency: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b in edges:
        adjacency[a].append(b)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GREY
        stack.append(node)
        for nxt in adjacency[node]:
            if color[nxt] == GREY:
                start = stack.index(nxt)
                return stack[start:] + [nxt]
            if color[nxt] == WHITE:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in nodes:
        if color[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return None


def _legal_orders(nodes: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    """Enumerate every topological order; raise a pointed error on a cycle."""

    cycle = _cycle(nodes, edges)
    if cycle is not None:
        raise MaterialError(
            "order_cycle",
            "the 'must be handled before' slips form a cycle: "
            + " -> ".join(cycle),
            cycle=cycle,
        )

    predecessors: dict[str, set[str]] = {n: set() for n in nodes}
    for a, b in edges:
        predecessors[b].add(a)

    orders: list[list[str]] = []
    chosen: list[str] = []
    placed: set[str] = set()

    def walk() -> None:
        if len(chosen) == len(nodes):
            orders.append(list(chosen))
            return
        for node in nodes:
            if node in placed:
                continue
            if predecessors[node] <= placed:
                chosen.append(node)
                placed.add(node)
                walk()
                placed.remove(node)
                chosen.pop()

    walk()
    return orders


def _simulate(
    order: list[str],
    motion_by_id: dict[str, dict[str, str]],
    initial_articles: dict[str, str],
    roster: dict[str, Any],
    quorum: int,
) -> dict[str, Any]:
    articles = dict(initial_articles)
    steps: list[dict[str, Any]] = []
    admitted: list[str] = []
    passed: list[str] = []

    for position, mid in enumerate(order, start=1):
        motion = motion_by_id[mid]
        snapshot = roster["cutoffs"][mid]
        tally = roster_mod.tally(snapshot)
        article = motion["article"]
        current = articles[article]
        quorum_met = tally["eligible_count"] >= quorum
        vote_met = tally["yes_count"] > tally["no_count"]
        step: dict[str, Any] = {
            "position": position,
            "motion": mid,
            "article": article,
            "current_text": current,
            "proposed_old": motion["old"],
            "proposed_next": motion["next"],
            "admitted": False,
            "reason": None,
            "quorum_required": quorum,
            "eligible_count": tally["eligible_count"],
            "quorum_met": quorum_met,
            "vote_met": vote_met,
            "passed": False,
            "ballot": tally,
        }
        if current != motion["old"]:
            step["reason"] = "text_mismatch"
            step["text_changed_by"] = None
        else:
            step["admitted"] = True
            admitted.append(mid)
            if not quorum_met:
                step["reason"] = "no_quorum"
            elif not vote_met:
                step["reason"] = "vote_not_passed"
            else:
                step["reason"] = "passed"
                step["passed"] = True
                passed.append(mid)
                articles[article] = motion["next"]
        step["current_after"] = articles[article]
        steps.append(step)

    return {
        "agenda": list(order),
        "steps": steps,
        "final_articles": dict(articles),
        "process": {
            "admitted": admitted,
            "passed": passed,
            "final_snapshot": articles,
        },
    }


def assess_vote(
    snapshot: dict[str, Any], quorum: int, member: str | None = None
) -> dict[str, Any]:
    """Standalone ballot/quorum reading, optionally for one named member."""

    tally = roster_mod.tally(snapshot)
    result: dict[str, Any] = {
        "motion": snapshot["motion"],
        "quorum": quorum,
        "quorum_met": tally["eligible_count"] >= quorum,
        "yes_vs_no": tally["yes_count"] > tally["no_count"],
        "passes": tally["eligible_count"] >= quorum
        and tally["yes_count"] > tally["no_count"],
        "tally": tally,
    }
    if member is not None:
        choice = tally["ballot"]["choices"].get(member) if tally["ballot"] else None
        result["member"] = roster_mod.eligibility_verdict(snapshot, member, choice)
    return result
