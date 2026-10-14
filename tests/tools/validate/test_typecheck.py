from __future__ import annotations as _annotations

from enum import Enum, IntEnum
from typing import Any

import pytest
from typeguard import checker_lookup_functions

from pytrove.errors import ValidationError
from pytrove.typings import Container, NestedContainer
from pytrove.validate_tools import validate_type
from pytrove.validate_tools._internal import (
    _ClassInfo,
    _checker_lookup,
    _flatten_class_info,
    _is_container,
    _CONTAINER,
    _NOT_CONTAINER,
    HAS_TYPEGUARD,
)


class _Level(IntEnum):
    """An enum to check values against."""

    LOW = 1
    HIGH = 2


def test_validate_type_accepts_a_matching_value() -> None:
    assert validate_type([1, 2], list[int]) is None


def test_validate_type_wraps_a_mismatch_in_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        validate_type([1, "x"], list[int])


def test_validate_type_accepts_an_enums_value_not_only_its_member() -> None:
    validate_type(2, _Level)

    with pytest.raises(ValidationError):
        validate_type(9, _Level)


def test_the_checker_is_registered_with_typeguard() -> None:
    assert HAS_TYPEGUARD
    assert _checker_lookup in checker_lookup_functions


def test_checker_lookup_answers_only_for_enums_and_containers() -> None:
    assert _checker_lookup(_Level) is not None
    assert _checker_lookup(list) is not None
    assert _checker_lookup(str) is None
    assert _checker_lookup(int) is None


def test_flatten_class_info_unwraps_unions_and_nested_tuples_in_order() -> None:
    assert _flatten_class_info(int) == (int,)
    assert _flatten_class_info(int | str) == (int, str)
    assert _flatten_class_info((bytes, (int | str, int))) == (bytes, int, str)


def test_class_info_alias_names_the_three_shapes() -> None:
    assert _ClassInfo is not None


def test_is_container_excludes_the_not_container_types() -> None:
    assert _is_container([1])
    assert not _is_container("ab")
    assert not _is_container(_Level)


def test_container_tuples_hold_classes() -> None:
    assert all(isinstance(t, type) for t in (*_CONTAINER, *_NOT_CONTAINER))
    assert str in _NOT_CONTAINER
    assert isinstance(Enum, tuple(type(t) for t in _NOT_CONTAINER if t is type(Enum)))


def test_nested_container_validation_recurses() -> None:
    validate_type([1, [2, 3]], NestedContainer[int])


def test_validate_type_accepts_any_for_an_unparametrised_container() -> None:
    value: Any = [object(), "x"]
    validate_type(value, Container)
