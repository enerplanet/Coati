"""The choices a caller has when a results document is made."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from coati.errors import CoatiError

__all__ = ["ExtractOptions", "parse_duration", "parse_instant", "synthesize_timestamps"]

_DURATION: Final = re.compile(r"^\s*(?P<count>\d+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z]+)\s*$")

_SECONDS: Final = {
    **dict.fromkeys(("s", "sec", "secs", "second", "seconds"), 1.0),
    **dict.fromkeys(("min", "mins", "minute", "minutes", "t"), 60.0),
    **dict.fromkeys(("h", "hr", "hrs", "hour", "hours"), 3600.0),
    **dict.fromkeys(("d", "day", "days"), 86400.0),
}


@dataclass(frozen=True)
class ExtractOptions:
    """The choices a caller has when a results document is made.

    Attributes:
        labels: Whether the display name and the colour of a technology are
            reported, where the file has them.
        period: The investment period to report, for a file of AdOpT-NET0
            with several; the first if `None`.
        time_start: The first instant of a model whose file records no
            times, as ISO 8601 text. Together with `time_step` it makes
            the timestamps instants instead of positions.
        time_step: The distance between two instants, such as `1h` or `15min`.
    """

    labels: bool = True
    period: str | None = None
    time_start: str | None = None
    time_step: str | None = None

    def __post_init__(self) -> None:
        if (self.time_start is None) != (self.time_step is None):
            raise CoatiError("time_start and time_step must be given together")
        if self.time_start is not None and self.time_step is not None:
            parse_instant(self.time_start)
            parse_duration(self.time_step)


def parse_duration(text: str) -> int:
    """Return the length of a duration such as `15min` in microseconds.

    Raises:
        CoatiError: The text is no duration, or the duration is not positive.
    """
    match = _DURATION.match(text)
    seconds = _SECONDS.get(match["unit"].lower()) if match else None
    if match is None or seconds is None:
        raise CoatiError(f"{text!r} is not a duration; expected for example 1h, 30min or 1d")
    length = round(float(match["count"]) * seconds * 1_000_000)
    if length <= 0:
        raise CoatiError(f"{text!r}: a time step must be longer than zero")
    return length


def parse_instant(text: str) -> np.datetime64:
    """Return the instant that ISO 8601 text such as `2025-01-01T00:00` names.

    Raises:
        CoatiError: The text names no instant.
    """
    try:
        instant = np.datetime64(text.strip().replace(" ", "T"), "us")
    except ValueError:
        instant = None
    if instant is None or np.isnat(instant):
        raise CoatiError(f"{text!r} is not a time; expected for example 2025-01-01T00:00")
    return instant


def synthesize_timestamps(options: ExtractOptions, length: int) -> Any:
    """Return the timestamps of a model whose file records no times.

    Returns:
        Instants that start at `options.time_start` and are
        `options.time_step` apart, or the positions if these are not given.
    """
    if options.time_start is None or options.time_step is None:
        return list(range(length))
    start = parse_instant(options.time_start)
    step = np.timedelta64(parse_duration(options.time_step), "us")
    return start + np.arange(length) * step
