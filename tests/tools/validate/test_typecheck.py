from __future__ import annotations as _annotations

from enum import IntEnum
from typing import Any

import pytest

from pytrove.errors import ValidationError
from pytrove.typings import Container, NestedContainer
from pytrove.validate_tools import validate_type
from pytrove.validate_tools._internal import _checker_lookup, _ALIAS_TYPES, HAS_TYPEGUARD

needs_typeguard = pytest.mark.skipif(not HAS_TYPEGUARD, reason="needs the typecheck extra")


class _Level(IntEnum):
    """An enum to check values against."""

    LOW = 1
    HIGH = 2


@needs_typeguard
def test_validate_type_accepts_a_matching_value() -> None:
    assert validate_type([1, 2], list[int]) is None


@needs_typeguard
def test_validate_type_wraps_a_mismatch_in_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        validate_type([1, "x"], list[int])


@needs_typeguard
def test_validate_type_accepts_an_enums_value_not_only_its_member() -> None:
    validate_type(2, _Level)

    with pytest.raises(ValidationError):
        validate_type(9, _Level)


@needs_typeguard
def test_the_checker_is_registered_with_typeguard() -> None:
    checker_lookup_functions = pytest.importorskip("typeguard").checker_lookup_functions
    assert _checker_lookup in checker_lookup_functions


@needs_typeguard
def test_nested_container_validation_recurses() -> None:
    validate_type([1, [2, 3]], NestedContainer[int])


@needs_typeguard
def test_validate_type_accepts_any_for_an_unparametrised_container() -> None:
    value: Any = [object(), "x"]
    validate_type(value, Container)


@needs_typeguard
def test_validate_type_checks_every_item_of_a_package_container() -> None:
    validate_type((1, 2, 3), Container[int])

    with pytest.raises(ValidationError):
        validate_type((1, "x"), Container[int])


@needs_typeguard
@pytest.mark.skipif(
    not _ALIAS_TYPES, reason="before 3.12 typeguard expands the aliases as plain unions"
)
def test_validate_type_applies_the_package_container_rules_to_aliases() -> None:
    with pytest.raises(ValidationError):
        validate_type("abc", Container[str])

    with pytest.raises(ValidationError):
        validate_type([1, ["x"]], NestedContainer[int])


@needs_typeguard
@pytest.mark.skipif(not _ALIAS_TYPES, reason="PEP 695 aliases exist from 3.12")
def test_validate_type_checks_a_plain_pep_695_alias() -> None:
    from typing import TypeAliasType  # noqa: PLC0415 - exists only from 3.12, the branch under test

    # typeguard itself checks a plain alias; `_checker_lookup` does not answer for it.
    plain = TypeAliasType("Plain", int)
    validate_type(1, plain)

    with pytest.raises(ValidationError):
        validate_type("x", plain)


@needs_typeguard
@pytest.mark.skipif(not _ALIAS_TYPES, reason="PEP 695 aliases exist from 3.12")
def test_validate_type_checks_a_parametrised_pep_695_alias() -> None:
    from typing import TypeAliasType, TypeVar  # noqa: PLC0415 - `TypeAliasType` exists only from 3.12

    t = TypeVar("t")
    pair = TypeAliasType("Pair", tuple[t, t], type_params=(t,))
    validate_type((1, 2), pair[int])

    with pytest.raises(ValidationError):
        validate_type(("x", "y"), pair[int])


@pytest.mark.skipif(HAS_TYPEGUARD, reason="the typecheck extra is installed")
def test_validate_type_names_the_typecheck_extra_when_typeguard_is_missing() -> None:
    with pytest.raises(ImportError, match=r"pytrove\[typecheck\]"):
        validate_type(1, int)
