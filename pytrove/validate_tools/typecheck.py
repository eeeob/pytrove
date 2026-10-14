"""Runtime type checking against annotations, through typeguard."""

from __future__ import annotations as _annotations

from typing import Any

try:
    from typeguard import CollectionCheckStrategy, TypeCheckError, check_type, checker_lookup_functions
except ImportError:
    pass

from .._internal._optional import _optional_import
from ..errors import ValidationError
from ._internal import _checker_lookup, HAS_TYPEGUARD


@_optional_import(("typeguard", "typecheck"))
def validate_type(value: Any, annotation: Any) -> None:
    """Check `value` against a type annotation, every item of a collection included.

    Besides typeguard's own rules, an enum accepts any member's value and a
    package `Container[X]` checks each item against `X`.

    Args:
        value: The value to check.
        annotation: The type it must match.

    Raises:
        ValidationError: If it does not match.
    """
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
