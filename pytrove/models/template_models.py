from __future__ import annotations

import inspect
import warnings

from typing import (
    Mapping, Any, ClassVar,
    TYPE_CHECKING, overload,
)

try:
    from typing import Self
except ImportError:  # Python < 3.11
    from typing_extensions import Self


from collections import ChainMap
from dataclasses import dataclass

try:
    from pyrogram.enums import ParseMode
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
except ImportError:
    HAS_PYROGRAM = False
else:
    HAS_PYROGRAM = True

if TYPE_CHECKING:
    from pyrogram.enums import ButtonStyle
    from pyrogram.types import InputRichMessage
else:
    try:
        from pyrogram.types import InputRichMessage
    except ImportError:
        InputRichMessage = None

    try:
        from pyrogram.enums import ButtonStyle
    except ImportError:
        ButtonStyle = str


from .._optional import _optional_import, _unavailable_class
from ..typings import (
    NestedStrKeyDict, MaybeList, JsonValue,
    StrInt, PathLike, _True, _False,

    TemplateButtonType,
    TemplateLineDict,
    TemplateEachLineDict,
    TemplateButtonDict,
    TemplateEachButtonDict,
    TemplateRichMessageDict,
    TemplateDict,
    TemplatePyroMessage,
)
from ..data_tools import clean_none_values
from ..date_tools import arabic_time
from ..validate_tools import is_mapping, is_container
from ..iter_tools import to_frozenset
from ..files_tools import load_ref_json, read_json
from ..classes import classproperty
from .base import BaseDataClass


def compile_lines(lines: list[str | TemplateLineDict | TemplateEachLineDict] | None) -> list[CompiledLine | CompiledEachLine] | None:
    """
    Compile a block of lines - the shape `message` and each rich message format share.
    Returns None for an empty block, so it is simply absent rather than blank.
    """

    return [
        CompiledEachLine.compile(line) if (is_mapping(line) and line.get("each")) else CompiledLine.compile(line)
        for line in (lines or ())
    ] or None

def format_lines(lines: list[CompiledLine | CompiledEachLine] | None, kw: Mapping[str, Any]) -> str | None:
    """Render a block of lines into text, dropping the ones that opt out."""

    return "\n".join(
        formatted
        for line in (lines or ())
        if (formatted := line.format(kw)) is not None
    ) or None



@dataclass(slots=True)
class CompiledDefaults(BaseDataClass):
    """Base for every compiled part that can carry its own fallback values."""

    default_keys: dict[str, JsonValue] | None = None

    def with_defaults(self, kw: Mapping[str, Any]) -> Mapping[str, Any]:
        """Layer default_keys beneath kw, so any value the caller actually passed always wins."""

        return ChainMap(kw, defaults) if (defaults := self.default_keys) else kw

@dataclass(slots=True)
class CompiledConditional(CompiledDefaults):
    """
    Base for every compiled part that can opt out of being rendered.

    A part renders only when `all_of` keys are all present in the format() keyword
    arguments and at least one `any_of` key is. Both are optional; a part that sets
    neither always renders. `default_keys` fills in values for keys the caller did not
    pass, before conditions are checked - so a key covered by a default counts as
    present for `all_of`/`any_of` too, exactly as if the caller had passed it.
    """

    any_of: frozenset[str] | None = None
    all_of: frozenset[str] | None = None

    def __post_init__(self) -> None:
        self.any_of = to_frozenset(self.any_of) or None
        self.all_of = to_frozenset(self.all_of) or None

        super(CompiledConditional, self).__post_init__()

    def can_format(self, kw: Mapping[str, Any]) -> bool:
        return not (
            (self.all_of and not all(k in kw for k in self.all_of))
            or
            (self.any_of and not any(k in kw for k in self.any_of))
        )


@dataclass(slots=True, kw_only=True)
class CompiledLine(CompiledConditional):
    """One line of a message. `text` is formatted against the format() keyword arguments."""

    text: str

    @classmethod
    def compile(cls, item: str | TemplateLineDict) -> Self:
        if isinstance(item, str):
            item = {"text": item}

        return cls.from_dict(item, True)

    def format(self, kw: Mapping[str, Any]) -> str | None:
        kw = self.with_defaults(kw)

        if self.can_format(kw):
            return self.text.format_map(kw)
        
