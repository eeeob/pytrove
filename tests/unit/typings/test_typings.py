from __future__ import annotations as _annotations

import os
import threading
from collections.abc import Awaitable, Callable, Collection, Hashable, Iterator, Reversible, Sequence, Set
from enum import Enum
from typing import Any, Literal, ParamSpec, TypeVar, get_args, get_origin, get_type_hints

import pytest

import pytrove.typings
from pytrove.enums import ArchiveDuplicatePolicy, ArchiveLinkPolicy, ArchiveOverwritePolicy
from pytrove.typings import (
    ArchiveLimits,
    Container,
    ContainerWithoutMapping,
    CountryInfo,
    JsonValue,
    LockProtocol,
    MaybeList,
    NestedContainer,
    NotContainer,
    PathLike,
    TemplateDict,
    TemplatePyroMessage,
    _CT,
    _EnumT,
    _ExcT,
    _False,
    _FT,
    _KT,
    _P,
    _T,
    _True,
    _VT,
)
from pytrove.typings import archive, core, template

CONTAINER_ORIGINS = [Sequence, Set, Collection, Reversible, Iterator]


def _value(alias: Any) -> Any:
    """Unwrap a PEP 695 alias (3.12+) to the union it stands for."""
    return getattr(alias, "__value__", alias)


def test_the_entry_point_is_the_union_of_its_modules() -> None:
    assert pytrove.typings.__all__ == (*archive.__all__, *core.__all__, *template.__all__)
    assert all(hasattr(pytrove.typings, name) for name in pytrove.typings.__all__)


def test_every_template_type_is_prefixed() -> None:
    assert all(name.startswith("Template") for name in template.__all__)


@pytest.mark.parametrize("alias", [Container, ContainerWithoutMapping])
def test_container_aliases_keep_the_member_order(alias: Any) -> None:
    assert [get_origin(a) or a for a in get_args(_value(alias))] == CONTAINER_ORIGINS


def test_not_container_lists_the_iterables_read_as_single_values() -> None:
    assert set(get_args(NotContainer)) == {bytearray, bytes, str, memoryview, type(Enum), Awaitable}


def test_recursive_aliases_can_be_subscripted() -> None:
    assert MaybeList[int] is not None
    assert NestedContainer[int] is not None


def test_json_value_covers_the_json_types() -> None:
    members = [get_origin(a) or a for a in get_args(_value(JsonValue))]
    assert {str, bool, int, float, type(None), list, dict} <= set(members)


def test_path_like_accepts_strings_bytes_and_os_paths() -> None:
    assert set(get_args(PathLike)) == {str, bytes, os.PathLike[str], os.PathLike[bytes]}


def test_type_variables_carry_their_bounds() -> None:
    assert isinstance(_P, ParamSpec)
    bounds = {_T: None, _VT: None, _KT: Hashable, _CT: type, _FT: Callable[..., Any], _ExcT: BaseException, _EnumT: Enum}
    for var, bound in bounds.items():
        assert isinstance(var, TypeVar)
        assert var.__bound__ == bound


def test_boolean_literals() -> None:
    assert _True == Literal[True]
    assert _False == Literal[False]


def test_a_threading_lock_satisfies_lock_protocol() -> None:
    lock: LockProtocol = threading.Lock()
    assert lock.acquire() is True
    lock.release()
    assert {"acquire", "release"} <= set(dir(LockProtocol))


def test_country_info_fields() -> None:
    assert get_type_hints(CountryInfo) == {"cc": int, "rc": str, "flag": str, "name": str}


def test_archive_limits_defaults_cap_nothing_and_refuse_links() -> None:
    limits = ArchiveLimits()
    assert limits[:8] == (None,) * 8
    assert limits.symlinks is ArchiveLinkPolicy.ERROR
    assert limits.hardlinks is ArchiveLinkPolicy.ERROR
    assert limits.overwrite is ArchiveOverwritePolicy.OVERWRITE
    assert limits.duplicates is ArchiveDuplicatePolicy.SKIP


def test_archive_limits_compare_and_hash_by_value() -> None:
    assert ArchiveLimits(max_files=3) == ArchiveLimits(max_files=3)
    assert hash(ArchiveLimits(max_files=3)) == hash(ArchiveLimits(max_files=3))


def test_permissive_limits_allow_links_and_keep_other_fields() -> None:
    limits = ArchiveLimits.permissive(max_files=5)
    assert limits.symlinks is ArchiveLinkPolicy.ALLOW
    assert limits.hardlinks is ArchiveLinkPolicy.ALLOW
    assert limits.max_files == 5


@pytest.mark.parametrize("typed_dict", [TemplateDict, TemplatePyroMessage])
def test_template_dict_keys_are_all_declared_optional(typed_dict: type) -> None:
    # The annotations are deferred strings (rule 4.2), so `__required_keys__` cannot be trusted on every version.
    annotations = [getattr(v, "__forward_arg__", v) for v in typed_dict.__annotations__.values()]
    assert annotations
    assert all(v.startswith("NotRequired[") for v in annotations)
