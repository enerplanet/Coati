"""Arrays in which values may be missing."""

from __future__ import annotations

import numpy as np

from coati.masked import all_missing, is_masked, mask_of, masked, values_of, with_missing_as


def test_an_array_with_missing_values() -> None:
    array = masked([1, 2, 3], [False, True, False])
    assert is_masked(array)
    assert mask_of(array).tolist() == [False, True, False]
    assert values_of(array).tolist() == [1, 2, 3]
    assert not is_masked(values_of(array))
    assert with_missing_as(array, -1).tolist() == [1, -1, 3]


def test_an_array_without_missing_values() -> None:
    array = np.array([1.5, 2.5])
    assert not is_masked(array)
    assert mask_of(array).tolist() == [False, False]
    assert mask_of(array).dtype == np.bool_
    assert values_of(array) is array
    assert with_missing_as(array, 0.0).tolist() == [1.5, 2.5]


def test_a_mask_that_is_not_spelled_out() -> None:
    array = np.ma.MaskedArray([1, 2])
    assert array.mask is np.ma.nomask
    assert mask_of(array).tolist() == [False, False]


def test_an_array_of_missing_values_alone() -> None:
    array = all_missing((2, 3), np.int16)
    assert is_masked(array)
    assert array.shape == (2, 3)
    assert array.dtype == np.int16
    assert mask_of(array).all()
    nothing = all_missing((), np.float64)
    assert nothing.shape == ()
    assert bool(mask_of(nothing))
