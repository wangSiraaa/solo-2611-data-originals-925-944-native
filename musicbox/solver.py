"""Find the fastest feed that lets every platemaker strike sound.

Ticks run ``0..K`` (``K = last column + max head offset``).  The feed is a
sequence of ``fast``/``slow`` step durations, ``steps[t]`` being the travel
time between tick ``t`` and tick ``t + 1``; exactly ``K`` steps are needed.

The search is an exact dynamic program.  Its state is

    (tick, changes used, previous step length, ages)

where ``ages`` records, for every tooth that has already sounded, how long ago
(relative to the current tick's real time) it last sounded.  Cooldown only
depends on those ages: a tooth due now sounds iff its age is at least its
cooldown, and then its age resets to zero.  Storing ages rather than absolute
times means that, for the same ages, the state with the smallest accumulated
time strictly dominates - so a shortest-path DP over these states is exact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .model import Bench, cooldown_of, simulate

# Ages of already-sounded teeth: sorted tuple of (tooth, age-since-last-sound).
Ages = Tuple[Tuple[str, int], ...]


@dataclass
class SolveResult:
    solved: bool
    total_time: Optional[int] = None
    start: Optional[str] = None
    steps: Optional[List[int]] = None
    changes_used: Optional[int] = None
    events: List[Dict[str, object]] = field(default_factory=list)
    reason: Optional[str] = None
    max_changes: Optional[int] = None
    states_explored: int = 0

    def as_dict(self) -> Dict[str, object]:
        return {
            "solved": self.solved,
            "reason": self.reason,
            "total_time": self.total_time,
            "K": self.total_time,
            "start": self.start,
            "steps": self.steps,
            "step_count": None if self.steps is None else len(self.steps),
            "changes_used": self.changes_used,
            "max_changes": self.max_changes,
            "events": self.events,
            "states_explored": self.states_explored,
        }


def solve(
    plate,
    bench: Bench,
    max_states: int = 5_000_000,
) -> SolveResult:
    """Return a shortest valid feed, or a clear no-solution reason."""
    K = plate.K
    events = plate.play_events()
    for e in events:
        if not (0 <= e.time <= K):  # pragma: no cover - model guarantees this
            raise ValueError(f"strike tick {e.time} outside [0, {K}]")

    due = _teeth_by_tick(events, K)
    lengths = (bench.fast,) if bench.fast == bench.slow else (bench.fast, bench.slow)
    # An age can never exceed the total travel time, and ages at or above the
    # cooldown are equivalent, so cap each tooth's age at the smaller of the
    # two.  That keeps the state space bounded even for huge cooldowns.
    horizon = K * max(lengths)
    caps = {
        tooth: min(cooldown_of(bench, tooth), horizon)
        for tick in due
        for tooth in due[tick]
    }

    # Initial: at tick 0 nothing has sounded yet, so every tooth due at tick 0
    # sounds immediately and its age resets to 0.
    ages0 = tuple(sorted((tooth, 0) for tooth in due.get(0, ())))
    initial = (0, 0, None, ages0)  # (tick, changes, prev_len, ages)
    best: Dict[Tuple[int, int, Optional[int], Ages], int] = {initial: 0}
    parents: Dict[Tuple[int, int, Optional[int], Ages], Tuple[int, int, Optional[int], Ages]] = {}
    explored = 1

    for tick in range(K):
        frontier = [(key, t) for key, t in best.items() if key[0] == tick]
        for (cur_tick, used, prev_len, ages), cur_time in frontier:
            for length in lengths:
                if prev_len is None or length == prev_len:
                    new_used = used
                else:
                    new_used = used + 1
                if new_used > bench.max_changes:
                    continue

                new_time = cur_time + length
                # Advance all ages by the step, then strike the due teeth.
                new_ages = _advance(ages, length, caps)
                new_ages = _strike(new_ages, due.get(tick + 1, ()), bench)
                if new_ages is None:
                    continue  # a strike would miss this feed

                key = (tick + 1, new_used, length, new_ages)
                if key not in best or new_time < best[key]:
                    best[key] = new_time
                    parents[key] = (cur_tick, used, prev_len, ages)
                    explored += 1

        if explored > max_states:
            raise RuntimeError(
                f"state space exceeded max_states={max_states}; "
                "this plate is too large for the exact search"
            )

    finals = [(key, t) for key, t in best.items() if key[0] == K]
    if not finals:
        return SolveResult(
            solved=False,
            reason=_explain_failure(K, due, bench),
            max_changes=bench.max_changes,
            states_explored=explored,
        )

    # Deterministic tie-break: shortest time, then lexicographically smallest
    # (start gear, then steps) - "fast" sorts before "slow".
    best_choice: Optional[Tuple[int, str, Tuple[int, ...], Tuple]] = None
    for key, total_time in finals:
        steps = _reconstruct(key, parents)
        choice = (total_time, "fast" if steps and steps[0] == bench.fast else "slow", tuple(steps), key)
        if best_choice is None or choice[:3] < best_choice[:3]:
            best_choice = choice

    assert best_choice is not None
    total_time, _start, steps_t, key = best_choice
    steps = list(steps_t)
    sim = simulate(K, events, bench, steps)
    if not sim["ok"] or sim["total_time"] != total_time:  # pragma: no cover
        raise AssertionError(
            f"solver/simulator disagree: solver={total_time}, "
            f"sim={sim['total_time']}, ok={sim['ok']}"
        )
    return SolveResult(
        solved=True,
        total_time=total_time,
        start=sim["start_with"],
        steps=steps,
        changes_used=sim["changes"],
        events=sim["played"],
        max_changes=bench.max_changes,
        states_explored=explored,
    )


def _teeth_by_tick(events, K: int) -> Dict[int, Tuple[str, ...]]:
    due: Dict[int, List[str]] = {}
    for e in events:
        bucket = due.setdefault(e.time, [])
        if e.tooth not in bucket:
            bucket.append(e.tooth)
    return {tick: tuple(teeth) for tick, teeth in due.items()}


def _advance(ages: Ages, delta: int, caps: Dict[str, int]) -> Ages:
    if delta == 0:
        return ages
    # Cap at the cooldown; values at or above it are equivalent in the DP and
    # reset to zero as soon as the tooth sounds.
    return tuple((tooth, min(age + delta, caps.get(tooth, 0))) for tooth, age in ages)


def _strike(ages: Ages, teeth: Sequence[str], bench: Bench) -> Optional[Ages]:
    """Apply strikes at the current tick; ``None`` if any tooth still rebounds."""
    if not teeth:
        return ages
    current = dict(ages)
    for tooth in teeth:
        age = current.get(tooth)
        if age is not None and age < cooldown_of(bench, tooth):
            return None
    for tooth in teeth:
        current[tooth] = 0
    return tuple(sorted(current.items()))


def _reconstruct(key, parents) -> List[int]:
    steps: List[int] = []
    while key[0] > 0:
        prev_len = key[2]
        assert prev_len is not None
        steps.append(prev_len)
        key = parents[key]
    steps.reverse()
    return steps


def _explain_failure(K: int, due: Dict[int, Tuple[str, ...]], bench: Bench) -> str:
    if K == 0:
        # Only one tick, no travel at all: nothing can be too close.
        return "no feed exists for this plate"
    pairs = []
    for tick in sorted(due):
        for tooth in due[tick]:
            cd = cooldown_of(bench, tooth)
            if cd > 0:
                pairs.append(f"{tooth}@{tick} (cooldown {cd})")
    detail = ", ".join(pairs) if pairs else "no positive cooldowns but still unsatisfiable"
    return (
        "no feed with max_changes="
        f"{bench.max_changes} (fast={bench.fast}, slow={bench.slow}, K={K}) "
        "lets every strike sound; the binding strikes are: "
        + detail
    )
