from __future__ import annotations as _annotations

import importlib.util

import pytest

from pytrove.models import CompiledLine, CompiledRichMessage

HAS_PYROGRAM = importlib.util.find_spec("pyrogram") is not None
needs_pyrogram = pytest.mark.skipif(not HAS_PYROGRAM, reason="needs the tg extra")


@needs_pyrogram
def test_rich_message_uses_the_first_block_that_renders() -> None:
    rich = CompiledRichMessage.compile({"html": [{"text": "{a}", "any_of": ["a"]}], "markdown": ["*{b}*"], "is_rtl": True})
    message = rich.format({"b": "x"})
    assert (message.html, message.markdown, message.is_rtl) == (None, "*x*", True)
    assert CompiledRichMessage().format({}) is None


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
