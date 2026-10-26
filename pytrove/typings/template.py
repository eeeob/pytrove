"""The shapes a message template is written in, and the payload it renders to.

They describe `models.template_models` only, so every name is prefixed
`Template`: `pytrove.typings` re-exports its modules flat, where an
unprefixed `LineDict` would read as a package-wide type.
"""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Literal, TypeAlias, TypedDict

if TYPE_CHECKING:
    from pyrogram.enums import ParseMode as PyroParseMode  # type: ignore[import-not-found]  # Optional: the `tg` extra.
    from pyrogram.types import InlineKeyboardMarkup, InputRichMessage  # type: ignore[import-not-found]  # Optional: the `tg` extra.

    from .core import JsonValue, MaybeList, StrInt

TemplateButtonType: TypeAlias = Literal["url", "callback_data"]
"""Which `InlineKeyboardButton` argument a button's `value` fills."""

TemplateParseMode: TypeAlias = Literal["html", "markdown", "disabled"]
"""The parse mode a template's message is written in; `"disabled"` sends it unparsed."""


class TemplateDefaultsDict(TypedDict, total=False):
    """Keys every renderable part accepts."""

    default_keys: dict[str, JsonValue]
    """Fallback values for keys not passed to `format()`; a key filled here counts as present for `any_of`/`all_of`."""


class TemplateConditionalDict(TemplateDefaultsDict, total=False):
    """Keys a part uses to opt out of rendering."""

    any_of: MaybeList[str]
    """The part renders only if at least one of these keys is present."""

    all_of: MaybeList[str]
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


class _TemplateButtonRequiredDict(TemplateConditionalDict):
    """The keys every `TemplateButtonDict` must have."""

    text: str
    """The button label, a `str.format` template."""

    type: TemplateButtonType
    """Which `InlineKeyboardButton` argument `value` fills."""

    value: str
    """The URL or callback data, a `str.format` template."""


class TemplateButtonDict(_TemplateButtonRequiredDict, total=False):
    """One inline button."""

    meta: dict[str, StrInt]
    """Extra `InlineKeyboardButton` arguments as raw JSON, such as `{"style": "primary"}`; compiling restores enum members."""


class _TemplateEachButtonRequiredDict(TypedDict):
    """The keys every `TemplateEachButtonDict` must have."""

    each: str
    """The `format()` argument holding the list; only mapping elements render."""

    item: TemplateButtonDict
    """The button rendered for every element."""


class TemplateEachButtonDict(_TemplateEachButtonRequiredDict, total=False):
    """A button repeated once per element of a list argument."""

    row_width: int
    """Buttons per keyboard row; 2 when omitted."""


class TemplateRichMessageDict(TemplateDefaultsDict, total=False):
    """A rich message, sent with `Client.send_rich_message`."""

    html: list[str | TemplateLineDict | TemplateEachLineDict]
    """The message lines, written as HTML; tried before `markdown`."""

    markdown: list[str | TemplateLineDict | TemplateEachLineDict]
    """The message lines, written as Markdown; used only if no `html` line rendered."""

    is_rtl: bool
    """Whether the message reads right to left; passed to `InputRichMessage`."""

    skip_entity_detection: bool
    """Whether Telegram should skip detecting entities; passed to `InputRichMessage`."""


class TemplateDict(TemplateDefaultsDict, total=False):
    """A whole message template."""

    message: list[str | TemplateLineDict | TemplateEachLineDict]
    """The message lines, joined by newlines."""

    buttons: list[MaybeList[TemplateButtonDict] | TemplateEachButtonDict]
    """Keyboard rows: one button (a row of just it), a list of buttons, or a repeated button."""

    parse_mode: TemplateParseMode
    """The parse mode of `message`; the file-wide default when omitted."""

    rich_message: TemplateRichMessageDict
    """A rich message to send instead of `message`."""

    key_time: str
    """A `format()` key filled with `arabic_time()` when not passed; the file-wide default when omitted."""


class TemplatePyroMessage(TypedDict, total=False):
    """What `CompiledTemplate.format()` returns, ready to spread into `Client.send_message()`.

    Every key is optional because `format()` drops the ones that came out empty.
    """

    text: str
    """The rendered message; absent when `rich_message` is present."""

    parse_mode: PyroParseMode
    """The parse mode of `text`."""

    rich_message: InputRichMessage
    """The rendered rich message, replacing `text`/`parse_mode`."""

    reply_markup: InlineKeyboardMarkup
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
