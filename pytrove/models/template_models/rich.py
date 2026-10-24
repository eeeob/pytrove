"""The rich message a template can be sent as."""

from __future__ import annotations as _annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

try:
    from pyrogram.types import InputRichMessage  # type: ignore[import-not-found]  # Optional: the `tg` extra.
except ImportError:
    pass

from ..._internal import _optional_import
from ._internal import _compile_lines, _CompiledRichMessageDict, _format_lines
from .conditions import CompiledDefaults
from .lines import CompiledEachLine, CompiledLine

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ...typings import TemplateRichMessageDict


@dataclass(slots=True, kw_only=True)
class CompiledRichMessage(CompiledDefaults):
    """A rich message, sent with `Client.send_rich_message` instead of `Client.send_message`.

    It carries its own lines rather than reusing the template's `message`.
    The format a block is written under is the format Telegram reads it as,
    so no parse mode is involved; the first block that renders is used.
    """

    html: list[CompiledLine | CompiledEachLine] | None = None
    """Lines read as HTML; tried first."""

    markdown: list[CompiledLine | CompiledEachLine] | None = None
    """Lines read as Markdown; used only if no `html` line rendered."""

    is_rtl: bool | None = None
    """Passed to `InputRichMessage` as is."""

    skip_entity_detection: bool | None = None
    """Passed to `InputRichMessage` as is."""

    @classmethod
    def compile(cls, item: TemplateRichMessageDict) -> Self:
        """Compile the definition, its line blocks included.

        Args:
            item: The definition; its blocks are replaced by the compiled lines.

        Returns:
            The compiled rich message.
        """
        # The dict is rewritten in place into its compiled shape.
        compiled = cast("_CompiledRichMessageDict", item)
        compiled["html"] = _compile_lines(item.get("html", None))
        compiled["markdown"] = _compile_lines(item.get("markdown", None))

        return cls.from_dict(compiled, True)

    @_optional_import(("kurigram>=2.2.24", "tg"))
    def format(self, kw: Mapping[str, Any]) -> InputRichMessage | None:
        """Render the first block that produces text.

        Args:
            kw: The `format()` keyword arguments.

        Returns:
            The rich message, or `None` if no block rendered.
        """
        kw = self.with_defaults(kw)

        for lines, parse in ((self.html, "html"), (self.markdown, "markdown")):
            if (formatted := _format_lines(lines, kw)) is not None:
                return InputRichMessage(
                    html=formatted if parse == "html" else None,
                    markdown=formatted if parse == "markdown" else None,
                    is_rtl=self.is_rtl,
                    skip_entity_detection=self.skip_entity_detection,
                )

        return None


__all__ = ("CompiledRichMessage",)
