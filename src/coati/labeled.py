"""Numbers along named axes whose positions carry labels.

The results of Calliope are arrays such as `flow_out(nodes, techs, carriers,
timesteps)`. Turning them into a results document takes a few operations on
such arrays: add up along an axis, pick the part that belongs to a label, walk
over the elements that have a value. `LabeledArray` provides these and
nothing else; it is what Coati uses in place of xarray, which it cannot depend
on because the frameworks require versions of xarray that exclude each other.

An element without a value is `NaN`. The reductions skip such elements, and
an all-`NaN` slice reduces to `NaN`, not to zero, so that "no value" does
not turn into "zero" along the way.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from coati import cf
from coati.errors import ExtractionError
from coati.masked import is_masked, mask_of, values_of, with_missing_as
from coati.model import Group, Variable

__all__ = ["LabeledArray", "finite", "labels_of", "numbers_of", "texts_of", "weights_of"]


@dataclass(frozen=True)
class LabeledArray:
    """An array of numbers with a name for each axis and a label for each position.

    Attributes:
        values: The numbers in double precision; `NaN` where there is none.
        dims: The name of each axis.
        labels: The labels along each axis, by the name of the axis.
    """

    values: np.ndarray[Any, Any]
    dims: tuple[str, ...]
    labels: dict[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        if self.values.ndim != len(self.dims):
            raise ValueError(f"{self.values.ndim} axes but {len(self.dims)} names")
        for axis, dim in enumerate(self.dims):
            if len(self.labels[dim]) != self.values.shape[axis]:
                raise ValueError(f"the axis {dim!r} has labels for another length")

    @classmethod
    def read(cls, variable: Variable, group: Group | None = None) -> LabeledArray:
        """Read `variable` with the labels of its dimensions.

        Args:
            variable: A variable of numbers or truth values.
            group: The group whose coordinate variables label the dimensions;
                the positions label a dimension that has none.

        Raises:
            ExtractionError: The variable holds no numbers, or an axis has no dimension.
        """
        decoded = cf.decode(variable)
        if decoded.values.dtype.kind not in "biuf":
            raise ExtractionError(f"{variable.path} holds {decoded.type_name}, not numbers")
        dims: list[str] = []
        labels: dict[str, tuple[str, ...]] = {}
        for axis, dim in enumerate(decoded.dimensions):
            if dim is None:
                raise ExtractionError(f"{variable.path}: the axis {axis} has no dimension")
            dims.append(dim)
            labels[dim] = labels_of(group, dim, decoded.values.shape[axis])
        return cls(_numbers(decoded.values), tuple(dims), labels)

    def axis(self, dim: str) -> int:
        """Return the position of the axis `dim`."""
        try:
            return self.dims.index(dim)
        except ValueError:
            raise ExtractionError(f"no axis {dim!r} among {', '.join(self.dims)}") from None

    def __contains__(self, dim: object) -> bool:
        return dim in self.dims

    def _reduce(self, dims: Sequence[str], values: np.ndarray[Any, Any]) -> LabeledArray:
        kept = tuple(dim for dim in self.dims if dim not in dims)
        return LabeledArray(values, kept, {dim: self.labels[dim] for dim in kept})

    def sum(self, *dims: str) -> LabeledArray:
        """Add up along `dims`. A slice without any value adds up to `NaN`."""
        present = [dim for dim in dims if dim in self.dims]
        if not present:
            return self
        axes = tuple(self.axis(dim) for dim in present)
        empty = np.isnan(self.values).all(axis=axes)
        total = np.where(empty, np.nan, np.nansum(self.values, axis=axes))
        return self._reduce(present, np.asarray(total, dtype=np.float64))

    def max(self, *dims: str) -> LabeledArray:
        """Take the largest value along `dims`; `NaN` for a slice without any value."""
        present = [dim for dim in dims if dim in self.dims]
        if not present:
            return self
        axes = tuple(self.axis(dim) for dim in present)
        empty = np.isnan(self.values).all(axis=axes)
        filled = np.where(np.isnan(self.values), -np.inf, self.values)
        largest = np.where(empty, np.nan, filled.max(axis=axes, initial=-np.inf))
        return self._reduce(present, np.asarray(largest, dtype=np.float64))

    def select(self, dim: str, label: str) -> LabeledArray:
        """Return the part that belongs to `label` on the axis `dim`, without that axis."""
        try:
            position = self.labels[dim].index(label)
        except (KeyError, ValueError):
            raise ExtractionError(f"no {label!r} on the axis {dim!r}") from None
        return self._reduce([dim], np.take(self.values, position, axis=self.axis(dim)))

    def take(self, dim: str, labels: Sequence[str]) -> LabeledArray:
        """Return the part that belongs to `labels` on the axis `dim`, in their order."""
        known = {label: position for position, label in enumerate(self.labels[dim])}
        positions = [known[label] for label in labels if label in known]
        kept = tuple(label for label in labels if label in known)
        values = np.take(self.values, positions, axis=self.axis(dim))
        return LabeledArray(values, self.dims, {**self.labels, dim: kept})

    def scale(self, dim: str, factors: np.ndarray[Any, Any]) -> LabeledArray:
        """Multiply along the axis `dim` by `factors`, one for each position."""
        if dim not in self.dims:
            return self
        shape = [1] * self.values.ndim
        shape[self.axis(dim)] = -1
        return LabeledArray(self.values * np.reshape(factors, shape), self.dims, self.labels)

    def absolute(self) -> LabeledArray:
        """Return the magnitudes."""
        return LabeledArray(np.abs(self.values), self.dims, self.labels)

    def series(self, dim: str) -> np.ndarray[Any, Any]:
        """Add up along all axes but `dim`, counting an element without a value as zero."""
        others = tuple(axis for axis, name in enumerate(self.dims) if name != dim)
        self.axis(dim)
        return np.asarray(np.nansum(self.values, axis=others), dtype=np.float64)

    def items(self) -> Iterator[tuple[tuple[str, ...], float]]:
        """Yield the labels and the value of every element that has a value."""
        if not self.dims:
            if not np.isnan(self.values):
                yield (), float(self.values)
            return
        axes = [self.labels[dim] for dim in self.dims]
        for index in zip(*np.nonzero(~np.isnan(self.values)), strict=True):
            labels = tuple(axes[axis][int(position)] for axis, position in enumerate(index))
            yield labels, float(self.values[index])


def _numbers(values: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Return `values` in double precision with `NaN` for masked elements."""
    if is_masked(values):
        return with_missing_as(values.astype(np.float64), np.nan)
    return np.asarray(values, dtype=np.float64)