@dataclass(slots=True, kw_only=True)
class CompiledEachLine(BaseDataClass):
    """
    A line rendered once per element of the list passed to format() under `each`,
    joined by newlines - so one template entry can produce many lines.

    Only mapping elements are rendered; each one is merged over the surrounding
    keyword arguments, so `item` can reference both. Whether a given element is kept
    is entirely `item`'s own decision (its `all_of`/`any_of`) - this wrapper carries no
    condition, and no fallback values, of its own.
    """

    each: str
    item: CompiledLine

    @classmethod
    def compile(cls, item: TemplateEachLineDict) -> Self:
        item["item"] = CompiledLine.compile(item["item"])
        return cls.from_dict(item, True)

    def format(self, kw: Mapping[str, Any]) -> str | None:
        each = kw.get(self.each)

        if not each or not is_container(each):
            return

        item = self.item

        return "\n".join(
            line for raw_each in each
            if (
                is_mapping(raw_each)
                and (line := item.format(ChainMap(raw_each, kw))) is not None
            )
        ) or None


@dataclass(slots=True, kw_only=True)
class CompiledButton(CompiledConditional):
    """
    One inline button. `type` selects which pyrogram argument `value` fills
    (`url` or `callback_data`), and `meta` carries extra InlineKeyboardButton
    arguments such as its ButtonStyle.
    """

    text: str
    type: TemplateButtonType
    value: str
    meta: dict[str, StrInt | ButtonStyle] | None = None

    @classmethod
    def compile(cls, item: TemplateButtonDict) -> Self:
        return cls.from_dict(item, True, True)

    @classproperty(cached=True)
    @_optional_import(("kurigram", "tg"))
    def _buttons_params(cls) -> frozenset[str]:
        return frozenset(inspect.signature(InlineKeyboardButton).parameters.keys())

    @_optional_import(("kurigram", "tg"))
    def format(self, kw: Mapping[str, Any]) -> InlineKeyboardButton | None:
        parameters = self._buttons_params
        
        if self.type not in parameters:
            raise ValueError(f"Unsupported InlineKeyboardButton type: {self.type!r}")

        meta = self.meta or {}
        if invalid_meta := meta.keys() - parameters:
            warnings.warn(
                "Ignoring unsupported InlineKeyboardButton meta keys: "
                + ", ".join(sorted(invalid_meta)),
                UserWarning,
                stacklevel=2,
            )
            meta = {
                key: value for key, value in meta.items()
                if key in parameters
            }

        kw = self.with_defaults(kw)

        if self.can_format(kw):
            return InlineKeyboardButton(
                self.text.format_map(kw),
                **{self.type: self.value.format_map(kw)},
                **meta
            )

@dataclass(slots=True, kw_only=True)
class CompiledEachButton(BaseDataClass):
    """
    A button rendered once per element of the list passed to format() under `each`,
    laid out over as many rows as needed - so one template entry can produce a whole
    block of the keyboard.

    Elements are filtered and merged exactly as in CompiledEachLine: whether a given
    element is kept is entirely `item`'s own decision, this wrapper carries no
    condition, and no fallback values, of its own. `row_width` is how many buttons go
    in each row before wrapping to the next one.
    """

    DEFAULT_ROW_WIDTH: ClassVar[int] = 2

    each: str
    item: CompiledButton
    row_width: int | None = None

    @classmethod
    def compile(cls, item: TemplateEachButtonDict) -> Self:
        item["item"] = CompiledButton.compile(item["item"])
        return cls.from_dict(item, True)

    @_optional_import(("kurigram", "tg"))
    def format(self, kw: Mapping[str, Any]) -> list[list[InlineKeyboardButton]] | None:
        each = kw.get(self.each)

        if not each or not is_container(each):
            return

        rows, current = [], []

        item = self.item
        row_width = self.row_width or self.DEFAULT_ROW_WIDTH

        for raw_each in each:
            if not is_mapping(raw_each):
                continue

            if (button := item.format(ChainMap(raw_each, kw))) is not None:
                current.append(button)

            if len(current) == row_width:
                rows.append(current)
                current = []

        if current:
            rows.append(current)

        if rows:
            return rows

