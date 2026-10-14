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
    """Keys every renderable part accepts.

    Attributes:
        default_keys: Fallback values for keys not passed to `format()`;
            a key filled here counts as present for `any_of`/`all_of`.
    """

    default_keys: NotRequired[dict[str, JsonValue]]


class TemplateConditionalDict(TemplateDefaultsDict):
    """Keys a part uses to opt out of rendering.

    Attributes:
        any_of: The part renders only if at least one of these keys is present.
        all_of: The part renders only if all of these keys are present.
    """

    any_of: NotRequired[MaybeList[str]]
    all_of: NotRequired[MaybeList[str]]


class TemplateLineDict(TemplateConditionalDict):
    """One message line.

    Attributes:
        text: A `str.format` template filled from the `format()` arguments.
    """

    text: str


class TemplateEachLineDict(TypedDict):
    """A line repeated once per element of a list argument.

    Attributes:
        each: The `format()` argument holding the list; only mapping elements
            render, each merged over the surrounding arguments.
        item: The line rendered for every element.
    """

    each: str
    item: str | TemplateLineDict


class TemplateButtonDict(TemplateConditionalDict):
    """One inline button.

    Attributes:
        text: The button label, a `str.format` template.
        type: Which button argument `value` fills.
        value: The URL or callback data, a `str.format` template.
        meta: Extra `InlineKeyboardButton` arguments as raw JSON values, such as
            `{"style": "primary"}`; compiling turns enum names into members.
    """

    text: str
    type: TemplateButtonType
    value: str
    meta: NotRequired[dict[str, StrInt]]


class TemplateEachButtonDict(TypedDict):
    """A button repeated once per element of a list argument.

    Attributes:
        each: The `format()` argument holding the list.
        item: The button rendered for every element.
        row_width: Buttons per keyboard row; 2 when omitted.
    """

    each: str
    item: TemplateButtonDict
    row_width: NotRequired[int]


class TemplateRichMessageDict(TemplateDefaultsDict):
    """A rich message, sent with `Client.send_rich_message`.

    Attributes:
        html: The message lines, written as HTML.
        markdown: The message lines, written as Markdown.
        is_rtl: Whether the message reads right to left.
        skip_entity_detection: Whether Telegram should skip detecting entities.
    """

    html: NotRequired[list[str | TemplateLineDict | TemplateEachLineDict]]
    markdown: NotRequired[list[str | TemplateLineDict | TemplateEachLineDict]]
    is_rtl: NotRequired[bool]
    skip_entity_detection: NotRequired[bool]


class TemplateDict(TemplateDefaultsDict):
    """A whole message template.

    Attributes:
        message: The message lines.
        buttons: Keyboard rows: a button, a list of buttons, or a repeated button.
        parse_mode: The parse mode of `message`.
        rich_message: A rich message to send instead of `message`.
        key_time: A key filled with the current time in Arabic when not passed.
    """

    message: NotRequired[list[str | TemplateLineDict | TemplateEachLineDict]]
    buttons: NotRequired[list[MaybeList[TemplateButtonDict] | TemplateEachButtonDict]]
    parse_mode: NotRequired[TemplateParseMode]
    rich_message: NotRequired[TemplateRichMessageDict]
    key_time: NotRequired[str]


class TemplatePyroMessage(TypedDict):
    """What `CompiledTemplate.format()` returns, ready to spread into `Client.send_message()`.

    Every key is optional because `format()` drops the ones that came out empty.

    Attributes:
        text: The rendered message.
        parse_mode: The parse mode of `text`.
        rich_message: The rendered rich message.
        reply_markup: The rendered keyboard.
    """

    text: NotRequired[str]
    parse_mode: NotRequired[PyroParseMode]
    rich_message: NotRequired[InputRichMessage]
    reply_markup: NotRequired[InlineKeyboardMarkup]


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
