"""Helpers private to the template models."""

from __future__ import annotations as _annotations

from collections import ChainMap
from typing import TYPE_CHECKING, Any, TypedDict, cast

from ...data_tools import snapshot
from ...typings import (
    TemplateDefaultsDict,
    TemplateEachButtonDict,
    TemplateEachLineDict,
    TemplateLineDict,
)
from ...validate_tools import is_mapping

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping
    from pyrogram.enums import ParseMode  # type: ignore[import-not-found]  # Optional: the `tg` extra.

    # Only annotations use `TypeIs`, so the checker's `typing_extensions` serves every
    # version without raising the runtime floor (`TypeIs` needs `typing_extensions>=4.10`).
    from typing_extensions import TypeIs
    from .buttons import CompiledButton, CompiledButtonRow, CompiledEachButton
    from .lines import CompiledEachLine, CompiledLine
    from .rich import CompiledRichMessage

if TYPE_CHECKING:
    from pyrogram.enums import ButtonStyle  # type: ignore[import-not-found]  # Optional: the `tg` extra.
else:
    # `values_to_enums` resolves `_CompiledButtonMeta` at runtime, so `ButtonStyle` must be
    # a name here even without pyrogram; as `str` it simply converts nothing.
    try:
        from pyrogram.enums import ButtonStyle
    except ImportError:
        ButtonStyle = str


class _CompiledButtonMeta(TypedDict, total=False):
    """A button's `meta` once compiled: only `style` is an enum, so only it is converted.

    Any other `InlineKeyboardButton` keyword argument may sit here too, as written;
    `CompiledButton.format()` drops the ones the installed pyrogram does not take.
    """

    style: ButtonStyle
    """The button colour, restored from its raw value."""

    icon_custom_emoji_id: str
    """A custom emoji shown on the button, kept as written."""


class _CompiledEachLineDict(TypedDict):
    """A `TemplateEachLineDict` after `CompiledEachLine.compile` rewrote it in place."""

    each: str
    """The `format()` argument holding the list."""

    item: CompiledLine
    """The compiled line, in place of its definition."""


# The optional keys sit in a `total=False` subclass of a base holding the required ones:
# under deferred annotations `NotRequired[...]` is a string that `TypedDict` cannot see at
# runtime, so it would report those keys as required.


class _CompiledEachButtonRequiredDict(TypedDict):
    """The keys every `_CompiledEachButtonDict` has."""

    each: str
    """The `format()` argument holding the list."""

    item: CompiledButton
    """The compiled button, in place of its definition."""


class _CompiledEachButtonDict(_CompiledEachButtonRequiredDict, total=False):
    """A `TemplateEachButtonDict` after `CompiledEachButton.compile` rewrote it in place."""

    row_width: int
    """Buttons per keyboard row, untouched by compiling."""


class _CompiledRichMessageRequiredDict(TemplateDefaultsDict):
    """The keys every `_CompiledRichMessageDict` has, `default_keys` aside."""

    html: list[CompiledLine | CompiledEachLine] | None
    """The compiled HTML lines, or `None` for an empty or missing block."""

    markdown: list[CompiledLine | CompiledEachLine] | None
    """The compiled Markdown lines, or `None` for an empty or missing block."""


class _CompiledRichMessageDict(_CompiledRichMessageRequiredDict, total=False):
    """A `TemplateRichMessageDict` after `CompiledRichMessage.compile` rewrote it in place."""

    is_rtl: bool
    """Whether the message reads right to left, untouched by compiling."""

    skip_entity_detection: bool
    """Whether Telegram should skip detecting entities, untouched by compiling."""


