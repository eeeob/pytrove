"""Helpers private to the template models."""

from __future__ import annotations as _annotations

from collections.abc import Mapping
from typing import Any

from ...typings import TemplateEachLineDict, TemplateLineDict
from ...validate_tools import is_mapping
from .lines import CompiledEachLine, CompiledLine


def _compile_lines(
    lines: list[str | TemplateLineDict | TemplateEachLineDict] | None,
) -> list[CompiledLine | CompiledEachLine] | None:
    """Compile a block of lines: the shape `message` and each rich message format share.

    Args:
        lines: The block's line definitions.

    Returns:
        The compiled lines, or `None` for an empty block, so it is absent rather than blank.
    """
    return [
        CompiledEachLine.compile(line) if (is_mapping(line) and line.get("each")) else CompiledLine.compile(line)
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


__all__ = ("_compile_lines", "_format_lines")
