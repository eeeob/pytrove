"""A whole message template, compiled from its JSON definition."""

from __future__ import annotations as _annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast, overload

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

try:
    from pyrogram.enums import ParseMode
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputRichMessage
except ImportError:
    HAS_PYROGRAM = False
else:
    HAS_PYROGRAM = True

from ..._internal._optional import _unavailable_class
from ...data_tools import clean_none_values
from ...date_tools import arabic_time
from ...files_tools import load_ref_json, read_json
from ...typings import (
    JsonValue,
    NestedStrKeyDict,
    PathLike,
    TemplateDict,
    TemplatePyroMessage,
    _False,
    _True,
)
from ._internal import (
    _chain_mappings,
    _compile_lines,
    _CompiledTemplateDict,
    _format_lines,
    _is_each_button,
)
from .buttons import CompiledButtonRow, CompiledEachButton
from .conditions import CompiledDefaults
from .lines import CompiledEachLine, CompiledLine
from .rich import CompiledRichMessage

if TYPE_CHECKING:
    from collections.abc import Mapping

if HAS_PYROGRAM:

    @dataclass(slots=True, kw_only=True)
    class CompiledTemplate(CompiledDefaults):
        """A whole message: the lines joined into its text, its keyboard, and the parse mode to send them with.

        `message` and `rich_message` are two independent ways of writing the
        content. A template that defines `rich_message` is sent as one, so
        `format()` returns a `rich_message` payload in place of
        `text`/`parse_mode`. `default_keys` fills in missing `format()`
        arguments before any part of the template sees them.
        """

        message: list[CompiledLine | CompiledEachLine] | None = None
        """The lines of the text, joined by newlines when rendered."""

        buttons: list[CompiledButtonRow | CompiledEachButton] | None = None
        """The keyboard, as fixed rows and repeated button blocks; `None` for no keyboard."""

        rich_message: CompiledRichMessage | None = None
        """The rich message to send instead of `message`; when it renders, `text`/`parse_mode` are not returned."""

        parse_mode: ParseMode | None = None
        """The parse mode `message` is sent with; the file-wide default already applied."""

        key_time: str | None = None
        """A `format()` key filled with `arabic_time()` when not passed; `None` fills nothing."""

        @classmethod
        def compile(
            cls,
            template: TemplateDict,
            parse_mode: ParseMode | None = None,
            key_time: str | None = None,
        ) -> Self:
            """Compile one template definition.

            The compiled parts are written back into `template`, so the same
            object cannot be compiled twice.

            Args:
                template: The definition.
                parse_mode: The file-wide default, used if the template sets none.
                key_time: The file-wide default, used if the template sets none.

            Returns:
                The compiled template.
            """
            # The dict is rewritten in place into its compiled shape.
            compiled = cast(_CompiledTemplateDict, template)
            compiled["parse_mode"] = (
                ParseMode(mode)
                if (mode := template.get("parse_mode", None) or parse_mode) is not None
                else None
            )
            compiled["key_time"] = template.get("key_time", None) or key_time
            compiled["message"] = _compile_lines(template.get("message", None))
            compiled["buttons"] = [
                CompiledEachButton.compile(button)
                if _is_each_button(button)
                else CompiledButtonRow.compile(button)
                for button in template.get("buttons", [])
            ] or None
            compiled["rich_message"] = (
                CompiledRichMessage.compile(rich_message)
                if (rich_message := template.get("rich_message", None))
                else None
            )

            return cls.from_dict(compiled, True)

        def apply_key_time(self, kw: Mapping[str, Any]) -> Mapping[str, Any]:
            """Layer the `key_time` key the lines can reference over `kw`, unless already passed.

            `kw` itself is never changed, so a read-only mapping works too.

            Args:
                kw: The `format()` keyword arguments.

            Returns:
                `kw` itself, or a view of it with `key_time` filled in.
            """
            if self.key_time is None or self.key_time in kw:
                return kw

            return _chain_mappings({self.key_time: arabic_time()}, kw)

        def format_message(self, kw: Mapping[str, Any]) -> str | None:
            """Render `message`.

            Args:
                kw: The `format()` keyword arguments.

            Returns:
                The text, or `None` if no line rendered.
            """
            return _format_lines(self.message, self.apply_key_time(kw))

        def format_rich_message(self, kw: Mapping[str, Any]) -> InputRichMessage | None:
            """Render `rich_message`.

            Args:
                kw: The `format()` keyword arguments.

            Returns:
                The rich message, or `None` if there is none or it did not render.
            """
            if self.rich_message is None:
                return None

            return self.rich_message.format(self.apply_key_time(kw))

        def format_keyboard(self, kw: Mapping[str, Any]) -> InlineKeyboardMarkup | None:
            """Render the keyboard.

            Args:
                kw: The `format()` keyword arguments.

            Returns:
                The keyboard, or `None` if no button rendered.
            """
            rows: list[list[InlineKeyboardButton]] = []

            for buttons in self.buttons or ():
                # `CompiledEachButton` returns several rows and `CompiledButtonRow`
                # one, so only the former needs `extend()`.
                if isinstance(buttons, CompiledEachButton):
                    if each_rows := buttons.format(kw):
                        rows.extend(each_rows)
                elif row := buttons.format(kw):
                    rows.append(row)

            if rows:
                return InlineKeyboardMarkup(rows)

            return None

        def format(self, **kw: Any) -> TemplatePyroMessage:
            """Render the whole message, ready to pass to pyrogram.

            Args:
                **kw: The values the template's parts reference; `None` values are ignored.

            Returns:
                `rich_message` or `text`/`parse_mode`, plus `reply_markup`, with `None` values dropped.
            """
            # Applied once here, so the text, the rich message and the buttons all see one time.
            values = self.apply_key_time(self.with_defaults(clean_none_values(kw)))

            rich_message = self.format_rich_message(values)
            content = (
                {"rich_message": rich_message}
                if rich_message is not None
                else {"text": self.format_message(values), "parse_mode": self.parse_mode}
            )

            # `clean_none_values` drops the `None` values that no `TemplatePyroMessage`
            # key can hold, which its `_T -> _T` signature cannot express.
            return cast(
                TemplatePyroMessage,
                clean_none_values({**content, "reply_markup": self.format_keyboard(values)}),
            )

        @classmethod
        def compile_from_file(
            cls,
            path: PathLike,
            parse_mode: ParseMode | None = None,
            key_time: str | None = None,
        ) -> NestedStrKeyDict[Self]:
            """Compile every template in a JSON file.

            The file may also set `parse_mode`/`key_time` defaults for all of
            its templates, and hold definitions that repeated values point at
            with a JSON Reference (`{"$ref": "#/..."}`). References are
            resolved before compiling when the `json` extra is installed.

            Args:
                path: The JSON file.
                parse_mode: The default when the file sets none.
                key_time: The default when the file sets none.

            Returns:
                The compiled templates, nested as the file nests them.

            Raises:
                TypeError: If the file does not hold a JSON object.
            """
            try:
                templates = load_ref_json(path)
            except ImportError:
                templates = read_json(path)

            if not isinstance(templates, dict):
                msg = f"a template file must hold a JSON object, not {type(templates).__name__}"
                raise TypeError(msg)

            return cls.compile_template(
                templates,
                ParseMode(mode)
                if (mode := templates.pop("parse_mode", None) or parse_mode) is not None
                else None,
                # The file format holds `key_time` as a string; like every other template
                # key it is taken from the JSON unchecked.
                cast(str | None, templates.pop("key_time", None)) or key_time,
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
        ) -> NestedStrKeyDict[Self]: ...
        @classmethod
        def compile_template(
            cls,
            template: NestedStrKeyDict[JsonValue],
            parse_mode: ParseMode | None = None,
            key_time: str | None = None,
            *,
            is_single_template: bool = False,
        ) -> Self | NestedStrKeyDict[Self]:
            """Compile a mapping of templates, recursing into each group marked `"nested": true`.

            Entries whose name starts with `$` are skipped: they hold the
            definitions `$ref` points at, not templates. Entries that are not
            JSON objects are skipped too.

            Args:
                template: The templates, or one template with `is_single_template`.
                parse_mode: The default for templates that set none.
                key_time: The default for templates that set none.
                is_single_template: Compile `template` as one template.

            Returns:
                The one compiled template with `is_single_template`, otherwise
                the compiled templates nested as `template` nests them.
            """
            if is_single_template:
                return cls.compile(cast(TemplateDict, template), parse_mode, key_time)

            return {
                name: (
                    cls.compile_template(templ, parse_mode, key_time)
                    if templ.pop("nested", False)
                    else cls.compile_template(templ, parse_mode, key_time, is_single_template=True)
                )
                for name, templ in template.items()
                if isinstance(templ, dict) and not name.startswith("$")
            }

else:
    CompiledTemplate = _unavailable_class("CompiledTemplate", ("kurigram>=2.2.24", "tg"))


__all__ = ("CompiledTemplate",)
