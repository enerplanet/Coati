"""The solution of a power flow in a network of PyPSA.

`n.lpf()` and `n.pf()` solve the electrical network for a dispatch that is
given, and optimise nothing: they find the voltage of every bus, the flow on
every line and transformer and the power that the slack takes up, and they
leave no objective behind. A network without an objective whose buses have
results therefore holds the solution of a power flow.

PyPSA writes a result only where it differs from its default: the magnitude
of a voltage where it is not 1 per unit, its angle where it is not zero,
reactive power where it is not zero. What the file lacks has the default.

PyPSA does not record whether a power flow converged. MEME, which runs power
flows through PyPSA, writes that down next to the network, in
`power_flow/convergence.csv`, one row for each snapshot; the document takes
the convergence from there if the file lies next to the network.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np

from coati.results.document import Results
from coati.results.pypsa_network import Component, Network

__all__ = ["RECORD", "Convergence", "describe", "is_power_flow", "read_record"]

#: Where a record of the convergence lies, relative to the directory of the network.
RECORD: Final = Path("power_flow") / "convergence.csv"

# The results of a power flow at a bus; a network that has any of them holds a power flow.
_BUS_RESULTS: Final = ("v_mag_pu", "v_ang", "p", "q")

# The carrier of a bus whose voltage a power flow finds, and PyPSA's default carrier of a bus.
_ALTERNATING: Final = "AC"

_CONVERGED: Final = "converged"
_ITERATIONS: Final = "iterations"
_TRUE: Final = frozenset({"true", "1", "yes"})
_FALSE: Final = frozenset({"false", "0", "no"})


@dataclass
class Convergence:
    """What a record next to the network says about the convergence of a power flow.

    Attributes:
        converged: Whether the power flow converged, for each snapshot.
        iterations: How many iterations each snapshot took, if the record
            says.
    """

    converged: list[bool]
    iterations: list[int] | None = None

    @property
    def failed(self) -> int:
        """The number of snapshots in which the power flow did not converge."""
        return sum(1 for item in self.converged if not item)


def is_power_flow(network: Network) -> bool:
    """Tell whether `network` holds the solution of a power flow.

    A network that has been optimised has an objective; a network that has
    not been solved at all has no results at its buses.
    """
    buses = network.component("buses")
    return network.objective is None and any(name in buses.series for name in _BUS_RESULTS)


def describe(
    results: Results, network: Network, source: Path, reactive: dict[str, np.ndarray[Any, Any]]
) -> None:
    """Say in `results` what the power flow in `network` found.

    Args:
        results: The results, with the capacities, the dispatch and the
            demand of the network already in them.
        network: The network.
        source: The file of the network, next to which a record of the
            convergence may lie.
        reactive: The reactive power that each technology at each location
            supplies, by `location::technology`.
    """
    record, problem = read_record(source, network.snapshots)
    remark = (
        "the network holds the solution of a power flow, not of an optimisation:"
        " the capacities are those given, and the document has no costs"
    )
    if record is None:
        results.termination_condition = "unknown"
        results.success = True
        remark += "; PyPSA does not record whether the power flow converged, and "
        if problem is None:
            remark += f"no record lies next to the file ({RECORD.as_posix()})"
        else:
            remark += f"the record next to the file ({RECORD.as_posix()}) cannot be used: {problem}"
    elif record.failed:
        results.termination_condition = "not_converged"
        results.success = False
        remark += (
            f"; the record next to the file says that the power flow did not converge in"
            f" {record.failed} of {len(record.converged)} snapshots"
        )
    else:
        results.termination_condition = "converged"
        results.success = True
    results.warnings.append(remark)
    results.details["power_flow"] = _details(network, record, reactive)


def read_record(source: Path, snapshots: int) -> tuple[Convergence | None, str | None]:
    """Read the record of the convergence that lies next to the file `source`, if any.

    Returns:
        The record, or `None` with the reason if there is none or it does
        not fit the network: it must have a column `converged` and one row
        for each snapshot.
    """
    path = Path(source).parent / RECORD
    try:
        if not path.is_file():
            return None, None
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return None, f"it cannot be read ({error.__class__.__name__})"
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if _CONVERGED not in (reader.fieldnames or ()):
        return None, "it has no column 'converged'"
    if len(rows) != snapshots:
        return None, f"it has {len(rows)} rows, the network {snapshots} snapshots"
    converged = [_truth(row[_CONVERGED]) for row in rows]
    if None in converged:
        return None, "its column 'converged' is not all true or false"
    iterations = None
    if _ITERATIONS in (reader.fieldnames or ()):
        counted = [_count(row[_ITERATIONS]) for row in rows]
        if None not in counted:
            iterations = [int(item) for item in counted if item is not None]
    return Convergence([bool(item) for item in converged], iterations), None


def _truth(text: str | None) -> bool | None:
    word = (text or "").strip().lower()
    return True if word in _TRUE else False if word in _FALSE else None


def _count(text: str | None) -> int | None:
    word = (text or "").strip()
    return int(word) if word.isdigit() else None


def _details(
    network: Network, record: Convergence | None, reactive: dict[str, np.ndarray[Any, Any]]
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    if record is not None:
        details["converged"] = record.converged
        if record.iterations is not None:
            details["iterations"] = record.iterations
    slack = [bus for bus in network.component("sub_networks").texts("slack_bus") if bus]
    if slack:
        details["slack_buses"] = slack
    magnitude, angle = _voltage(network.component("buses"), network.snapshots)
    if magnitude:
        details["voltage_magnitude"] = magnitude
        details["voltage_angle"] = angle
    if reactive:
        details["reactive_power"] = reactive
    loading = {
        **_loading(network.component("lines"), network.snapshots),
        **_loading(network.component("transformers"), network.snapshots),
    }
    if loading:
        details["branch_loading"] = loading
    return details


def _voltage(
    buses: Component, snapshots: int
) -> tuple[dict[str, np.ndarray[Any, Any]], dict[str, np.ndarray[Any, Any]]]:
    """Return the magnitude and the angle of the voltage of each bus of alternating current."""
    magnitude = buses.varying("v_mag_pu", 1.0, snapshots)
    angle = buses.varying("v_ang", 0.0, snapshots)
    alternating = [
        position
        for position, carrier in enumerate(buses.texts("carrier", _ALTERNATING))
        if carrier == _ALTERNATING
    ]
    return (
        {buses.names[position]: magnitude[:, position] for position in alternating},
        {buses.names[position]: angle[:, position] for position in alternating},
    )


def _loading(branches: Component, snapshots: int) -> dict[str, np.ndarray[Any, Any]]:
    """Return the loading of each branch: the apparent power at its fuller end over its rating."""
    if not len(branches):
        return {}
    apparent = [
        np.hypot(branches.flow(f"p{end}", snapshots), branches.flow(f"q{end}", snapshots))
        for end in (0, 1)
    ]
    with np.errstate(divide="ignore", invalid="ignore"):
        loading = np.maximum(*apparent) / branches.numbers("s_nom", 0.0)
    return {name: loading[:, position] for position, name in enumerate(branches.names)}
