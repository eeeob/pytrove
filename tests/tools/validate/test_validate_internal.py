from __future__ import annotations as _annotations

import sys
from collections import UserString
from collections.abc import Sequence
from enum import Enum, IntEnum
from typing import Any

import pytest

from pytrove.typings import Container, ContainerWithoutMapping, MaybeContainer
from pytrove.validate_tools._internal import (
    _ClassInfo,
    _checker_lookup,
    _flatten_class_info,
    _is_container,
    _ALIAS_TYPES,
    _CONTAINER,
    _CONTAINER_ALIASES,
    _NOT_CONTAINER,
    HAS_TYPEGUARD,
)

needs_typeguard = pytest.mark.skipif(not HAS_TYPEGUARD, reason="needs the typecheck extra")


class _Level(IntEnum):
    """An enum to check values against."""

    LOW = 1
    HIGH = 2


def test_flatten_class_info_unwraps_unions_and_nested_tuples_in_order() -> None:
    assert _flatten_class_info(int) == (int,)
    assert _flatten_class_info(int | str) == (int, str)
    assert _flatten_class_info((bytes, (int | str, int))) == (bytes, int, str)


def test_class_info_alias_names_the_three_shapes() -> None:
    assert _ClassInfo is not None


def test_is_container_excludes_the_not_container_types() -> None:
    assert _is_container([1])
    assert not _is_container("ab")
    assert not _is_container(UserString("ab"))
    assert not _is_container(_Level)


def test_container_tuples_hold_classes() -> None:
    assert all(isinstance(t, type) for t in (*_CONTAINER, *_NOT_CONTAINER))
    assert Sequence in _CONTAINER
    assert str in _NOT_CONTAINER
    assert type(Enum) in _NOT_CONTAINER
    assert UserString in _NOT_CONTAINER
    assert _CONTAINER_ALIASES == (Container, ContainerWithoutMapping)


def test_alias_types_exist_only_from_python_312() -> None:
    if sys.version_info >= (3, 12):
        from typing import TypeAliasType  # noqa: PLC0415 - exists only from 3.12, the branch under test

        assert _ALIAS_TYPES == (TypeAliasType,)
    else:
        assert _ALIAS_TYPES == ()


@needs_typeguard
def test_checker_lookup_answers_only_for_enums_and_containers() -> None:
    assert _checker_lookup(_Level, ()).__name__ == "validate_enum"
    assert _checker_lookup(list, ()).__name__ == "validate_container"
    assert _checker_lookup(Container, ()).__name__ == "validate_container"
    assert _checker_lookup(ContainerWithoutMapping, ()).__name__ == "validate_container"
    assert _checker_lookup(str, ()) is None
    assert _checker_lookup(int, ()) is None
    assert _checker_lookup(type(Enum), ()) is None


@needs_typeguard
@pytest.mark.skipif(not _ALIAS_TYPES, reason="PEP 695 aliases exist from 3.12")
def test_checker_lookup_answers_only_for_a_parametrised_pep_695_alias() -> None:
    assert _checker_lookup(MaybeContainer, (int,)).__name__ == "validate_alias"
    assert _checker_lookup(MaybeContainer, ()) is None


@needs_typeguard
def test_the_checkers_enforce_their_rules() -> None:
    typeguard = pytest.importorskip("typeguard")
    memo = typeguard.TypeCheckMemo(
        globals(),
        locals(),
        config=typeguard.TypeCheckConfiguration(
            collection_check_strategy=typeguard.CollectionCheckStrategy.ALL_ITEMS,
        ),
    )
    validate_enum = _checker_lookup(_Level, ())
    validate_container = _checker_lookup(list, ())

    validate_enum(1, _Level, (), memo)

    with pytest.raises(typeguard.TypeCheckError):
        validate_enum(9, _Level, (), memo)

    validate_container([1, 2], Container, (int,), memo)
    validate_container(["x"], Container, (), memo)
    validate_container(["x"], Container, (Any,), memo)

    with pytest.raises(typeguard.TypeCheckError, match="is not container"):
        validate_container("ab", Container, (str,), memo)

    with pytest.raises(typeguard.TypeCheckError, match="item 1"):
        validate_container([1, "x"], Container, (int,), memo)


@needs_typeguard
@pytest.mark.skipif(not _ALIAS_TYPES, reason="PEP 695 aliases exist from 3.12")
def test_the_alias_checker_checks_against_the_aliased_type() -> None:
    typeguard = pytest.importorskip("typeguard")
    memo = typeguard.TypeCheckMemo(globals(), locals())
    validate_alias = _checker_lookup(MaybeContainer, (int,))

    validate_alias(1, MaybeContainer, (int,), memo)
    validate_alias([1], MaybeContainer, (int,), memo)

    with pytest.raises(typeguard.TypeCheckError):
        validate_alias("x", MaybeContainer, (int,), memo)


@pytest.mark.skipif(HAS_TYPEGUARD, reason="the typecheck extra is installed")
def test_checker_lookup_names_the_typecheck_extra_when_typeguard_is_missing() -> None:
    with pytest.raises(ImportError, match=r"pytrove\[typecheck\]"):
        _checker_lookup(list, ())
