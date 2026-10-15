"""A whole message template, compiled from its JSON definition."""

from __future__ import annotations as _annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast, overload

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

try:
    from pyrogram.enums import ParseMode
    from pyrogram.types import InlineKeyboardMarkup, InputRichMessage
except ImportError:
    HAS_PYROGRAM = False
else:
    HAS_PYROGRAM = True

from ..._internal._optional import _unavailable_class
from ...data_tools import clean_none_values
from ...date_tools import arabic_time
from ...files_tools import load_ref_json, read_json
from ...typings import JsonValue, NestedStrKeyDict, PathLike, TemplateDict, TemplatePyroMessage, _False, _True
from ...validate_tools import is_mapping
from ._internal import _compile_lines, _format_lines
from .buttons import CompiledButtonRow, CompiledEachButton
from .conditions import CompiledDefaults
from .lines import CompiledEachLine, CompiledLine
from .rich import CompiledRichMessage

if HAS_PYROGRAM:

    @dataclass(slots=True, kw_only=True)
    class CompiledTemplate(CompiledDefaults):
        """A whole message: the lines joined into its text, its keyboard, and the parse mode to send them with.

        `message` and `rich_message` are two independent ways of writing the
        content. A template that defines `rich_message` is sent as one, so
        `format()` returns a `rich_message` payload in place of
        `text`/`parse_mode`. `default_keys` fills in missing `format()`
        arguments before any part of the template sees them.

        Attributes:
            message: The lines of the text.
            buttons: The keyboard, as fixed rows and repeated button blocks.
            rich_message: The rich message to send instead of `message`.
            parse_mode: The parse mode `message` is sent with.
            key_time: A `format()` key filled with `arabic_time()` when not passed.
        """

        message: list[CompiledLine | CompiledEachLine] | None = None
        buttons: list[CompiledButtonRow | CompiledEachButton] | None = None
        rich_message: CompiledRichMessage | None = None
        parse_mode: ParseMode | None = None
        key_time: str | None = None

        @classmethod
        def compile(cls, template: TemplateDict, parse_mode: ParseMode | None = None, key_time: str | None = None) -> Self:
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
            template["parse_mode"] = (
                ParseMode(parse_mode)
                if (parse_mode := template.get("parse_mode", None) or parse_mode) is not None
                else None
            )
            template["key_time"] = template.get("key_time", None) or key_time
            template["message"] = _compile_lines(template.get("message", None))
            template["buttons"] = [
                CompiledEachButton.compile(button)
                if (is_mapping(button) and button.get("each"))
                else CompiledButtonRow.compile(button)
                for button in template.get("buttons", [])
            ] or None
            template["rich_message"] = (
                CompiledRichMessage.compile(rich_message)
                if (rich_message := template.get("rich_message", None))
                else None
            )

            return cls.from_dict(template, True)

        def apply_key_time(self, kw: Mapping[str, Any]) -> None:
            """Fill in the `key_time` key the lines can reference, unless already passed.

            Args:
                kw: The `format()` keyword arguments; updated in place.
            """
            if self.key_time is not None and self.key_time not in kw:
                kw[self.key_time] = arabic_time()

        def format_message(self, kw: Mapping[str, Any]) -> str | None:
            """Render `message`.

            Args:
                kw: The `format()` keyword arguments.

            Returns:
                The text, or `None` if no line rendered.
            """
            self.apply_key_time(kw)
            return _format_lines(self.message, kw)

        def format_rich_message(self, kw: Mapping[str, Any]) -> InputRichMessage | None:
            """Render `rich_message`.

            Args:
                kw: The `format()` keyword arguments.

            Returns:
                The rich message, or `None` if there is none or it did not render.
            """
            if self.rich_message is None:
                return None

            self.apply_key_time(kw)
            return self.rich_message.format(kw)

        def format_keyboard(self, kw: Mapping[str, Any]) -> InlineKeyboardMarkup | None:
            """Render the keyboard.

            Args:
                kw: The `format()` keyword arguments.

            Returns:
                The keyboard, or `None` if no button rendered.
            """
            rows = []

            for buttons in self.buttons or ():
                row = buttons.format(kw)

                if not row:
                    continue

                # `CompiledEachButton` returns several rows and `CompiledButtonRow`
                # one, so only the former needs `extend()`.
                if isinstance(buttons, CompiledEachButton):
                    rows.extend(row)
                else:
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
            kw = self.with_defaults(clean_none_values(kw))

            rich_message = self.format_rich_message(kw)
            content = (
                {"rich_message": rich_message}
                if rich_message is not None
                else {"text": self.format_message(kw), "parse_mode": self.parse_mode}
            )

            return clean_none_values({**content, "reply_markup": self.format_keyboard(kw)})

        @classmethod
        def compile_from_file(
            cls,
            path: PathLike,
            parse_mode: ParseMode | None = None,
            key_time: str | None = None,
        ) -> NestedStrKeyDict[CompiledTemplate]:
            """Compile every template in a JSON file.

            The file may also set `parse_mode`/`key_time` defaults for all of
            its templates, and hold definitions that repeated values point at
            with a JSON Reference (`{"$ref": "#/..."}`). References are
            resolved before compiling when the `jsonref` extra is installed.

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
                ParseMode(parse_mode)
                if (parse_mode := templates.pop("parse_mode", None) or parse_mode) is not None
                else None,
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
        ) -> Self | NestedStrKeyDict[CompiledTemplate]:
            """Compile a mapping of templates, recursing into each group marked `"nested": true`.

            Entries whose name starts with `$` are skipped: they hold the
            definitions `$ref` points at, not templates.

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
    CompiledTemplate = _unavailable_class("CompiledTemplate", ("kurigram", "tg"))


__all__ = ("CompiledTemplate",)
