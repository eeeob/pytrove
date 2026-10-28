from __future__ import annotations as _annotations

import asyncio
import importlib.util
import sys
from collections import UserString, deque
from collections.abc import Iterator, Sequence
from enum import Enum, IntEnum
from types import UnionType
from typing import Any, Union, get_args

import pytest

import pytrove._internal
from pytrove.typings import Container, ContainerWithoutMapping, MaybeContainer
from pytrove.validate_tools import _internal
from pytrove.validate_tools._internal import (
    _ClassInfo,
    _checker_lookup,
    _flatten_class_info,
    _is_container,
    _is_sub_container,
    _validate_alias,
    _validate_container,
    _validate_enum,
    _ALIAS_TYPES,
    _CONTAINER,
    _CONTAINER_ALIASES,
    _NOT_CONTAINER,
    _TYPECHECK_ACTIVE,
    HAS_TYPEGUARD,
)

needs_typeguard = pytest.mark.skipif(not HAS_TYPEGUARD, reason="needs the typecheck extra")


class _Level(IntEnum):
    """An enum to check values against."""

    LOW = 1
    HIGH = 2


@pytest.fixture
def active() -> Iterator[None]:
    """Run the test as if inside `validate_type`, where `_checker_lookup` answers."""
    token = _TYPECHECK_ACTIVE.set(True)
    yield
    _TYPECHECK_ACTIVE.reset(token)


def test_flatten_class_info_unwraps_unions_and_nested_tuples_in_order() -> None:
    assert _flatten_class_info(int) == (int,)
    assert _flatten_class_info(int | str) == (int, str)
    assert _flatten_class_info((bytes, (int | str, int))) == (bytes, int, str)


def test_flatten_class_info_unwraps_a_typing_union() -> None:
    assert _flatten_class_info(Union[int, str]) == (int, str)  # noqa: UP007 - `typing.Union` is the case under test.
    assert _flatten_class_info((Union[int, str], int | bytes)) == (int, str, bytes)  # noqa: UP007


def test_class_info_alias_names_the_three_shapes() -> None:
    assert isinstance(_ClassInfo, UnionType)
    assert get_args(_ClassInfo) == (type, UnionType, tuple[Any, ...])


def test_is_container_excludes_the_not_container_types() -> None:
    assert _is_container([1])
    assert not _is_container("ab")
    assert not _is_container(UserString("ab"))
    assert not _is_container(_Level)


def test_is_container_takes_dict_views_but_not_awaitables() -> None:
    mapping = {"a": 1}
    assert _is_container(mapping.keys())
    assert _is_container(mapping.values())
    assert _is_container(mapping.items())

    coro = asyncio.sleep(0)
    loop = asyncio.new_event_loop()

    try:
        assert not _is_container(coro)
        assert not _is_container(loop.create_future())
    finally:
        coro.close()
        loop.close()


def test_is_sub_container_takes_container_classes_only() -> None:
    assert _is_sub_container(list)
    assert _is_sub_container(deque)
    assert _is_sub_container(Iterator)
    assert not _is_sub_container(str)
    assert not _is_sub_container(bytes)
    assert not _is_sub_container(_Level)
    assert not _is_sub_container(asyncio.Future)
    assert not _is_sub_container([1])


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


def test_typecheck_active_is_unset_by_default() -> None:
    assert _TYPECHECK_ACTIVE.get() is False


def test_checker_lookup_answers_nothing_outside_validate_type() -> None:
    for origin in (_Level, list, deque, Iterator, Container, ContainerWithoutMapping):
        assert _checker_lookup(origin, ()) is None


@pytest.mark.usefixtures("active")
def test_checker_lookup_answers_only_for_enums_and_containers() -> None:
    assert _checker_lookup(_Level, ()) is _validate_enum
    assert _checker_lookup(list, ()) is _validate_container
    assert _checker_lookup(deque, (int,)) is _validate_container
    assert _checker_lookup(Iterator, (int,)) is _validate_container
    assert _checker_lookup(Container, ()) is _validate_container
    assert _checker_lookup(ContainerWithoutMapping, ()) is _validate_container
    assert _checker_lookup(str, ()) is None
    assert _checker_lookup(int, ()) is None
    assert _checker_lookup(type(Enum), ()) is None


@pytest.mark.usefixtures("active")
@pytest.mark.skipif(not _ALIAS_TYPES, reason="PEP 695 aliases exist from 3.12")
def test_checker_lookup_answers_only_for_a_parametrised_pep_695_alias() -> None:
    assert _checker_lookup(MaybeContainer, (int,)) is _validate_alias
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
    _validate_enum(1, _Level, (), memo)

    with pytest.raises(typeguard.TypeCheckError):
        _validate_enum(9, _Level, (), memo)

    _validate_container([1, 2], Container, (int,), memo)
    _validate_container(["x"], Container, (), memo)
    _validate_container(["x"], Container, (Any,), memo)

    with pytest.raises(typeguard.TypeCheckError, match="is not container"):
        _validate_container("ab", Container, (str,), memo)

    with pytest.raises(typeguard.TypeCheckError, match="item 1"):
        _validate_container([1, "x"], Container, (int,), memo)


@needs_typeguard
def test_the_container_checker_does_not_walk_an_iterator() -> None:
    typeguard = pytest.importorskip("typeguard")
    memo = typeguard.TypeCheckMemo(globals(), locals())
    it = iter(["x", "y"])
    gen = (c for c in "ab")

    _validate_container(it, Iterator, (int,), memo)
    _validate_container(gen, Container, (int,), memo)

    assert list(it) == ["x", "y"]
    assert list(gen) == ["a", "b"]


@needs_typeguard
@pytest.mark.usefixtures("active")
@pytest.mark.skipif(not _ALIAS_TYPES, reason="PEP 695 aliases exist from 3.12")
def test_the_alias_checker_checks_against_the_aliased_type() -> None:
    typeguard = pytest.importorskip("typeguard")
    memo = typeguard.TypeCheckMemo(globals(), locals())

    _validate_alias(1, MaybeContainer, (int,), memo)
    _validate_alias([1], MaybeContainer, (int,), memo)

    with pytest.raises(typeguard.TypeCheckError):
        _validate_alias("x", MaybeContainer, (int,), memo)


@needs_typeguard
def test_has_typeguard_is_false_when_the_installed_typeguard_is_out_of_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def out_of_range(extra: str, distribution: str) -> bool:
        """Report every requirement as unmet, recording what was asked."""
        calls.append((extra, distribution))
        return False

    monkeypatch.setattr(pytrove._internal, "_has_requirement", out_of_range)
    spec = importlib.util.spec_from_file_location(
        # Named inside the package, so its relative imports resolve.
        "pytrove.validate_tools._internal_probe",
        _internal.__file__,
    )
    assert spec is not None
    assert spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    assert probe.HAS_TYPEGUARD is False
    assert calls == [("typecheck", "typeguard")]
