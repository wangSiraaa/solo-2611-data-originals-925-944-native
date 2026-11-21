"""Load case material and resolve ``base`` + ``variants`` into cases.

A case file may either be

* a plain material object (``members``/``roll``/``cutoffs``/... ), or
* a ``{ "base": <material>, "variants": [...] }`` envelope as in
  ``case.json``.

Each variant copies ``base`` and applies exactly one declared mutation.  The
mutation is written with the operation as the key and a dotted path as its
value, e.g.::

    {"name": "recusal", "append_to": "roll", "value": {...}}
    {"name": "reverse-order", "replace": "before", "value": [["M2", "M1"]]}

Supported operations: ``append_to``, ``replace``, ``merge``, ``delete``.
An explicit ``{"op": ..., "path": ..., "value": ...}`` form is accepted too.
Variants reproduce a scenario only; they never carry hidden knowledge into
the engine -- every derived roster is rebuilt from the resulting material.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .util import (
    MaterialError,
    append_path,
    clone,
    delete_path,
    merge_path,
    set_path,
)

OPERATIONS = ("append_to", "replace", "merge", "delete")


def load_material(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MaterialError("unreadable_material", f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MaterialError(
            "invalid_json", f"{path} is not valid JSON: {exc}", path=str(path)
        ) from exc
    if not isinstance(data, dict):
        raise MaterialError("bad_material", f"{path}: top level must be an object")
    return data


def material_cases(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ``[{"name", "material", "variant"}]`` with ``base`` first."""

    if "base" not in envelope:
        if "variants" in envelope:
            raise MaterialError("bad_material", "variants require a base material")
        return [{"name": "material", "material": clone(envelope), "variant": None}]

    base = envelope["base"]
    if not isinstance(base, dict):
        raise MaterialError("bad_material", "base must be an object")

    cases = [{"name": "base", "material": clone(base), "variant": None}]
    variants = envelope.get("variants", [])
    if not isinstance(variants, list):
        raise MaterialError("bad_variants", "variants must be a list")

    names: set[str] = {"base"}
    for index, variant in enumerate(variants):
        where = f"variants[{index}]"
        if not isinstance(variant, dict):
            raise MaterialError("bad_variant", f"{where}: variant must be an object")
        name = variant.get("name", f"variant-{index}")
        if not isinstance(name, str) or not name:
            raise MaterialError("bad_variant", f"{where}: name must be a non-empty string")
        if name in names:
            raise MaterialError("duplicate_variant", f"variant name {name!r} is not unique")
        names.add(name)
        cases.append(
            {
                "name": name,
                "material": apply_variant(base, variant, where),
                "variant": clone(variant),
            }
        )
    return cases


def _operation(variant: dict[str, Any], where: str) -> tuple[str, str, bool]:
    explicit = [key for key in OPERATIONS if key in variant]
    if explicit:
        op = explicit[0]
        path = variant[op]
        if not isinstance(path, str) or not path:
            raise MaterialError("bad_variant", f"{where}: {op} needs a dotted path string")
        return op, path, "value" in variant
    if "op" in variant:
        op = variant["op"]
        if op not in OPERATIONS:
            raise MaterialError(
                "bad_variant", f"{where}: unknown operation {op!r}", found=op
            )
        path = variant.get("path")
        if not isinstance(path, str) or not path:
            raise MaterialError("bad_variant", f"{where}: {op} needs a dotted 'path'")
        return op, path, "value" in variant
    raise MaterialError(
        "bad_variant",
        f"{where}: expected one operation among {list(OPERATIONS)}",
        variant=variant,
    )


def apply_variant(base: dict[str, Any], variant: dict[str, Any], where: str) -> dict[str, Any]:
    material = clone(base)
    op, path, has_value = _operation(variant, where)
    if op != "delete" and not has_value:
        raise MaterialError("bad_variant", f"{where}: {op} needs a 'value'")
    value = variant.get("value")
    if op == "append_to":
        append_path(material, path, value)
    elif op == "replace":
        if len(path.split(".")) == 1 and path in ("base",):
            raise MaterialError("bad_variant", f"{where}: cannot replace {path!r}")
        set_path(material, path, clone(value))
    elif op == "merge":
        merge_path(material, path, value)
    elif op == "delete":
        delete_path(material, path)
    return material
