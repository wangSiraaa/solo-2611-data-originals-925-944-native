"""Small shared helpers: canonical JSON, hashing, dotted-path access."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


class MaterialError(Exception):
    """A structural problem in the archival material.

    The archive must refuse the material rather than silently guess a value.
    """

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            out["details"] = self.details
        return out

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.details:
            return f"[{self.code}] {self.message} ({self.details})"
        return f"[{self.code}] {self.message}"


def canonical_json(value: Any) -> str:
    """Deterministic JSON used for signatures and grouping."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def clone(value: Any) -> Any:
    return copy.deepcopy(value)


def is_int(value: Any) -> bool:
    """True for real integers (JSON booleans are not integers)."""

    return isinstance(value, int) and not isinstance(value, bool)


def get_path(obj: Any, path: str) -> Any:
    cur = obj
    walked: list[str] = []
    for part in path.split("."):
        walked.append(part)
        try:
            if isinstance(cur, list) and part.isdigit():
                cur = cur[int(part)]
            else:
                cur = cur[part]
        except (KeyError, IndexError, TypeError):
            raise MaterialError(
                "unknown_path",
                f"material field {'/'.join(walked)} does not exist",
                path=path,
            ) from None
    return cur


def set_path(obj: Any, path: str, value: Any) -> None:
    parts = path.split(".")
    parent = get_path(obj, ".".join(parts[:-1])) if len(parts) > 1 else obj
    leaf = parts[-1]
    try:
        if isinstance(parent, list) and leaf.isdigit():
            parent[int(leaf)] = value
        elif isinstance(parent, dict):
            if leaf not in parent:
                raise KeyError(leaf)
            parent[leaf] = value
        else:
            raise TypeError(type(parent))
    except (KeyError, IndexError, TypeError):
        raise MaterialError(
            "unknown_path",
            f"cannot replace missing material field {path!r}",
            path=path,
        ) from None


def append_path(obj: Any, path: str, value: Any) -> None:
    target = get_path(obj, path)
    if not isinstance(target, list):
        raise MaterialError(
            "not_a_list",
            f"cannot append to {path!r}: target is not a list",
            path=path,
            actual_type=type(target).__name__,
        )
    target.append(clone(value))


def merge_path(obj: Any, path: str, value: Any) -> None:
    target = get_path(obj, path)
    if not isinstance(target, dict) or not isinstance(value, dict):
        raise MaterialError(
            "not_a_mapping",
            f"cannot merge into {path!r}: both sides must be objects",
            path=path,
        )
    target.update(clone(value))


def delete_path(obj: Any, path: str) -> None:
    parts = path.split(".")
    parent = get_path(obj, ".".join(parts[:-1])) if len(parts) > 1 else obj
    leaf = parts[-1]
    try:
        if isinstance(parent, list) and leaf.isdigit():
            del parent[int(leaf)]
        elif isinstance(parent, dict):
            del parent[leaf]
        else:
            raise TypeError(type(parent))
    except (KeyError, IndexError, TypeError):
        raise MaterialError(
            "unknown_path",
            f"cannot delete missing material field {path!r}",
            path=path,
        ) from None


def safe_ref(record: dict[str, Any]) -> dict[str, Any]:
    """A compact, serialisable reference to one roll record."""

    ref = {
        "id": record.get("id"),
        "rev": record.get("rev"),
        "t": record.get("t"),
        "seq": record.get("seq"),
        "kind": record.get("kind"),
    }
    if "member" in record:
        ref["member"] = record["member"]
    if "motion" in record:
        ref["motion"] = record["motion"]
    return ref


def initial_ref(state: bool = False) -> dict[str, Any]:
    return {"initial": True, "state": state}
