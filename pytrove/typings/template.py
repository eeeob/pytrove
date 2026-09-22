"""The shapes a message template is written in, and the payload it renders to.

These describe models/template_models only, so every name here is prefixed
`Template*` -- pytrove.typings re-exports its modules flat, and an
unprefixed `LineDict`/`ButtonDict`/`ParseMode` would read there as if it
were a package-wide type rather than one belonging to this one feature.
"""

from __future__ import annotations as _annotations

from typing import (
    Literal, TypedDict, TypeAlias,
    TYPE_CHECKING,
)

import sys

if sys.version_info >= (3, 11):
    from typing import NotRequired
else:
    from typing_extensions import NotRequired


if TYPE_CHECKING:
    from pyrogram.enums import ParseMode as PyroParseMode
    from pyrogram.types import InlineKeyboardMarkup, InputRichMessage

from .core import MaybeList, JsonValue, StrInt


TemplateButtonType: TypeAlias = Literal["url", "callback_data"]
TemplateParseMode: TypeAlias = Literal["html", "markdown"]


class TemplateDefaultsDict(TypedDict):
    """Keys every renderable part accepts to carry its own fallback values."""

    default_keys: NotRequired[dict[str, JsonValue]]
    "Fallback values for keys not passed to format()."

class TemplateConditionalDict(TemplateDefaultsDict):
    """The opt-out/fallback keys every conditional part shares -- see
    template_models.CompiledConditional for how they are evaluated."""

    any_of: NotRequired[MaybeList[str]]
    all_of: NotRequired[MaybeList[str]]

class TemplateLineDict(TemplateConditionalDict):
    text: str
class TemplateEachLineDict(TypedDict):
    each: str
    item: str | TemplateLineDict

class TemplateButtonDict(TemplateConditionalDict):
    text: str
    type: TemplateButtonType
    value: str

    meta: NotRequired[dict[str, StrInt]]
    """Extra InlineKeyboardButton arguments, as written in the JSON -- so raw
    values only, never enum members (`"style": "primary"`, not
    ButtonStyle.PRIMARY). CompiledButton.meta is the widened counterpart:
    compile() runs the values through from_dict(..., values_to_enums=True),
    which is what turns the ones naming a ButtonStyle into real members."""
class TemplateEachButtonDict(TypedDict):
    each: str
    item: TemplateButtonDict
    row_width: NotRequired[int]

class TemplateRichMessageDict(TemplateDefaultsDict):
    html: NotRequired[list[str | TemplateLineDict | TemplateEachLineDict]]
    markdown: NotRequired[list[str | TemplateLineDict | TemplateEachLineDict]]
    is_rtl: NotRequired[bool]
    skip_entity_detection: NotRequired[bool]

class TemplateDict(TemplateDefaultsDict):
    message: NotRequired[list[str | TemplateLineDict | TemplateEachLineDict]]
    buttons: NotRequired[list[MaybeList[TemplateButtonDict] | TemplateEachButtonDict]]
    parse_mode: NotRequired[TemplateParseMode]
    rich_message: NotRequired[TemplateRichMessageDict]
    key_time: NotRequired[str]

class TemplatePyroMessage(TypedDict):
    """What CompiledTemplate.format() hands back -- spread straight into
    Client.send_message()/send_rich_message(). Every key is NotRequired
    because format() drops the ones that came out empty."""

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
