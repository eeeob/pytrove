from __future__ import annotations as _annotations

import importlib.util
import json
from collections import ChainMap
from pathlib import Path

import pytest

from pytrove.models import (
    CompiledButton,
    CompiledButtonRow,
    CompiledConditional,
    CompiledDefaults,
    CompiledEachButton,
    CompiledEachLine,
    CompiledLine,
    CompiledRichMessage,
    CompiledTemplate,
)
from pytrove.models.template_models._internal import _compile_lines, _format_lines

HAS_PYROGRAM = importlib.util.find_spec("pyrogram") is not None
needs_pyrogram = pytest.mark.skipif(not HAS_PYROGRAM, reason="needs the tg extra")


def _button(text: str = "{name}", **extra: object) -> dict[str, object]:
    """Return a callback button definition."""
    return {"text": text, "type": "callback_data", "value": "id:{name}", **extra}


def test_defaults_sit_beneath_the_passed_values() -> None:
    assert CompiledDefaults().with_defaults({"a": 1}) == {"a": 1}
    merged = CompiledDefaults({"a": 0, "b": 2}).with_defaults({"a": 1})
    assert isinstance(merged, ChainMap)
    assert dict(merged) == {"a": 1, "b": 2}


def test_conditional_normalises_and_checks_its_keys() -> None:
    part = CompiledConditional(any_of=["a", "b"], all_of="c")
    assert part.any_of == frozenset({"a", "b"}) and part.all_of == frozenset({"c"})
    assert CompiledConditional(any_of=[]).any_of is None

    assert part.can_format({"a": 1, "c": 1})
    assert not part.can_format({"a": 1})
    assert not part.can_format({"c": 1})
    assert CompiledConditional().can_format({})


def test_line_compiles_from_text_or_definition_and_honours_defaults() -> None:
    assert CompiledLine.compile("hi {name}").format({"name": "x"}) == "hi x"

    line = CompiledLine.compile({"text": "{a}{b}", "all_of": ["b"], "default_keys": {"b": "!"}})
    assert line.format({"a": "x"}) == "x!"
    assert CompiledLine.compile({"text": "{a}", "any_of": ["a"]}).format({}) is None


def test_each_line_renders_one_line_per_mapping_element() -> None:
    line = CompiledEachLine.compile({"each": "items", "item": {"text": "{n} {sep}", "all_of": ["n"]}})
    kw = {"sep": "-", "items": [{"n": 1}, "skip", {}, {"n": 2}]}

    assert line.format(kw) == "1 -\n2 -"
    assert line.format({"items": [{}]}) is None
    assert line.format({"items": 5}) is None
    assert line.format({}) is None


def test_compile_and_format_line_blocks() -> None:
    lines = _compile_lines(["a", {"text": "{b}", "any_of": ["b"]}, {"each": "xs", "item": "{x}"}])
    assert [type(line) for line in lines] == [CompiledLine, CompiledLine, CompiledEachLine]
    assert _format_lines(lines, {"xs": [{"x": 1}]}) == "a\n1"
    assert _compile_lines([]) is None and _compile_lines(None) is None
    assert _format_lines(None, {}) is None


@needs_pyrogram
def test_button_renders_and_rejects_bad_types() -> None:
    from pyrogram.enums import ButtonStyle

    button = CompiledButton.compile(_button(meta={"style": ButtonStyle.DANGER.value}))
    assert button.meta == {"style": ButtonStyle.DANGER}
    rendered = button.format({"name": "a"})
    assert (rendered.text, rendered.callback_data, rendered.style) == ("a", "id:a", ButtonStyle.DANGER)
    assert CompiledButton.compile(_button(all_of=["x"])).format({"name": "a"}) is None
    assert "url" in CompiledButton._buttons_params

    with pytest.raises(ValueError, match="Unsupported"):
        CompiledButton(text="t", type="nope", value="v").format({})

    with pytest.warns(UserWarning, match="unknown"):
        assert CompiledButton.compile(_button(meta={"unknown": 1})).format({"name": "a"}) is not None


