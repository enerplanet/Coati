"""Comparing a results document with what a framework says about its own model."""

from __future__ import annotations

import json
import math
from typing import Any

from coati import jsonio

#: How far two numbers may be apart, relative to their size and in absolute terms.
RELATIVE = 1e-7
ABSOLUTE = 1e-6

#: How far two costs may be apart: the statistics of PyPSA round to five decimal places.
ROUNDED = 1e-4


def as_json(document: Any, **options: Any) -> Any:
    """Return ``document`` as a JSON parser reads what Coati writes of it."""
    return json.loads(jsonio.dumps(document, jsonio.JsonOptions(**options)))


def differences(
    found: Any, expected: Any, path: str = "$", tolerance: float = ABSOLUTE
) -> list[str]:
    """List where ``found`` differs from ``expected``, numbers compared with a tolerance."""
    if isinstance(expected, dict) and isinstance(found, dict):
        lines = [f"{path}.{key}: missing" for key in expected if key not in found]
        lines += [f"{path}.{key}: not expected" for key in found if key not in expected]
        for key in expected:
            if key in found:
                lines += differences(found[key], expected[key], f"{path}.{key}", tolerance)
        return lines
    if isinstance(expected, list) and isinstance(found, list):
        if len(expected) != len(found):
            return [f"{path}: {len(found)} elements, expected {len(expected)}"]
        lines = []
        for index, (left, right) in enumerate(zip(found, expected, strict=True)):
            lines += differences(left, right, f"{path}[{index}]", tolerance)
        return lines
    if _is_number(expected) and _is_number(found):
        if math.isclose(found, expected, rel_tol=RELATIVE, abs_tol=tolerance):
            return []
        return [f"{path}: {found!r}, expected {expected!r}"]
    return [] if found == expected else [f"{path}: {found!r}, expected {expected!r}"]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def against_facts(document: dict[str, Any], facts: dict[str, Any]) -> list[str]:
    """List where a results document differs from the facts of a framework.

    The facts name what the framework says; the document may say more. Of
    ``capacities`` and the other maps, the entries that the facts name are
    compared. ``costs`` are those of each technology, all locations together,
    and ``transmission_flow`` holds the time series alone. A key that starts
    with an underscore is a note for a test of its own and is not compared.
    """
    lines: list[str] = []
    for key, expected in facts.items():
        if key.startswith("_"):
            continue
        if key == "costs":
            found = _costs_by_technology(document, expected)
            lines += differences(found, expected, "$.costs", ROUNDED)
        elif key == "transmission_flow":
            flows = {pair: entry["timeseries"] for pair, entry in document[key].items()}
            lines += differences(flows, expected, f"$.{key}")
        elif isinstance(expected, dict):
            found = document.get(key, {})
            chosen = {name: found[name] for name in expected if name in found}
            if key == "dispatch":  # a technology that puts out nothing is left out
                chosen = {
                    name: found.get(name, [0.0] * len(series)) for name, series in expected.items()
                }
            lines += differences(chosen, expected, f"$.{key}")
        else:
            lines += differences(document.get(key), expected, f"$.{key}")
    return lines


def _costs_by_technology(document: dict[str, Any], expected: dict[str, Any]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for costs in document["costs_by_location"].values():
        for technology, cost in costs.items():
            totals[technology] = totals.get(technology, 0.0) + cost
    return {name: totals.get(name, 0.0) for name in expected}
