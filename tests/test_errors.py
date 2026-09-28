"""The errors of the package."""

from __future__ import annotations

import pytest

import coati
from coati import errors
from coati.errors import CoatiError


@pytest.mark.parametrize("name", [name for name in errors.__all__ if name != "CoatiError"])
def test_errors_are_of_one_family(name: str) -> None:
    error = getattr(errors, name)
    assert issubclass(error, CoatiError)
    assert error.__doc__
    assert getattr(coati, name) is error
    with pytest.raises(CoatiError, match="what is wrong"):
        raise error("what is wrong")


def test_the_family_is_one_of_exceptions() -> None:
    assert issubclass(CoatiError, Exception)
    assert not issubclass(CoatiError, OSError)
    assert coati.CoatiError is CoatiError


def test_the_package_states_its_version() -> None:
    assert isinstance(coati.__version__, str)
    assert coati.__version__[0].isdigit()