@needs_pyrogram
def test_each_button_wraps_rows_and_button_row_drops_hidden_buttons() -> None:
    each = CompiledEachButton.compile({"each": "people", "item": _button(), "row_width": 2})
    rows = each.format({"people": [{"name": n} for n in "abc"] + ["skip"]})
    assert [[b.text for b in row] for row in rows] == [["a", "b"], ["c"]]
    assert each.format({"people": []}) is None
    assert each.format({"people": 5}) is None
    conditional = CompiledEachButton.compile({"each": "people", "item": _button(all_of=["name"])})
    assert conditional.format({"people": [{"other": 1}]}) is None
    assert CompiledEachButton.DEFAULT_ROW_WIDTH == 2

    row = CompiledButtonRow.compile(_button())
    assert [b.text for b in row.format({"name": "z"})] == ["z"]
    hidden = CompiledButtonRow.compile([_button(any_of=["x"])])
    assert hidden.format({"name": "z"}) is None


@needs_pyrogram
def test_rich_message_uses_the_first_block_that_renders() -> None:
    rich = CompiledRichMessage.compile({"html": [{"text": "{a}", "any_of": ["a"]}], "markdown": ["*{b}*"], "is_rtl": True})
    message = rich.format({"b": "x"})
    assert (message.html, message.markdown, message.is_rtl) == (None, "*x*", True)
    assert CompiledRichMessage().format({}) is None


@needs_pyrogram
def test_template_compiles_and_formats_a_whole_message() -> None:
    from pyrogram.enums import ParseMode

    template = CompiledTemplate.compile(
        {
            "message": ["hi {name}", {"text": "{time}", "any_of": ["time"]}],
            "buttons": [_button(), {"each": "people", "item": _button()}],
            "default_keys": {"name": "you"},
        },
        parse_mode="html",
        key_time="time",
    )
    assert template.parse_mode is ParseMode.HTML

    out = template.format(people=[{"name": "a"}], ignored=None)
    assert out["text"].startswith("hi you\n")
    assert out["parse_mode"] is ParseMode.HTML
    assert [[b.text for b in row] for row in out["reply_markup"].inline_keyboard] == [["you"], ["a"]]
    assert CompiledTemplate().format() == {}
    assert CompiledTemplate().format_rich_message({}) is None

    rich = CompiledTemplate.compile({"message": ["plain"], "rich_message": {"html": ["<b>{time}</b>"]}}, key_time="time")
    payload = rich.format(time="now")
    assert set(payload) == {"rich_message"}
    assert payload["rich_message"].html == "<b>now</b>"


@needs_pyrogram
def test_compile_from_file_nests_skips_definitions_and_applies_file_defaults(tmp_path: Path) -> None:
    from pyrogram.enums import ParseMode

    path = tmp_path / "templates.json"
    path.write_text(
        json.dumps(
            {
                "parse_mode": "markdown",
                "$defs": {"greet": "hello"},
                "top": {"message": [{"$ref": "#/$defs/greet"}]},
                "group": {"nested": True, "inner": {"message": ["x"], "parse_mode": "html"}},
                "not_a_template": 5,
            }
        ),
        encoding="utf-8",
    )

    templates = CompiledTemplate.compile_from_file(path)
    assert set(templates) == {"top", "group"}
    assert templates["top"].parse_mode is ParseMode.MARKDOWN
    assert templates["group"]["inner"].parse_mode is ParseMode.HTML
    assert templates["group"]["inner"].format()["text"] == "x"

    single = CompiledTemplate.compile_template({"message": ["one"]}, is_single_template=True)
    assert isinstance(single, CompiledTemplate)

    path.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="JSON object"):
        CompiledTemplate.compile_from_file(path)


@pytest.mark.skipif(HAS_PYROGRAM, reason="checks the error raised without the tg extra")
def test_template_parts_need_the_tg_extra() -> None:
    with pytest.raises(ImportError, match="pytrove\\[tg\\]"):
        CompiledTemplate()

    with pytest.raises(ImportError, match="pytrove\\[tg\\]"):
        CompiledButton(text="t", type="url", value="v").format({})

    assert CompiledLine.compile("still works").format({}) == "still works"
