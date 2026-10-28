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
from ._internal import _checker_lookup, _TYPECHECK_ACTIVE, HAS_TYPEGUARD


@_optional_import("typecheck")
def validate_type(value: Any, annotation: Any) -> None:
    """Check `value` against a type annotation, every item of a collection included.

    Besides typeguard's own rules, an enum accepts any member's value and a
    package `Container[X]` checks each item against `X`. Before Python 3.12
    the aliases are plain unions typeguard expands itself, so a `str` passes as
    a `Sequence` there, and `NestedContainer` is checked one level deep only:
    its recursive reference is a string typeguard cannot resolve, and it warns.

    The check follows the annotation, not the package's container rule: a bare
    `Container` is expanded by typeguard into its union, so a `str` passes as
    the `Sequence` it is. To exclude strings, bytes and the other `NotContainer`
    types, test the value with `is_container`.

    An iterator or generator is checked for its kind only, never walked, so it
    is left intact for the caller. These rules apply inside this call only: a
    plain `typeguard.check_type` elsewhere in the process keeps typeguard's own.

    Args:
        value: The value to check.
        annotation: The type it must match.

    Raises:
        ValidationError: If it does not match.
    """
    token = _TYPECHECK_ACTIVE.set(True)

    try:
        check_type(
            value,
            annotation,
            typecheck_fail_callback=None,
            collection_check_strategy=CollectionCheckStrategy.ALL_ITEMS,
        )
    except TypeCheckError as exc:
        raise ValidationError(str(exc)) from exc
    finally:
        _TYPECHECK_ACTIVE.reset(token)


if HAS_TYPEGUARD:
    checker_lookup_functions.append(_checker_lookup)


__all__ = ("validate_type",)