def numbers_of(variable: Variable) -> np.ndarray[Any, Any]:
    """Read `variable` as numbers in double precision, `NaN` where it has no value.

    Raises:
        ExtractionError: The variable holds something else than numbers.
    """
    decoded = cf.decode(variable)
    if decoded.values.dtype.kind not in "biuf":
        raise ExtractionError(f"{variable.path} holds {decoded.type_name}, not numbers")
    return _numbers(decoded.values)


def finite(values: np.ndarray[Any, Any], nan: float = 0.0) -> np.ndarray[Any, Any]:
    """Return `values` with `nan` in place of every `NaN`."""
    return np.asarray(np.nan_to_num(values, nan=nan))


def weights_of(variable: Variable | None, length: int) -> np.ndarray[Any, Any]:
    """Return how much each of `length` times counts: one unless `variable` says otherwise."""
    if variable is None or variable.shape != (length,):
        return np.ones(length)
    return finite(numbers_of(variable), nan=1.0)


def texts_of(variable: Variable) -> list[str | None]:
    """Read `variable` as a flat list of texts; `None` where it has no value.

    Numbers and times are written as text; an empty text and the texts that
    the frameworks write for a missing value count as no value.
    """
    decoded = cf.decode(variable)
    values = decoded.values
    hidden = mask_of(values).ravel() if is_masked(values) else None
    data = values_of(values)
    if data.dtype.kind == "M":
        data = _instants(data)
    texts: list[str | None] = []
    for position, item in enumerate(data.ravel().tolist()):
        if (hidden is not None and hidden[position]) or item is None:
            texts.append(None)
            continue
        text = item.decode("utf-8", "replace") if isinstance(item, bytes) else str(item)
        texts.append(None if text in _MISSING_TEXTS else text)
    return texts


# What the frameworks write where a text is missing.
_MISSING_TEXTS = frozenset({"", "nan", "NaN", "<NA>", "None", "NaT"})


def _instants(data: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Write instants as ISO 8601 text with a resolution of one second."""
    text = np.datetime_as_string(data.astype("datetime64[s]")).astype(object)
    text[np.isnat(data)] = None
    return np.asarray(text)


def labels_of(group: Group | None, dim: str, size: int) -> tuple[str, ...]:
    """Return the labels of the dimension `dim`.

    Args:
        group: The group whose coordinate variable of the name `dim`, or
            that of an enclosing group, holds the labels.
        dim: The name of the dimension.
        size: The length of the dimension.

    Returns:
        The labels; the positions as text if there is no coordinate variable
        or if it does not fit the dimension.
    """
    node = group
    while node is not None:
        coordinate = node.variables.get(dim)
        if (
            coordinate is not None
            and coordinate.shape == (size,)
            and coordinate.dimensions in ((dim,), (None,))
        ):
            return tuple(
                text if text is not None else str(position)
                for position, text in enumerate(texts_of(coordinate))
            )
        node = node.parent
    return tuple(str(position) for position in range(size))
