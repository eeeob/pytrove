"""The shapes a message template is written in, and the payload it renders to.

They describe `models.template_models` only, so every name is prefixed
`Template`: `pytrove.typings` re-exports its modules flat, where an
unprefixed `LineDict` would read as a package-wide type.
"""

from __future__ import annotations as _annotations

import sys
from typing import TYPE_CHECKING, Literal, TypeAlias, TypedDict

if sys.version_info >= (3, 11):
    from typing import NotRequired
else:
    from typing_extensions import NotRequired

if TYPE_CHECKING:
    from pyrogram.enums import ParseMode as PyroParseMode
    from pyrogram.types import InlineKeyboardMarkup, InputRichMessage

    from .core import JsonValue, MaybeList, StrInt

TemplateButtonType: TypeAlias = Literal["url", "callback_data"]
"""Which `InlineKeyboardButton` argument a button's `value` fills."""

TemplateParseMode: TypeAlias = Literal["html", "markdown"]
"""The parse mode a template's message is written in."""


class TemplateDefaultsDict(TypedDict):
    """Keys every renderable part accepts."""

    default_keys: NotRequired[dict[str, JsonValue]]
    """Fallback values for keys not passed to `format()`; a key filled here counts as present for `any_of`/`all_of`."""


class TemplateConditionalDict(TemplateDefaultsDict):
    """Keys a part uses to opt out of rendering."""

    any_of: NotRequired[MaybeList[str]]
    """The part renders only if at least one of these keys is present."""

    all_of: NotRequired[MaybeList[str]]
    """The part renders only if all of these keys are present."""


class TemplateLineDict(TemplateConditionalDict):
    """One message line."""

    text: str
    """A `str.format` template filled from the `format()` arguments."""


class TemplateEachLineDict(TypedDict):
    """A line repeated once per element of a list argument."""

    each: str
    """The `format()` argument holding the list; only mapping elements render, each merged over the surrounding arguments."""

    item: str | TemplateLineDict
    """The line rendered for every element; a bare string is its `text`."""


class TemplateButtonDict(TemplateConditionalDict):
    """One inline button."""

    text: str
    """The button label, a `str.format` template."""

    type: TemplateButtonType
    """Which `InlineKeyboardButton` argument `value` fills."""

    value: str
    """The URL or callback data, a `str.format` template."""

    meta: NotRequired[dict[str, StrInt]]
    """Extra `InlineKeyboardButton` arguments as raw JSON, such as `{"style": "primary"}`; compiling restores enum members."""


class TemplateEachButtonDict(TypedDict):
    """A button repeated once per element of a list argument."""

    each: str
    """The `format()` argument holding the list; only mapping elements render."""

    item: TemplateButtonDict
    """The button rendered for every element."""

    row_width: NotRequired[int]
    """Buttons per keyboard row; 2 when omitted."""


class TemplateRichMessageDict(TemplateDefaultsDict):
    """A rich message, sent with `Client.send_rich_message`."""

    html: NotRequired[list[str | TemplateLineDict | TemplateEachLineDict]]
    """The message lines, written as HTML; tried before `markdown`."""

    markdown: NotRequired[list[str | TemplateLineDict | TemplateEachLineDict]]
    """The message lines, written as Markdown; used only if no `html` line rendered."""

    is_rtl: NotRequired[bool]
    """Whether the message reads right to left; passed to `InputRichMessage`."""

    skip_entity_detection: NotRequired[bool]
    """Whether Telegram should skip detecting entities; passed to `InputRichMessage`."""


class TemplateDict(TemplateDefaultsDict):
    """A whole message template."""

    message: NotRequired[list[str | TemplateLineDict | TemplateEachLineDict]]
    """The message lines, joined by newlines."""

    buttons: NotRequired[list[MaybeList[TemplateButtonDict] | TemplateEachButtonDict]]
    """Keyboard rows: one button (a row of just it), a list of buttons, or a repeated button."""

    parse_mode: NotRequired[TemplateParseMode]
    """The parse mode of `message`; the file-wide default when omitted."""

    rich_message: NotRequired[TemplateRichMessageDict]
    """A rich message to send instead of `message`."""

    key_time: NotRequired[str]
    """A `format()` key filled with `arabic_time()` when not passed; the file-wide default when omitted."""


class TemplatePyroMessage(TypedDict):
    """What `CompiledTemplate.format()` returns, ready to spread into `Client.send_message()`.

    Every key is optional because `format()` drops the ones that came out empty.
    """

    text: NotRequired[str]
    """The rendered message; absent when `rich_message` is present."""

    parse_mode: NotRequired[PyroParseMode]
    """The parse mode of `text`."""

    rich_message: NotRequired[InputRichMessage]
    """The rendered rich message, replacing `text`/`parse_mode`."""

    reply_markup: NotRequired[InlineKeyboardMarkup]
    """The rendered keyboard."""


__all__ = (
    "TemplateButtonType",
    "TemplateParseMode",
    "TemplateDefaultsDict",
    "TemplateConditionalDict",
    "TemplateLineDict",
    "TemplateEachLineDict",
    "TemplateButtonDict",
    "TemplateEachButtonDict",
    "TemplateRichMessageDict",
    "TemplateDict",
    "TemplatePyroMessage",
)