@dataclass(slots=True)
class CompiledButtonRow(BaseDataClass):
    """
    One fixed row of the keyboard. Compiles from a list of buttons, or from a single
    button object as a shorthand for a row holding just it.
    """

    buttons: list[CompiledButton]

    @classmethod
    def compile(cls, item: MaybeList[TemplateButtonDict]) -> Self:
        if is_mapping(item):
            item = [item]

        return cls.from_dict(
            {"buttons": [CompiledButton.compile(button) for button in item]},
            True
        )

    @_optional_import(("kurigram", "tg"))
    def format(self, kw: Mapping[str, Any]) -> list[InlineKeyboardButton] | None:
        return [btn for button in self.buttons if (btn := button.format(kw)) is not None] or None


@dataclass(slots=True, kw_only=True)
class CompiledRichMessage(CompiledDefaults):
    """
    A rich message, sent with Client.send_rich_message instead of Client.send_message.

    It carries its own content rather than reusing the template's `message`: `html`
    and `markdown` are each a block of lines written and generated exactly like
    `message`'s, and the one they are written under is the format Telegram reads them
    as - so no parse mode is involved. `default_keys` fills in values missing from the
    format() keyword arguments for this rich message's own lines.
    """

    html: list[CompiledLine | CompiledEachLine] | None = None
    markdown: list[CompiledLine | CompiledEachLine] | None = None
    is_rtl: bool | None = None
    skip_entity_detection: bool | None = None

    @classmethod
    def compile(cls, item: TemplateRichMessageDict) -> Self:
        item["html"] = compile_lines(item.get("html", None))
        item["markdown"] = compile_lines(item.get("markdown", None))

        return cls.from_dict(item, True)

    @_optional_import(("kurigram>=2.2.24", "tg"))
    def format(self, kw: Mapping[str, Any]) -> InputRichMessage | None:
        kw = self.with_defaults(kw)

        for lines, parse in ((self.html, "html"), (self.markdown, "markdown")):
            if (formatted := format_lines(lines, kw)) is not None:
                return InputRichMessage(
                    **{parse: formatted},
                    is_rtl=self.is_rtl,
                    skip_entity_detection=self.skip_entity_detection,
                )


