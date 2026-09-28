"""Arrays in which values may be missing.

A masked array of NumPy holds values and, for each of them, whether it is
missing. The readers return one where a file marks values as missing and the
type of the values has no value that could say so, as the integers have none.

The functions here are those of `numpy.ma` that the package uses, with the
types of what they return. NumPy declares these types from version 2.3 on,
which the oldest Python that the package supports cannot install.
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np

__all__ = ["all_missing", "is_masked", "mask_of", "masked", "values_of", "with_missing_as"]

_ma: Any = np.ma


def is_masked(values: Any) -> bool:
    """Tell whether `values` is an array in which values may be missing."""
    return isinstance(values, np.ma.MaskedArray)


def mask_of(values: Any) -> np.ndarray[Any, Any]:
    """Return which of the values are missing, in the shape of `values`."""
    return np.asarray(_ma.getmaskarray(values), dtype=np.bool_)


def values_of(values: Any) -> np.ndarray[Any, Any]:
    """Return the values; what stands in the place of a missing one is not defined."""
    return np.asarray(_ma.getdata(values))


def masked(values: Any, missing: Any) -> np.ndarray[Any, Any]:
    """Return an array of `values` of which those that `missing` marks are missing."""
    return cast("np.ndarray[Any, Any]", _ma.MaskedArray(values, mask=missing))


def all_missing(shape: tuple[int, ...], dtype: Any) -> np.ndarray[Any, Any]:
    """Return an array of the given shape and type, all of whose values are missing."""
    return cast("np.ndarray[Any, Any]", _ma.masked_all(shape, dtype=dtype))


def with_missing_as(values: Any, value: Any) -> np.ndarray[Any, Any]:
    """Return the values with `value` in the place of those that are missing."""
    return np.asarray(_ma.filled(values, value))
