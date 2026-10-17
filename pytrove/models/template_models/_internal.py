"""Helpers private to the template models."""

from __future__ import annotations as _annotations

import sys
from collections import ChainMap
from collections.abc import Mapping, MutableMapping
from typing import TYPE_CHECKING, Any, TypedDict, cast

if sys.version_info >= (3, 11):
    from typing import NotRequired
else:
    from typing_extensions import NotRequired

from ...typings import TemplateDefaultsDict, TemplateEachButtonDict, TemplateEachLineDict, TemplateLineDict
from ...validate_tools import is_mapping

if TYPE_CHECKING:
    from pyrogram.enums import ParseMode

    # Only annotations use `TypeIs`, so the checker's `typing_extensions` serves every
    # version without raising the runtime floor (`TypeIs` needs `typing_extensions>=4.10`).
    from typing_extensions import TypeIs

    from .buttons import CompiledButton, CompiledButtonRow, CompiledEachButton
    from .lines import CompiledEachLine, CompiledLine
    from .rich import CompiledRichMessage


class _CompiledEachLineDict(TypedDict):
    """A `TemplateEachLineDict` after `CompiledEachLine.compile` rewrote it in place.

    Attributes:
        each: The `format()` argument holding the list.
        item: The compiled line.
    """

    each: str
    item: CompiledLine


class _CompiledEachButtonDict(TypedDict):
    """A `TemplateEachButtonDict` after `CompiledEachButton.compile` rewrote it in place.

    Attributes:
        each: The `format()` argument holding the list.
        item: The compiled button.
        row_width: Buttons per keyboard row.
    """

    each: str
    item: CompiledButton
    row_width: NotRequired[int]


class _CompiledRichMessageDict(TemplateDefaultsDict):
    """A `TemplateRichMessageDict` after `CompiledRichMessage.compile` rewrote it in place.

    Attributes:
        html: The compiled HTML lines, or `None` for an empty block.
        markdown: The compiled Markdown lines, or `None` for an empty block.
        is_rtl: Whether the message reads right to left.
        skip_entity_detection: Whether Telegram should skip detecting entities.
    """

    html: list[CompiledLine | CompiledEachLine] | None
    markdown: list[CompiledLine | CompiledEachLine] | None
    is_rtl: NotRequired[bool]
    skip_entity_detection: NotRequired[bool]


class _CompiledTemplateDict(TemplateDefaultsDict):
    """A `TemplateDict` after `CompiledTemplate.compile` rewrote it in place.

    Attributes:
        message: The compiled lines, or `None` for an empty block.
        buttons: The compiled keyboard rows, or `None` for no keyboard.
        parse_mode: The resolved parse mode.
        rich_message: The compiled rich message, or `None` without one.
        key_time: The resolved `key_time` key.
    """

    message: list[CompiledLine | CompiledEachLine] | None
    buttons: list[CompiledButtonRow | CompiledEachButton] | None
    parse_mode: ParseMode | None
    rich_message: CompiledRichMessage | None
    key_time: str | None


def _is_each_line(line: object) -> TypeIs[TemplateEachLineDict]:
    """Tell whether a line definition is a repeated line: a mapping with a truthy `each`.

    Args:
        line: The line definition.

    Returns:
        Whether it is compiled with `CompiledEachLine`.
    """
    return is_mapping(line) and bool(line.get("each"))


def _is_each_button(button: object) -> TypeIs[TemplateEachButtonDict]:
    """Tell whether a keyboard row definition is a repeated button: a mapping with a truthy `each`.

    Args:
        button: The row definition.

    Returns:
        Whether it is compiled with `CompiledEachButton`.
    """
    return is_mapping(button) and bool(button.get("each"))


def _chain_mappings(*maps: Mapping[str, Any]) -> Mapping[str, Any]:
    """Look keys up through `maps` in order, without copying them.

    Args:
        *maps: The mappings, the first one winning.

    Returns:
        A `ChainMap` over `maps`.
    """
    # `ChainMap` types its maps as `MutableMapping` because a write lands in the first
    # one; reads work on any `Mapping`, and the only writer, `CompiledTemplate.format()`,
    # passes the dict it built itself as the first map.
    return ChainMap(*cast(tuple[MutableMapping[str, Any], ...], maps))


def _compile_lines(
    lines: list[str | TemplateLineDict | TemplateEachLineDict] | None,
) -> list[CompiledLine | CompiledEachLine] | None:
    """Compile a block of lines: the shape `message` and each rich message format share.

    Args:
        lines: The block's line definitions.

    Returns:
        The compiled lines, or `None` for an empty block, so it is absent rather than blank.
    """
    # `lines` imports this module for its compiled-shape `TypedDict`, so it is imported here.
    from .lines import CompiledEachLine, CompiledLine

    return [
        CompiledEachLine.compile(line) if _is_each_line(line) else CompiledLine.compile(line)
        for line in (lines or ())
    ] or None


def _format_lines(lines: list[CompiledLine | CompiledEachLine] | None, kw: Mapping[str, Any]) -> str | None:
    """Render a block of lines, dropping the ones that opt out.

    Args:
        lines: The compiled lines.
        kw: The `format()` keyword arguments.

    Returns:
        The rendered lines joined by newlines, or `None` if none rendered.
    """
    return "\n".join(formatted for line in (lines or ()) if (formatted := line.format(kw)) is not None) or None


__all__ = (
    "_CompiledEachLineDict",
    "_CompiledEachButtonDict",
    "_CompiledRichMessageDict",
    "_CompiledTemplateDict",
    "_is_each_line",
    "_is_each_button",
    "_chain_mappings",
    "_compile_lines",
    "_format_lines",
)
