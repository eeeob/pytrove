from __future__ import annotations as _annotations

import pytest

from pytrove.models import CompiledLine, CompiledRichMessage
from pytrove.models.template_models.template import HAS_PYROGRAM

needs_pyrogram = pytest.mark.skipif(not HAS_PYROGRAM, reason="needs the tg extra")

_BLOCKS = {"html": [{"text": "<b>{a}</b>", "any_of": ["a"]}], "markdown": ["*{b}*"]}


@needs_pyrogram
@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"a": 1, "b": 2}, ("<b>1</b>", None)),
        ({"b": 2}, (None, "*2*")),
    ],
)
def test_rich_message_uses_the_first_block_that_renders(
    kw: dict[str, int], expected: tuple[str | None, str | None]
) -> None:
    message = CompiledRichMessage.compile({**_BLOCKS, "is_rtl": True}).format(kw)
    assert (message.html, message.markdown, message.is_rtl) == (*expected, True)


@needs_pyrogram
def test_rich_message_is_none_when_no_block_renders() -> None:
    rich = CompiledRichMessage.compile(
        {"html": [{"text": "x", "all_of": ["a"]}], "markdown": [{"text": "y", "all_of": ["a"]}]}
    )
    assert rich.format({}) is None
    assert CompiledRichMessage().format({}) is None


@needs_pyrogram
def test_rich_message_applies_its_defaults_and_passes_its_flags_through() -> None:
    rich = CompiledRichMessage.compile(
        {"html": ["{a}"], "default_keys": {"a": "d"}, "skip_entity_detection": True}
    )
    message = rich.format({})
    assert (message.html, message.skip_entity_detection, message.is_rtl) == ("d", True, None)
    assert rich.format({"a": "given"}).html == "given"


@pytest.mark.skipif(HAS_PYROGRAM, reason="checks the error raised without the tg extra")
def test_rich_message_format_needs_the_tg_extra() -> None:
    with pytest.raises(ImportError, match="pytrove\\[tg\\]"):
        CompiledRichMessage.compile({"html": ["x"]}).format({})


def test_rich_message_compile_rewrites_the_dict_in_place() -> None:
    raw_rich = {"html": ["a"]}
    rich = CompiledRichMessage.compile(raw_rich)
    assert raw_rich["markdown"] is None
    assert raw_rich["html"] == rich.html
    assert [type(line) for line in raw_rich["html"]] == [CompiledLine]