if HAS_PYROGRAM:
    @dataclass(slots=True, kw_only=True)
    class CompiledTemplate(CompiledDefaults):
        """
        A whole message compiled from its JSON definition: the lines to join into the
        text, the keyboard to attach, and the parse mode to send them with.

        `message` and `rich_message` are two independent ways of writing the content, each
        with its own lines. A template that defines `rich_message` is sent as one, so
        format() yields a `rich_message` payload in place of `text`/`parse_mode`.
        `default_keys` fills in values missing from format()'s keyword arguments before
        anything else in the template sees them - message, buttons, and rich_message alike.
        """

        message: list[CompiledLine | CompiledEachLine] | None = None
        buttons: list[CompiledButtonRow | CompiledEachButton] | None = None
        rich_message: CompiledRichMessage | None = None
        parse_mode: ParseMode | None = None
        key_time: str | None = None


        @classmethod
        def compile(cls, template: TemplateDict, parse_mode: ParseMode | None = None, key_time: str | None = None) -> Self:
            """
            Compile one template object. `parse_mode`/`key_time` are the file-wide
            defaults, used only where the template does not set its own.

            Note this writes the compiled parts back into `template`, so the same object
            cannot be compiled twice.
            """

            template["parse_mode"] = (
                ParseMode(parse_mode)
                if (parse_mode := template.get("parse_mode", None) or parse_mode) is not None
                else None
            )
            template["key_time"] = template.get("key_time", None) or key_time
            template["message"] = compile_lines(template.get("message", None))
            template["buttons"] = [
                CompiledEachButton.compile(button) if (is_mapping(button) and button.get("each")) else CompiledButtonRow.compile(button)
                for button in template.get("buttons", [])
            ] or None
            template["rich_message"] = (
                CompiledRichMessage.compile(rich_message)
                if (rich_message := template.get("rich_message", None))
                else None
            )

            return cls.from_dict(template, True)

        def apply_key_time(self, kw: Mapping[str, Any]) -> None:
            """Fill in the timestamp key the lines can reference, unless already provided."""

            if self.key_time is not None and self.key_time not in kw:
                kw[self.key_time] = arabic_time()

        def format_message(self, kw: Mapping[str, Any]) -> str | None:
            self.apply_key_time(kw)
            return format_lines(self.message, kw)

        def format_rich_message(self, kw: Mapping[str, Any]) -> InputRichMessage | None:
            if self.rich_message is None:
                return None

            self.apply_key_time(kw)
            return self.rich_message.format(kw)

        def format_keyboard(self, kw: Mapping[str, Any]) -> InlineKeyboardMarkup | None:
            rows = []

            for buttons in (self.buttons or ()):
                row = buttons.format(kw)

                if not row:
                    continue

                # CompiledEachButton returns multiple rows, while CompiledButtonRow
                # returns a single row -- so only the former needs extend().
                if isinstance(buttons, CompiledEachButton):
                    rows.extend(row)
                else:
                    rows.append(row)

            if rows:
                return InlineKeyboardMarkup(rows)

        def format(self, **kw) -> TemplatePyroMessage:
            kw = self.with_defaults(clean_none_values(kw))

            rich_message = self.format_rich_message(kw)
            content = (
                {"rich_message": rich_message}
                if rich_message is not None
                else {"text": self.format_message(kw), "parse_mode": self.parse_mode}
            )

            return clean_none_values({
                **content,
                "reply_markup": self.format_keyboard(kw)
            })

        @classmethod
        def compile_from_file(
            cls,
            path: PathLike,
            parse_mode: ParseMode | None = None,
            key_time: str | None = None,
            ) -> NestedStrKeyDict[CompiledTemplate]:
            """
            Compile every template in a JSON file.

            Besides the templates themselves, the file may set `parse_mode`/`key_time`
            defaults for all of them, and hold definitions that repeated values point at
            with a standard JSON Reference (`{"$ref": "#/..."}`); those are resolved
            before compiling, so a shared value is written once.
            """

            try:
                templates = load_ref_json(path)
            except ImportError:
                templates = read_json(path)

            assert isinstance(templates, dict)

            return cls.compile_template(
                templates,
                ParseMode(parse_mode) if (parse_mode := templates.pop("parse_mode", None) or parse_mode) is not None else None,
                templates.pop("key_time", None) or key_time,
            )

        @overload
        @classmethod
        def compile_template(
            cls,
            template: NestedStrKeyDict[JsonValue],
            parse_mode: ParseMode | None = None,
            key_time: str | None = None,
            *,
            is_single_template: _True,
            ) -> Self: ...
        @overload
        @classmethod
        def compile_template(
            cls,
            template: NestedStrKeyDict[JsonValue],
            parse_mode: ParseMode | None = None,
            key_time: str | None = None,
            *,
            is_single_template: _False = False,
            ) -> NestedStrKeyDict[CompiledTemplate]: ...
        @classmethod
        def compile_template(
            cls,
            template: NestedStrKeyDict[JsonValue],
            parse_mode: ParseMode | None = None,
            key_time: str | None = None,
            *, 
            is_single_template: bool = False,
            ): #type: ignore
            """
            Compile a mapping of templates, recursing into any group marked
            `"nested": true` so the result mirrors the file's own structure.

            `is_single_template=True` compiles `template` as one template and
            returns that CompiledTemplate itself, rather than a mapping of them
            -- which is how the recursion below bottoms out on a leaf entry.

            Entries whose name starts with `$` are skipped: those hold the definitions
            that `$ref` points at, not templates.
            """

            if is_single_template:
                return cls.compile(template, parse_mode, key_time) #type: ignore


            return {
                # is_single_template is a plain bool here, so it matches
                # neither literal overload -- the two branches it picks
                # between are exactly the overloads' own two return types.
                name: cls.compile_template(
                    templ, parse_mode, key_time, #type: ignore
                    is_single_template=not templ.pop("nested", False) #type: ignore
                )
                for name, templ in template.items()
                if isinstance(templ, dict) and not name.startswith("$")
            }
else:
    CompiledTemplate = _unavailable_class("CompiledTemplate", ("kurigram", "tg"))




__all__ = (
    "CompiledDefaults",
    "CompiledConditional",
    "CompiledLine",
    "CompiledEachLine",
    "CompiledButton",
    "CompiledEachButton",
    "CompiledButtonRow",
    "CompiledRichMessage",
    "CompiledTemplate",
)
