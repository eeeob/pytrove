from __future__ import annotations as _annotations

import importlib.util
import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import pytest

from pytrove.models import CompiledButtonRow, CompiledEachButton, CompiledTemplate
from pytrove.models.template_models import template

if TYPE_CHECKING:
    from pathlib import Path

HAS_PYROGRAM = importlib.util.find_spec("pyrogram") is not None
needs_pyrogram = pytest.mark.skipif(not HAS_PYROGRAM, reason="needs the tg extra")


def _button(text: str = "{name}", **extra: object) -> dict[str, object]:
    """Return a callback button definition."""
    return {"text": text, "type": "callback_data", "value": "id:{name}", **extra}


@needs_pyrogram
def test_template_compiles_and_formats_a_whole_message() -> None:
    from pyrogram.enums import ParseMode  # noqa: PLC0415 - optional `pyrogram`, present only when `needs_pyrogram` lets the test run

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
    assert [[b.text for b in row] for row in out["reply_markup"].inline_keyboard] == [
        ["you"],
        ["a"],
    ]
    assert CompiledTemplate().format() == {}
    assert CompiledTemplate().format_rich_message({}) is None

    rich = CompiledTemplate.compile(
        {"message": ["plain"], "rich_message": {"html": ["<b>{time}</b>"]}}, key_time="time"
    )
    payload = rich.format(time="now")
    assert set(payload) == {"rich_message"}
    assert payload["rich_message"].html == "<b>now</b>"


@needs_pyrogram
def test_apply_key_time_layers_the_time_without_touching_kw() -> None:
    template = CompiledTemplate.compile({"message": ["{time}"]}, key_time="time")
    kw: dict[str, Any] = {"name": "a"}
    view = template.apply_key_time(kw)
    assert kw == {"name": "a"}
    assert view["name"] == "a"
    assert isinstance(view["time"], str)
    assert template.apply_key_time({"time": "set"})["time"] == "set"
    assert CompiledTemplate.compile({"message": ["x"]}).apply_key_time(kw) is kw


@needs_pyrogram
def test_format_message_accepts_a_read_only_mapping() -> None:
    template = CompiledTemplate.compile({"message": ["at {time}"]}, key_time="time")
    assert template.format_message(MappingProxyType({})).startswith("at ")


@needs_pyrogram
def test_format_shows_the_buttons_the_same_key_time_as_the_text() -> None:
    template = CompiledTemplate.compile(
        {"message": ["{time}"], "buttons": [_button("{time}")]}, key_time="time"
    )
    out = template.format(name="a")
    assert out["reply_markup"].inline_keyboard[0][0].text == out["text"]


@needs_pyrogram
def test_template_compile_rewrites_the_dict_and_keyboard_skips_empty_rows() -> None:
    from pyrogram.enums import ParseMode  # noqa: PLC0415 - optional `pyrogram`, present only when `needs_pyrogram` lets the test run

    raw = {
        "message": ["a"],
        "buttons": [[_button(all_of=["x"])], {"each": "people", "item": _button()}, _button()],
        "rich_message": {"markdown": ["m"]},
        "parse_mode": "markdown",
    }
    template = CompiledTemplate.compile(raw)

    assert raw["parse_mode"] is ParseMode.MARKDOWN and raw["key_time"] is None
    assert raw["message"] == template.message and raw["rich_message"] == template.rich_message
    assert [type(part) for part in raw["buttons"]] == [
        CompiledButtonRow,
        CompiledEachButton,
        CompiledButtonRow,
    ]

    keyboard = template.format_keyboard({"name": "n", "people": []})
    assert [[b.text for b in row] for row in keyboard.inline_keyboard] == [["n"]]
    keyboard = template.format_keyboard({"name": "n", "x": 1, "people": [{"name": "p"}]})
    assert [[b.text for b in row] for row in keyboard.inline_keyboard] == [["n"], ["p"], ["n"]]


@needs_pyrogram
def test_compile_from_file_nests_skips_definitions_and_applies_file_defaults(
    tmp_path: Path,
) -> None:
    from pyrogram.enums import ParseMode  # noqa: PLC0415 - optional `pyrogram`, present only when `needs_pyrogram` lets the test run

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


@needs_pyrogram
def test_compile_from_file_reads_plain_json_without_the_json_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_jsonref(path: object) -> object:
        """Fail as `load_ref_json` does when `jsonref` is absent."""
        msg = "pytrove[json]"
        raise ImportError(msg)

    monkeypatch.setattr(template, "load_ref_json", no_jsonref)
    path = tmp_path / "templates.json"
    path.write_text(json.dumps({"top": {"message": ["plain"]}}), encoding="utf-8")

    assert CompiledTemplate.compile_from_file(path)["top"].format()["text"] == "plain"


@pytest.mark.skipif(HAS_PYROGRAM, reason="checks the error raised without the tg extra")
def test_template_needs_the_tg_extra() -> None:
    with pytest.raises(ImportError, match="pytrove\\[tg\\]"):
        CompiledTemplate()
