"""The lines a template's text is built from."""

from __future__ import annotations as _annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ...typings import TemplateEachLineDict, TemplateLineDict
from ...validate_tools import is_container, is_mapping
from ..base import BaseDataClass
from ._internal import _chain_mappings, _CompiledEachLineDict
from .conditions import CompiledConditional


@dataclass(slots=True, kw_only=True)
class CompiledLine(CompiledConditional):
    """One line of a message."""

    text: str
    """A `str.format` template filled from the `format()` keyword arguments."""

    @classmethod
    def compile(cls, item: str | TemplateLineDict) -> Self:
        """Compile a line from its text alone or from its full definition.

        Args:
            item: The line's text, or its definition.

        Returns:
            The compiled line.
        """
        if isinstance(item, str):
            item = {"text": item}

        return cls.from_dict(item, True)

    def format(self, kw: Mapping[str, Any]) -> str | None:
        """Render the line.

        Args:
            kw: The `format()` keyword arguments.

        Returns:
            The text, or `None` if the line's conditions are not met.

        Example:
            >>> CompiledLine.compile("Hi {name}").format({"name": "Bob"})
            'Hi Bob'
            >>> CompiledLine.compile({"text": "Hi {name}", "all_of": ["name"]}).format({}) is None
            True
            >>> CompiledLine.compile({"text": "Hi {name}", "default_keys": {"name": "you"}}).format({})
            'Hi you'
        """
        kw = self.with_defaults(kw)

        if self.can_format(kw):
            return self.text.format_map(kw)

        return None


@dataclass(slots=True, kw_only=True)
class CompiledEachLine(BaseDataClass):
    """A line rendered once per element of a list argument, joined by newlines.

    Only mapping elements render; each is merged over the surrounding keyword
    arguments, so `item` can reference both. Whether an element is kept is
    `item`'s own decision: this wrapper has no conditions or defaults of its own.
    """

    each: str
    """The `format()` argument holding the list."""

    item: CompiledLine
    """The line rendered for every element."""

    @classmethod
    def compile(cls, item: TemplateEachLineDict) -> Self:
        """Compile the definition, its `item` included.

        Args:
            item: The definition; its `item` is replaced by the compiled line.

        Returns:
            The compiled line.
        """
        # The dict is rewritten in place into its compiled shape.
        compiled = cast(_CompiledEachLineDict, item)
        compiled["item"] = CompiledLine.compile(item["item"])
        return cls.from_dict(compiled, True)

    def format(self, kw: Mapping[str, Any]) -> str | None:
        """Render one line per element.

        Args:
            kw: The `format()` keyword arguments.

        Returns:
            The lines joined by newlines, or `None` if none rendered.

        Example:
            >>> block = CompiledEachLine.compile({"each": "items", "item": "- {n}"})
            >>> print(block.format({"items": [{"n": 1}, {"n": 2}]}))
            - 1
            - 2
        """
        each = kw.get(self.each)

        if not each or not is_container(each):
            return None

        item = self.item

        return "\n".join(
            line
            for raw_each in each
            if is_mapping(raw_each) and (line := item.format(_chain_mappings(raw_each, kw))) is not None
        ) or None


__all__ = (
    "CompiledLine",
    "CompiledEachLine",
)
