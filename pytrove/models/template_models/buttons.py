"""The inline keyboard buttons a template attaches."""

from __future__ import annotations as _annotations

import inspect
import sys
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, cast

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

try:
    from pyrogram.types import InlineKeyboardButton  # type: ignore[import-not-found]  # Optional: the `tg` extra.
except ImportError:
    pass

if TYPE_CHECKING:
    from pyrogram.enums import ButtonStyle  # type: ignore[import-not-found]  # Optional: the `tg` extra.
else:
    # `BaseDataClass` resolves field annotations at runtime, so `ButtonStyle`
    # must be a name here even when the installed pyrogram lacks it.
    try:
        from pyrogram.enums import ButtonStyle
    except ImportError:
        ButtonStyle = str

from ..._internal import _optional_import
from ...object_tools import classproperty
from ...typings import (
    MaybeList,
    StrInt,
    TemplateButtonDict,
    TemplateButtonType,
    TemplateEachButtonDict,
)
from ...validate_tools import is_container, is_mapping
from ..base import BaseDataClass
from ._internal import _chain_mappings, _CompiledEachButtonDict
from .conditions import CompiledConditional

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(slots=True, kw_only=True)
class CompiledButton(CompiledConditional):
    """One inline button."""

    text: str
    """The label, a `str.format` template."""

    type: TemplateButtonType
    """Which `InlineKeyboardButton` argument `value` fills; one the installed pyrogram lacks raises on `format()`."""

    value: str
    """The URL or callback data, a `str.format` template."""

    meta: dict[str, StrInt | ButtonStyle] | None = None
    """Extra `InlineKeyboardButton` arguments, such as its `ButtonStyle`; unknown keys are dropped with a warning."""

    @classmethod
    def compile(cls, item: TemplateButtonDict) -> Self:
        """Compile a button definition, turning enum values back into members.

        Args:
            item: The definition.

        Returns:
            The compiled button.
        """
        return cls.from_dict(item, True, True)

    @classproperty(cached=True)
    @_optional_import(("kurigram>=2.2.24", "tg"))
    def _buttons_params(cls: type[CompiledButton]) -> frozenset[str]:
        """The parameter names `InlineKeyboardButton` accepts."""
        return frozenset(inspect.signature(InlineKeyboardButton).parameters.keys())

    @_optional_import(("kurigram>=2.2.24", "tg"))
    def format(self, kw: Mapping[str, Any]) -> InlineKeyboardButton | None:
        """Render the button; `meta` keys the installed pyrogram does not accept are dropped with a warning.

        Args:
            kw: The `format()` keyword arguments.

        Returns:
            The button, or `None` if its conditions are not met.

        Raises:
            ValueError: If `type` is not an `InlineKeyboardButton` argument.
        """
        parameters = self._buttons_params

        if self.type not in parameters:
            msg = f"Unsupported InlineKeyboardButton type: {self.type!r}"
            raise ValueError(msg)

        meta = self.meta or {}
        if invalid_meta := meta.keys() - parameters:
            warnings.warn(
                "Ignoring unsupported InlineKeyboardButton meta keys: "
                + ", ".join(sorted(invalid_meta)),
                UserWarning,
                stacklevel=2,
            )
            meta = {key: value for key, value in meta.items() if key in parameters}

        kw = self.with_defaults(kw)

        if self.can_format(kw):
            return InlineKeyboardButton(
                self.text.format_map(kw), **{self.type: self.value.format_map(kw)}, **meta
            )

        return None


@dataclass(slots=True, kw_only=True)
class CompiledEachButton(BaseDataClass):
    """A button rendered once per element of a list argument, wrapped over as many rows as needed.

    Elements are filtered and merged exactly as in `CompiledEachLine`: whether
    an element is kept is `item`'s own decision, and this wrapper has no
    conditions or defaults of its own.
    """

    DEFAULT_ROW_WIDTH: ClassVar[int] = 2
    """Buttons per row when `row_width` is not set."""

    each: str
    """The `format()` argument holding the list."""

    item: CompiledButton
    """The button rendered for every element."""

    row_width: int | None = None
    """Buttons per row; `DEFAULT_ROW_WIDTH` when `None`."""

    @classmethod
    def compile(cls, item: TemplateEachButtonDict) -> Self:
        """Compile the definition, its `item` included.

        Args:
            item: The definition; its `item` is replaced by the compiled button.

        Returns:
            The compiled button block.
        """
        # The dict is rewritten in place into its compiled shape.
        compiled = cast("_CompiledEachButtonDict", item)
        compiled["item"] = CompiledButton.compile(item["item"])
        return cls.from_dict(compiled, True)

    @_optional_import(("kurigram>=2.2.24", "tg"))
    def format(self, kw: Mapping[str, Any]) -> list[list[InlineKeyboardButton]] | None:
        """Render one button per element, in rows of `row_width`.

        Args:
            kw: The `format()` keyword arguments.

        Returns:
            The rows, or `None` if no button rendered.
        """
        each = kw.get(self.each)

        if not each or not is_container(each):
            return None

        rows, current = [], []

        item = self.item
        row_width = self.row_width or self.DEFAULT_ROW_WIDTH

        for raw_each in each:
            if not is_mapping(raw_each):
                continue

            if (button := item.format(_chain_mappings(raw_each, kw))) is not None:
                current.append(button)

            if len(current) == row_width:
                rows.append(current)
                current = []

        if current:
            rows.append(current)

        return rows or None


@dataclass(slots=True)
class CompiledButtonRow(BaseDataClass):
    """One fixed row of the keyboard."""

    buttons: list[CompiledButton]
    """The row's buttons; the ones whose conditions fail are left out when rendering."""

    @classmethod
    def compile(cls, item: MaybeList[TemplateButtonDict]) -> Self:
        """Compile a row from a list of buttons, or from one button as shorthand for a row of just it.

        Args:
            item: The button definitions.

        Returns:
            The compiled row.
        """
        # A mapping is the one-button arm of `MaybeList`, anything else its list arm.
        # `ty` cannot split the arms by `is_mapping`: it keeps a `list & Mapping`
        # intersection in one branch and the `TypedDict` in the other.
        buttons = cast("list[TemplateButtonDict]", [item] if is_mapping(item) else item)

        return cls.from_dict({"buttons": list(map(CompiledButton.compile, buttons))}, True)

    @_optional_import(("kurigram>=2.2.24", "tg"))
    def format(self, kw: Mapping[str, Any]) -> list[InlineKeyboardButton] | None:
        """Render the row's buttons, dropping the ones that opt out.

        Args:
            kw: The `format()` keyword arguments.

        Returns:
            The buttons, or `None` if none rendered.
        """
        return [btn for button in self.buttons if (btn := button.format(kw)) is not None] or None


__all__ = (
    "CompiledButton",
    "CompiledEachButton",
    "CompiledButtonRow",
)
