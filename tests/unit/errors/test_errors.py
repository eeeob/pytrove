from __future__ import annotations as _annotations

import pytest

import pytrove.errors
from pytrove.errors import ArchiveLimitError, ArchivePolicyError, UtilError, ValidationError


def test_the_entry_point_exports_every_error() -> None:
    assert set(pytrove.errors.__all__) == {
        "UtilError",
        "ValidationError",
        "ArchiveLimitError",
        "ArchivePolicyError",
    }


def test_util_error_is_a_plain_exception() -> None:
    assert issubclass(UtilError, Exception)
    assert not issubclass(UtilError, ValueError)


@pytest.mark.parametrize("error", [ValidationError, ArchiveLimitError, ArchivePolicyError])
def test_every_specific_error_is_both_a_util_error_and_a_value_error(
    error: type[Exception],
) -> None:
    assert issubclass(error, UtilError)
    assert issubclass(error, ValueError)


@pytest.mark.parametrize(
    "error", [UtilError, ValidationError, ArchiveLimitError, ArchivePolicyError]
)
def test_every_error_carries_its_message(error: type[Exception]) -> None:
    msg = "boom"
    with pytest.raises(error, match=msg):
        raise error(msg)


def test_a_validation_error_is_caught_as_a_value_error() -> None:
    with pytest.raises(ValueError):
        raise ValidationError
