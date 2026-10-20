"""The fallback values and render conditions every compiled template part shares."""

from __future__ import annotations as _annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...iter_tools import to_frozenset
from ...typings import JsonValue
from ..base import BaseDataClass
from ._internal import _chain_mappings


@dataclass(slots=True)
class CompiledDefaults(BaseDataClass):
    """Base for every compiled part that can carry its own fallback values."""

    default_keys: dict[str, JsonValue] | None = None
    """Values for keys the caller did not pass to `format()`; a passed value always wins."""

    def with_defaults(self, kw: Mapping[str, Any]) -> Mapping[str, Any]:
        """Layer `default_keys` beneath `kw`, so a value the caller passed always wins.

        Args:
            kw: The `format()` keyword arguments.

        Returns:
            `kw` with the defaults beneath it, or `kw` itself if there are none.
        """
        return _chain_mappings(kw, defaults) if (defaults := self.default_keys) else kw


@dataclass(slots=True)
class CompiledConditional(CompiledDefaults):
    """Base for every compiled part that can opt out of being rendered.

    A part renders only when every `all_of` key and at least one `any_of`
    key is present in the `format()` keyword arguments; a part setting
    neither always renders. `default_keys` is applied first, so a key it
    fills counts as present, exactly as if the caller had passed it.
    """

    any_of: frozenset[str] | None = None
    """Keys of which at least one must be present; normalised to a frozenset, `None` when empty."""

    all_of: frozenset[str] | None = None
    """Keys that must all be present; normalised to a frozenset, `None` when empty."""

    def __post_init__(self) -> None:
        """Normalise `any_of`/`all_of` to frozensets, or `None` when empty."""
        self.any_of = to_frozenset(self.any_of) or None
        self.all_of = to_frozenset(self.all_of) or None

        super(CompiledConditional, self).__post_init__()

    def can_format(self, kw: Mapping[str, Any]) -> bool:
        """Return whether `kw` satisfies `all_of` and `any_of`.

        Args:
            kw: The `format()` keyword arguments, defaults already applied.

        Returns:
            `True` if the part should render.

        Example:
            >>> CompiledConditional(all_of={"a"}).can_format({"a": 1})
            True
            >>> CompiledConditional(any_of={"a", "b"}).can_format({"c": 1})
            False
        """
        return not (
            (self.all_of and not all(k in kw for k in self.all_of))
            or (self.any_of and not any(k in kw for k in self.any_of))
        )


__all__ = (
    "CompiledDefaults",
    "CompiledConditional",
)