class _CompiledTemplateDict(TemplateDefaultsDict):
    """A `TemplateDict` after `CompiledTemplate.compile` rewrote it in place."""

    message: list[CompiledLine | CompiledEachLine] | None
    """The compiled lines, or `None` for an empty or missing block."""

    buttons: list[CompiledButtonRow | CompiledEachButton] | None
    """The compiled keyboard rows, or `None` for no keyboard."""

    parse_mode: ParseMode | None
    """The template's own parse mode or the file-wide default, as a `ParseMode` member."""

    rich_message: CompiledRichMessage | None
    """The compiled rich message, or `None` without one."""

    key_time: str | None
    """The template's own `key_time` or the file-wide default."""


def _is_each_line(line: object) -> TypeIs[TemplateEachLineDict]:
    """Tell whether a line definition is a repeated line: a mapping with an `each` key.

    Args:
        line: The line definition.

    Returns:
        Whether it is compiled with `CompiledEachLine`, which validates `each`.
    """
    return is_mapping(line) and "each" in line


def _is_each_button(button: object) -> TypeIs[TemplateEachButtonDict]:
    """Tell whether a keyboard row definition is a repeated button: a mapping with an `each` key.

    Args:
        button: The row definition.

    Returns:
        Whether it is compiled with `CompiledEachButton`, which validates `each`.
    """
    return is_mapping(button) and "each" in button


def _check_each(definition: Mapping[str, Any]) -> None:
    """Reject a repeated line or button whose `each` is not a non-empty string.

    Args:
        definition: The repeated line or button definition.

    Raises:
        ValueError: If `each` is not a non-empty string.
    """
    if not isinstance(each := definition.get("each"), str) or not each:
        msg = f"each must name a format() argument, not {each!r}"
        raise ValueError(msg)


def _chain_mappings(*maps: Mapping[str, Any]) -> Mapping[str, Any]:
    """Look keys up through `maps` in order, without copying them.

    Args:
        *maps: The mappings, the first one winning.

    Returns:
        A `ChainMap` over `maps`.
    """
    # `ChainMap` types its maps as `MutableMapping` because a write lands in the first
    # one; the chains built here are only read, and reads work on any `Mapping`.
    return ChainMap(*cast("tuple[MutableMapping[str, Any], ...]", maps))


def _copy_templates(templates: Mapping[str, Any]) -> dict[str, Any]:
    """Copy the entries `CompiledTemplate.compile_template` compiles, and nothing else.

    A resolved `$ref` is the very object it points at, and compiling rewrites its
    input in place, so each template gets its own copy first. Only what compiling
    reaches is copied: a `$`-prefixed definition, which may hold a recursive
    reference, is never walked.

    Args:
        templates: The loaded templates, as `compile_template` takes them.

    Returns:
        The copied templates; each `"nested": true` group is copied the same way.
    """
    return {
        name: (
            {**_copy_templates(templ), "nested": True} if templ.get("nested") else snapshot(templ)
        )
        for name, templ in templates.items()
        if isinstance(templ, dict) and not name.startswith("$")
    }


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
    from .lines import CompiledEachLine, CompiledLine  # noqa: PLC0415 - see the comment above

    return [
        CompiledEachLine.compile(line) if _is_each_line(line) else CompiledLine.compile(line)
        for line in (lines or ())
    ] or None


def _format_lines(
    lines: list[CompiledLine | CompiledEachLine] | None, kw: Mapping[str, Any]
) -> str | None:
    """Render a block of lines, dropping the ones that opt out.

    Args:
        lines: The compiled lines.
        kw: The `format()` keyword arguments.

    Returns:
        The rendered lines joined by newlines, or `None` if none rendered.
    """
    return (
        "\n".join(formatted for line in (lines or ()) if (formatted := line.format(kw)) is not None)
        or None
    )


__all__ = (
    "_CompiledButtonMeta",
    "_CompiledEachLineDict",
    "_CompiledEachButtonDict",
    "_CompiledRichMessageDict",
    "_CompiledTemplateDict",
    "_is_each_line",
    "_is_each_button",
    "_check_each",
    "_chain_mappings",
    "_copy_templates",
    "_compile_lines",
    "_format_lines",
)
