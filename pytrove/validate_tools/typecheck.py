"""Runtime type checking against annotations, through typeguard."""

from __future__ import annotations as _annotations

from typing import Any

try:
    from typeguard import (  # type: ignore[import-not-found]  # Optional: the `typecheck` extra.
        CollectionCheckStrategy,
        TypeCheckError,
        check_type,
        checker_lookup_functions,
    )
except ImportError:
    pass

from .._internal import _optional_import
from ..errors import ValidationError
from ._internal import _checker_lookup, _is_container, _CONTAINER_ALIASES, HAS_TYPEGUARD


@_optional_import(("typeguard", "typecheck"))
def validate_type(value: Any, annotation: Any) -> None:
    """Check `value` against a type annotation, every item of a collection included.

    Besides typeguard's own rules, an enum accepts any member's value and a
    package `Container[X]` checks each item against `X`. Before Python 3.12
    the aliases are plain unions typeguard expands itself, so a `str` passes as
    a `Sequence` there, and `NestedContainer` is checked one level deep only:
    its recursive reference is a string typeguard cannot resolve, and it warns.
    A bare `Container` or `ContainerWithoutMapping` rejects a `NotContainer`
    such as `str` on every version.

    Args:
        value: The value to check.
        annotation: The type it must match.

    Raises:
        ValidationError: If it does not match.
    """
    # typeguard expands a bare alias before `_checker_lookup` sees it, so the package rule is applied here.
    if annotation in _CONTAINER_ALIASES and not _is_container(value):
        msg = f"{type(value).__name__} is not container"
        raise ValidationError(msg)

    try:
        check_type(
            value,
            annotation,
            typecheck_fail_callback=None,
            collection_check_strategy=CollectionCheckStrategy.ALL_ITEMS,
        )
    except TypeCheckError as exc:
        raise ValidationError(str(exc)) from exc


if HAS_TYPEGUARD:
    checker_lookup_functions.append(_checker_lookup)


__all__ = ("validate_type",)
