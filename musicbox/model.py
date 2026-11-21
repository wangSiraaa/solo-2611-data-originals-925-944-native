"""Core data model: the paper tape (plate) and the comb/bench trial-play.

A plate has equal-length tracks of 0/1 columns (0 = paper, 1 = hole).  A patch
covers a contiguous run of one original track; later patches win, out-of-range
patches are rejected.  A head reads one track, strikes one tooth and may be
shifted right by a non-negative integer number of columns (``offset``).

On a tape a run of consecutive holes is struck once, at its left edge.  A
strike on a head lands at (left-edge column + offset).  The trial run walks the
tape column by column; between adjacent columns it takes either ``fast`` or
``slow`` whole time units.  A tooth may sound again only when at least
``cooldown`` time units have passed since its previous real strike.  The final
instant K is the last column index plus the largest head offset, even when no
note sounds at K.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

Bit = int
Row = str


class PlateError(ValueError):
    """The tape / heads / patches are malformed or a patch is out of range."""


class BenchError(ValueError):
    """The pulse data or a trial-play request is malformed."""


# --------------------------------------------------------------------------
# Paper tape
# --------------------------------------------------------------------------


def build_rows(tracks: Mapping[str, str], columns: int) -> Dict[str, List[Bit]]:
    """Validate ``tracks`` and return mutable row bit-lists."""
    if not isinstance(tracks, Mapping) or not tracks:
        raise PlateError("tracks must be a non-empty mapping of name -> 0/1 string")
    if isinstance(columns, bool) or not isinstance(columns, int) or columns < 1:
        raise PlateError("column count must be a positive integer")
    rows: Dict[str, List[Bit]] = {}
    for name, bits in tracks.items():
        if not isinstance(name, str) or not name:
            raise PlateError("track names must be non-empty strings")
        if not isinstance(bits, str):
            raise PlateError(f"track {name!r} must be a 0/1 string")
        if len(bits) != columns:
            raise PlateError(
                f"track {name!r} has {len(bits)} column(s); expected {columns}"
            )
        if any(ch not in "01" for ch in bits):
            raise PlateError(f"track {name!r} contains characters other than 0/1")
        rows[name] = [int(ch) for ch in bits]
    return rows


# A patch may be given either in dictionary form or via this dataclass.
@dataclass(frozen=True)
class Patch:
    track: str
    start: int
    bits: Sequence[int]


def parse_patch(raw) -> Patch:
    """Turn a JSON patch object into a :class:`Patch`, validating types."""
    if isinstance(raw, Patch):
        raw = {"track": raw.track, "start": raw.start, "bits": raw.bits}
    if not isinstance(raw, Mapping):
        raise PlateError("each patch must be an object")
    extra = set(raw) - {"track", "start", "bits"}
    if extra:
        raise PlateError(f"unknown patch field(s): {', '.join(sorted(extra))}")
    track = raw.get("track")
    start = raw.get("start")
    bits = raw.get("bits")
    if not isinstance(track, str) or not track:
        raise PlateError("patch.track must be a non-empty string")
    if isinstance(start, bool) or not isinstance(start, int):
        raise PlateError("patch.start must be an integer")
    if not isinstance(bits, str):
        raise PlateError("patch.bits must be a 0/1 string")
    if any(ch not in "01" for ch in bits):
        raise PlateError("patch.bits contains characters other than 0/1")
    return Patch(track=track, start=start, bits=tuple(int(ch) for ch in bits))


def apply_patch(rows: Dict[str, List[Bit]], patch: Patch) -> None:
    """Overwrite ``rows[patch.track]`` in place with ``patch``; reject overruns."""
    name = patch.track
    if name not in rows:
        raise PlateError(f"patch targets unknown track {name!r}")
    start = patch.start
    end = start + len(patch.bits)
    width = len(rows[name])
    if start < 0 or end > width:
        raise PlateError(
            f"patch [{start}, {end}) on {name!r} lies outside the tape [0, {width})"
        )
    for i, bit in enumerate(patch.bits):
        rows[name][start + i] = int(bit)


# --------------------------------------------------------------------------
# Heads, notes and left edges
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Head:
    track: str
    tooth: str
    offset: int


def parse_heads(raw_heads: Iterable[Mapping]) -> List[Head]:
    heads: List[Head] = []
    for raw in raw_heads:
        if not isinstance(raw, Mapping):
            raise PlateError("each head must be an object")
        extra = set(raw) - {"track", "tooth", "offset"}
        if extra:
            raise PlateError(f"unknown head field(s): {', '.join(sorted(extra))}")
        track = raw.get("track")
        tooth = raw.get("tooth")
        offset = raw.get("offset", 0)
        if not isinstance(track, str) or not track:
            raise PlateError("head.track must be a non-empty string")
        if not isinstance(tooth, str) or not tooth:
            raise PlateError("head.tooth must be a non-empty string")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise PlateError("head.offset must be a non-negative integer")
        heads.append(Head(track=track, tooth=tooth, offset=offset))
    return heads


def notes_from_rows(rows: Mapping[str, Sequence[Bit]]) -> Dict[str, List[int]]:
    """Left edges: for each track, the start column of every hole run."""
    notes: Dict[str, List[int]] = {}
    for name, bits in rows.items():
        starts: List[int] = []
        prev = 0
        for col, bit in enumerate(bits):
            if bit == 1 and prev == 0:
                starts.append(col)
            prev = bit
        notes[name] = starts
    return notes


@dataclass(frozen=True)
class PlayEvent:
    """One distinct tooth strike as produced by the platemaker."""

    time: int
    tooth: str

    def as_dict(self) -> Dict[str, object]:
        return {"time": self.time, "tooth": self.tooth}


def strip_thumps(notes: Mapping[str, Sequence[int]], heads: Iterable[Head]):
    """Collapse head strikes to one per (landing time, tooth).

    Returns ``(events, contributions)`` where ``events`` is a sorted tuple of
    distinct :class:`PlayEvent` (this is the full, losing nothing on track/left
    edge) and ``contributions`` lists every original source that landed there,
    so duplicate same-tooth strikes at one instant remain auditable.
    """
    contributions: List[Tuple[int, str, str, int]] = []
    event_keys = set()
    for head in heads:
        for col in notes.get(head.track, ()):
            t = col + head.offset
            contributions.append((t, head.tooth, head.track, col))
            event_keys.add((t, head.tooth))
    events = tuple(PlayEvent(t, tooth) for t, tooth in sorted(event_keys))
    contributions.sort()
    return events, contributions


# --------------------------------------------------------------------------
# The plate
# --------------------------------------------------------------------------


class Plate:
    """A fixed-width paper tape plus heads, after applying patches in order."""

    def __init__(
        self,
        tracks: Mapping[str, str],
        columns: Optional[int] = None,
        patches: Iterable = (),
        heads: Iterable[Mapping] = (),
    ):
        if columns is None:
            lengths = {len(v) for v in tracks.values() if isinstance(v, str)}
            if len(lengths) != 1:
                raise PlateError("tracks must all have the same length")
            columns = lengths.pop()
        self.columns = columns
        self.rows = build_rows(tracks, columns)
        self._original_rows = [list(bits) for bits in self.rows.values()]
        self.patches: List[Patch] = []
        for raw in patches:
            patch = parse_patch(raw)
            apply_patch(self.rows, patch)
            self.patches.append(patch)
        self.heads = parse_heads(heads)
        for head in self.heads:
            if head.track not in self.rows:
                raise PlateError(f"head reads unknown track {head.track!r}")

    @property
    def tracks(self) -> Dict[str, str]:
        return {name: "".join(str(b) for b in bits) for name, bits in self.rows.items()}

    @property
    def original_tracks(self) -> Dict[str, str]:
        return {
            name: "".join(str(b) for b in bits)
            for name, bits in zip(self.rows.keys(), self._original_rows)
        }

    def original_left_edges(self) -> Dict[str, List[int]]:
        """Left edges of the untouched original tape (before any patch)."""
        return notes_from_rows(
            {
                name: bits
                for name, bits in zip(self.rows.keys(), self._original_rows)
            }
        )

    def notes(self) -> Dict[str, List[int]]:
        return notes_from_rows(self.rows)

    def play_events(self) -> List[PlayEvent]:
        events, _ = strip_thumps(self.notes(), self.heads)
        return list(events)

    def contributions(self) -> List[Tuple[int, str, str, int]]:
        _, contributions = strip_thumps(self.notes(), self.heads)
        return contributions

    @property
    def max_offset(self) -> int:
        return max((h.offset for h in self.heads), default=0)

    @property
    def K(self) -> int:
        """Final instant: last column index plus the largest head offset."""
        return (self.columns - 1) + self.max_offset

    def as_dict(self) -> Dict[str, object]:
        """Post-patch view that a player consumes (plus audit detail)."""
        events = self.play_events()
        return {
            "columns": self.columns,
            "tracks": self.tracks,
            "original_tracks": self.original_tracks,
            "patches": [
                {"track": p.track, "start": p.start, "bits": "".join(map(str, p.bits))}
                for p in self.patches
            ],
            "heads": [
                {"track": h.track, "tooth": h.tooth, "offset": h.offset}
                for h in self.heads
            ],
            "left_edges": self.notes(),
            "original_left_edges": self.original_left_edges(),
            "K": self.K,
            "play": [e.as_dict() for e in events],
            "contributions": [
                {"time": t, "tooth": tooth, "track": tr, "column": col}
                for t, tooth, tr, col in self.contributions()
            ],
        }


def build_plate(plate_spec: Mapping) -> Plate:
    """Build a :class:`Plate` from a ``plate`` object (tracks/patches/heads)."""
    if not isinstance(plate_spec, Mapping):
        raise PlateError("plate must be an object")
    allowed = {"tracks", "patches", "heads", "columns"}
    extra = set(plate_spec) - allowed
    if extra:
        raise PlateError(f"unknown plate field(s): {', '.join(sorted(extra))}")
    tracks = plate_spec.get("tracks")
    if not isinstance(tracks, Mapping):
        raise PlateError("plate.tracks must be an object")
    columns = plate_spec.get("columns")
    return Plate(
        tracks,
        columns=columns,
        patches=plate_spec.get("patches", ()),
        heads=plate_spec.get("heads", ()),
    )


# --------------------------------------------------------------------------
# Bench (comb + trial play)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Bench:
    cooldown: Mapping[str, int]
    fast: int
    slow: int
    max_changes: int


def parse_bench(bench_spec: Mapping) -> Bench:
    if not isinstance(bench_spec, Mapping):
        raise BenchError("bench must be an object")
    allowed = {"cooldown", "fast", "slow", "max_changes"}
    extra = set(bench_spec) - allowed
    if extra:
        raise BenchError(f"unknown bench field(s): {', '.join(sorted(extra))}")
    cooldown_raw = bench_spec.get("cooldown", {})
    if not isinstance(cooldown_raw, Mapping):
        raise BenchError("bench.cooldown must be an object")
    cooldown: Dict[str, int] = {}
    for tooth, value in cooldown_raw.items():
        if not isinstance(tooth, str) or not tooth:
            raise BenchError("cooldown keys must be non-empty tooth names")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BenchError(f"cooldown for {tooth!r} must be a non-negative integer")
        cooldown[tooth] = value
    fast = bench_spec.get("fast")
    slow = bench_spec.get("slow")
    max_changes = bench_spec.get("max_changes", 0)
    for name, value in (("fast", fast), ("slow", slow)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise BenchError(f"bench.{name} must be an integer")
    if not (0 < fast < slow):
        raise BenchError("bench needs 0 < fast < slow")
    if isinstance(max_changes, bool) or not isinstance(max_changes, int) or max_changes < 0:
        raise BenchError("bench.max_changes must be a non-negative integer")
    return Bench(cooldown=cooldown, fast=fast, slow=slow, max_changes=max_changes)


def cooldown_of(bench: Bench, tooth: str) -> int:
    return bench.cooldown.get(tooth, 0)


def simulate(
    K: int,
    events: Sequence[PlayEvent],
    bench: Bench,
    steps: Sequence[int],
) -> Dict[str, object]:
    """Walk a candidate feed and report every strike's real (sounded) time.

    Ticks run 0..K; ``steps[t]`` is the travel time between tick ``t`` and
    tick ``t + 1``, so exactly ``K`` steps are required.  A strike whose tooth
    is still rebounding is silent (a miss).  Strikes on the same tooth at the
    same tick are one sound.  Returns a dict suitable for JSON output.
    """
    try:
        steps = [int(s) for s in steps]
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise BenchError("steps must be integers") from exc
    if len(steps) != K:
        raise BenchError(f"expected {K} step(s) to reach tick {K}, got {len(steps)}")
    if any(s not in (bench.fast, bench.slow) for s in steps):
        raise BenchError("each step must be either bench.fast or bench.slow")

    changes = 0
    prev = None
    for s in steps:
        if prev is not None and s != prev:
            changes += 1
        prev = s
    if changes > bench.max_changes:
        raise BenchError(
            f"feed needs {changes} change(s), exceeding max_changes={bench.max_changes}"
        )

    times = [0]
    for s in steps:
        times.append(times[-1] + s)

    # One sound per (tick, tooth); keep distinct teeth in tick order.
    by_tick: Dict[int, List[str]] = {}
    for event in events:
        if not (0 <= event.time <= K):
            raise BenchError(f"strike tick {event.time} is outside [0, {K}]")
        bucket = by_tick.setdefault(event.time, [])
        if event.tooth not in bucket:
            bucket.append(event.tooth)

    last_sound: Dict[str, int] = {}
    played: List[Dict[str, object]] = []
    missed: List[Dict[str, object]] = []
    for tick in range(K + 1):
        for tooth in by_tick.get(tick, ()):
            t = times[tick]
            last = last_sound.get(tooth)
            if last is not None and t - last < cooldown_of(bench, tooth):
                missed.append(
                    {"tooth": tooth, "tick": tick, "time": t, "since": t - last}
                )
                continue
            last_sound[tooth] = t
            gap = None if last is None else t - last
            played.append(
                {
                    "tooth": tooth,
                    "tick": tick,
                    "time": t,
                    "since_previous": gap,
                    "cooldown": cooldown_of(bench, tooth),
                }
            )
    ok = not missed
    return {
        "ok": ok,
        "K": K,
        "total_time": times[-1],
        "start_with": None if not steps else ("fast" if steps[0] == bench.fast else "slow"),
        "steps": steps,
        "step_count": len(steps),
        "changes": changes,
        "strike_times": times,
        "played": played,
        "missed": missed,
    }
