from __future__ import annotations as _annotations

from collections import deque
from collections.abc import Iterator
from enum import Flag, IntEnum
from typing import Any

import pytest

from pytrove.errors import ValidationError
from pytrove.typings import Container, ContainerWithoutMapping, NestedContainer
from pytrove.validate_tools import validate_type
from pytrove.validate_tools._internal import (
    _checker_lookup,
    _ALIAS_TYPES,
    _TYPECHECK_ACTIVE,
    HAS_TYPEGUARD,
)

needs_typeguard = pytest.mark.skipif(not HAS_TYPEGUARD, reason="needs the typecheck extra")


class _Level(IntEnum):
    """An enum to check values against."""

    LOW = 1
    HIGH = 2


class _Other(IntEnum):
    """An unrelated enum whose member equals one of `_Level`'s values."""

    ONE = 1


class _Perm(Flag):
    """A flag, whose members combine into composite values."""

    READ = 1
    WRITE = 2


@needs_typeguard
def test_validate_type_accepts_a_matching_value() -> None:
    assert validate_type([1, 2], list[int]) is None


@needs_typeguard
def test_validate_type_wraps_a_mismatch_in_a_validation_error() -> None:
    typeguard = pytest.importorskip("typeguard")

    with pytest.raises(ValidationError, match="item 1 of list is not an instance of int") as caught:
        validate_type([1, "x"], list[int])

    assert isinstance(caught.value.__cause__, typeguard.TypeCheckError)


@needs_typeguard
def test_validate_type_sets_the_scope_flag_only_while_it_runs() -> None:
    assert _TYPECHECK_ACTIVE.get() is False

    with pytest.raises(ValidationError):
        validate_type("x", int)

    assert _TYPECHECK_ACTIVE.get() is False


@needs_typeguard
def test_typeguard_outside_validate_type_keeps_its_own_rules() -> None:
    typeguard = pytest.importorskip("typeguard")

    # Inside `validate_type` a value passes for its enum; a plain `check_type` still wants a member.
    with pytest.raises(typeguard.TypeCheckError):
        typeguard.check_type(1, _Level)

    typeguard.check_type(_Level.LOW, _Level)


@needs_typeguard
def test_validate_type_leaves_an_iterator_intact() -> None:
    it = iter([1, 2, 3])
    validate_type(it, Iterator[int])
    assert list(it) == [1, 2, 3]


@needs_typeguard
def test_validate_type_leaves_a_generator_intact_for_a_package_container() -> None:
    gen = (i for i in range(3))
    validate_type(gen, Container[int])
    assert list(gen) == [0, 1, 2]


@needs_typeguard
def test_validate_type_checks_a_deque_item_by_item() -> None:
    validate_type(deque([1, 2]), deque[int])

    with pytest.raises(ValidationError, match="item 0"):
        validate_type(deque(["x"]), deque[int])


@needs_typeguard
def test_validate_type_accepts_an_enums_value_not_only_its_member() -> None:
    validate_type(2, _Level)

    with pytest.raises(ValidationError):
        validate_type(9, _Level)


@needs_typeguard
def test_validate_type_accepts_an_equal_member_of_another_enum() -> None:
    # The check is by value: `_Other.ONE == 1`, which is `_Level.LOW`'s value.
    validate_type(_Other.ONE, _Level)


@needs_typeguard
def test_validate_type_accepts_a_composite_flag_value() -> None:
    validate_type(3, _Perm)

    with pytest.raises(ValidationError):
        validate_type(8, _Perm)


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
@pytest.mark.parametrize("alias", [Container, ContainerWithoutMapping])
@pytest.mark.parametrize("value", [[1], (1,), {1}, {"a": 1}])
def test_validate_type_accepts_a_container_for_a_bare_alias(alias: Any, value: Any) -> None:
    validate_type(value, alias)


@needs_typeguard
@pytest.mark.parametrize("alias", [Container, ContainerWithoutMapping])
@pytest.mark.parametrize("value", ["abc", b"x"])
def test_validate_type_follows_the_annotation_for_a_bare_alias(alias: Any, value: Any) -> None:
    # A `str` or `bytes` is the `Sequence` the expanded alias names; `is_container` is what excludes it.
    validate_type(value, alias)


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


@needs_typeguard
@pytest.mark.skipif(
    bool(_ALIAS_TYPES), reason="from 3.12 the aliases are PEP 695 and fully checked"
)
def test_validate_type_checks_a_nested_container_one_level_deep_before_312() -> None:
    typeguard = pytest.importorskip("typeguard")

    with pytest.warns(typeguard.TypeHintWarning, match="NestedContainer"):
        validate_type([1, ["x"]], NestedContainer[int])


@pytest.mark.skipif(HAS_TYPEGUARD, reason="the typecheck extra is installed")
def test_validate_type_names_the_typecheck_extra_when_typeguard_is_missing() -> None:
    with pytest.raises(ImportError, match=r"pytrove\[typecheck\]"):
        validate_type(1, int)
