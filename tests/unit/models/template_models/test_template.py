from __future__ import annotations as _annotations

import importlib.util
import json
import sys
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import pytest

import pytrove._internal
from pytrove.models import CompiledButtonRow, CompiledEachButton, CompiledTemplate
from pytrove.models.template_models import template as template_module
from pytrove.models.template_models.template import HAS_PYROGRAM

if TYPE_CHECKING:
    from pathlib import Path

needs_pyrogram = pytest.mark.skipif(not HAS_PYROGRAM, reason="needs the tg extra")


def _button(text: str = "{name}", **extra: object) -> dict[str, object]:
    """Return a callback button definition."""
    return {"text": text, "type": "callback_data", "value": "id:{name}", **extra}


def _write(path: Path, content: object) -> Path:
    """Write `content` as JSON to `path` and return it."""
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


@pytest.fixture
def fixed_time(monkeypatch: pytest.MonkeyPatch) -> str:
    """Make `arabic_time()` return a fixed string."""
    monkeypatch.setattr(template_module, "arabic_time", lambda: "T")
    return "T"


@needs_pyrogram
def test_template_compiles_and_formats_a_whole_message(fixed_time: str) -> None:
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

    out = template.format(people=[{"name": "a"}], name=None)
    assert out["text"] == f"hi you\n{fixed_time}"
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
def test_format_drops_only_top_level_none_arguments() -> None:
    template = CompiledTemplate.compile({"message": ["{r}"]})
    assert template.format(r=(1, None, 2))["text"] == "(1, None, 2)"
    assert template.format(r=range(3))["text"] == "range(0, 3)"
    assert template.format(r={"a": None})["text"] == "{'a': None}"


@needs_pyrogram
def test_rich_message_that_renders_nothing_falls_back_to_text() -> None:
    template = CompiledTemplate.compile(
        {"message": ["plain"], "rich_message": {"html": [{"text": "x", "all_of": ["k"]}]}}
    )
    assert set(template.format()) == {"text"}
    assert template.format()["text"] == "plain"
    assert set(template.format(k=1)) == {"rich_message"}


@needs_pyrogram
def test_empty_or_null_parts_compile_to_none() -> None:
    template = CompiledTemplate.compile(
        {"message": None, "buttons": None, "rich_message": {}, "default_keys": None}
    )
    assert (template.message, template.buttons, template.rich_message) == (None, None, None)
    assert template.format_message({}) is None
    assert template.format_keyboard({}) is None
    assert template.format() == {}


@needs_pyrogram
def test_format_keyboard_is_none_when_every_button_is_hidden() -> None:
    template = CompiledTemplate.compile(
        {"buttons": [_button(all_of=["x"]), {"each": "xs", "item": _button(all_of=["x"])}]}
    )
    assert template.format_keyboard({"name": "n", "xs": [{"name": "a"}]}) is None


@needs_pyrogram
def test_format_parts_apply_default_keys_and_key_time(fixed_time: str) -> None:
    template = CompiledTemplate.compile(
        {
            "message": ["{n} {time}"],
            "rich_message": {"html": ["{n} {time}"]},
            "buttons": [_button("{n} {time}")],
            "default_keys": {"n": "D"},
        },
        key_time="time",
    )
    expected = f"D {fixed_time}"
    assert template.format_message({}) == expected
    assert template.format_rich_message({}).html == expected
    assert template.format_keyboard({"name": "x"}).inline_keyboard[0][0].text == expected
    assert template.format_message({"n": "given"}) == f"given {fixed_time}"


@needs_pyrogram
def test_apply_key_time_layers_the_time_without_touching_kw() -> None:
    template = CompiledTemplate.compile({"message": ["{time}"]}, key_time="time")
    kw: dict[str, Any] = {"name": "a"}
    view = template.apply_key_time(kw)
    assert kw == {"name": "a"}
    assert view["name"] == "a"
    assert isinstance(view["time"], str)
    assert template.apply_key_time(view) is view
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
def test_compiling_the_same_dict_twice_is_not_supported() -> None:
    raw = {"buttons": [_button()]}
    CompiledTemplate.compile(raw)
    # The first compile left `CompiledButtonRow` objects where the definitions were.
    with pytest.raises(TypeError, match="CompiledButtonRow"):
        CompiledTemplate.compile(raw)


@needs_pyrogram
def test_compile_rejects_an_unknown_parse_mode() -> None:
    with pytest.raises(ValueError, match="nope"):
        CompiledTemplate.compile({"message": ["x"], "parse_mode": "nope"})
    with pytest.raises(ValueError, match="nope"):
        CompiledTemplate.compile({"message": ["x"]}, parse_mode="nope")


@needs_pyrogram
@pytest.mark.parametrize(
    ("own", "file", "argument", "expected"),
    [
        (None, None, None, None),
        (None, None, "html", "html"),
        (None, "markdown", "html", "markdown"),
        ("disabled", "markdown", "html", "disabled"),
        ("html", None, "markdown", "html"),
    ],
)
def test_parse_mode_and_key_time_precedence(
    tmp_path: Path, own: str | None, file: str | None, argument: str | None, expected: str | None
) -> None:
    from pyrogram.enums import ParseMode  # noqa: PLC0415 - optional `pyrogram`, present only when `needs_pyrogram` lets the test run

    definition: dict[str, object] = {"message": ["x"]}
    content: dict[str, object] = {"top": definition}
    if own is not None:
        definition |= {"parse_mode": own, "key_time": f"own_{own}"}
    if file is not None:
        content |= {"parse_mode": file, "key_time": f"file_{file}"}

    templates = CompiledTemplate.compile_from_file(
        _write(tmp_path / "t.json", content),
        argument,
        None if argument is None else f"arg_{argument}",
    )
    top = templates["top"]
    assert top.parse_mode is (None if expected is None else ParseMode(expected))
    origin = "own" if own else "file" if file else "arg"
    assert top.key_time == (None if expected is None else f"{origin}_{expected}")


@needs_pyrogram
def test_a_template_key_time_overrides_the_default_and_a_falsy_one_does_not() -> None:
    assert CompiledTemplate.compile({"key_time": "mine"}, key_time="t").key_time == "mine"
    assert CompiledTemplate.compile({"key_time": None}, key_time="t").key_time == "t"
    assert CompiledTemplate.compile({"key_time": ""}, key_time="t").key_time == "t"


@needs_pyrogram
def test_compile_from_file_nests_skips_definitions_and_applies_file_defaults(
    tmp_path: Path,
) -> None:
    from pyrogram.enums import ParseMode  # noqa: PLC0415 - optional `pyrogram`, present only when `needs_pyrogram` lets the test run

    path = _write(
        tmp_path / "templates.json",
        {
            "parse_mode": "markdown",
            "$defs": {"greet": "hello"},
            "top": {"message": [{"$ref": "#/$defs/greet"}]},
            "group": {
                "nested": True,
                "inner": {"message": ["x"], "parse_mode": "html"},
                "$skip": {"message": ["no"]},
                "scalar": 5,
                "deeper": {"nested": True, "leaf": {"message": ["leaf"]}},
            },
            "flat": {"nested": False, "message": ["flat"]},
            "not_a_template": 5,
        },
    )

    templates = CompiledTemplate.compile_from_file(path)
    assert set(templates) == {"top", "group", "flat"}
    assert templates["top"].parse_mode is ParseMode.MARKDOWN
    assert templates["top"].format()["text"] == "hello"
    assert set(templates["group"]) == {"inner", "deeper"}
    assert templates["group"]["inner"].parse_mode is ParseMode.HTML
    assert templates["group"]["inner"].format()["text"] == "x"
    assert templates["group"]["deeper"]["leaf"].format()["text"] == "leaf"
    assert templates["flat"].format()["text"] == "flat"

    single = CompiledTemplate.compile_template({"message": ["one"]}, is_single_template=True)
    assert isinstance(single, CompiledTemplate)

    path.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="JSON object"):
        CompiledTemplate.compile_from_file(path)


@needs_pyrogram
def test_compile_from_file_never_walks_a_recursive_definition(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "templates.json",
        {
            "$defs": {"node": {"text": "x", "child": {"$ref": "#/$defs/node"}}},
            "t": {"message": ["hi"]},
        },
    )
    templates = CompiledTemplate.compile_from_file(path)
    assert set(templates) == {"t"}
    assert templates["t"].format() == {"text": "hi"}


@needs_pyrogram
def test_compile_from_file_lets_templates_share_references(tmp_path: Path) -> None:
    each_line = {"each": "xs", "item": "- {n}"}
    each_button = {"each": "xs", "item": _button("{n}")}
    path = _write(
        tmp_path / "templates.json",
        {
            "$defs": {"line": each_line, "rich": {"html": ["<b>r</b>"]}, "button": each_button},
            "a": {
                "message": [{"$ref": "#/$defs/line"}],
                "buttons": [{"$ref": "#/$defs/button"}],
                "rich_message": {"$ref": "#/$defs/rich"},
            },
            "b": {
                "message": [{"$ref": "#/$defs/line"}],
                "buttons": [{"$ref": "#/$defs/button"}],
                "rich_message": {"$ref": "#/$defs/rich"},
            },
            "alias": {"$ref": "#/a"},
            "group": {"nested": True, "inner": {"message": ["g"]}},
            "group_alias": {"$ref": "#/group"},
        },
    )

    templates = CompiledTemplate.compile_from_file(path)
    kw = {"xs": [{"n": 1}], "name": "x"}
    for name in ("a", "b", "alias"):
        assert templates[name].format_message(kw) == "- 1"
        assert templates[name].format_rich_message(kw).html == "<b>r</b>"
        assert templates[name].format_keyboard(kw).inline_keyboard[0][0].text == "1"
    assert templates["a"] is not templates["alias"]
    assert templates["group_alias"]["inner"].format()["text"] == "g"


@needs_pyrogram
def test_compile_from_file_raises_on_a_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "none.json"
    with pytest.raises(FileNotFoundError, match="none.json"):
        CompiledTemplate.compile_from_file(missing)

    def no_jsonref(path: object, default: object) -> object:
        """Fail as `load_ref_json` does when `jsonref` is absent."""
        msg = "pytrove[json]"
        raise ImportError(msg)

    monkeypatch.setattr(template_module, "load_ref_json", no_jsonref)
    with pytest.raises(FileNotFoundError, match="none.json"):
        CompiledTemplate.compile_from_file(missing)


@needs_pyrogram
def test_compile_from_file_reads_plain_json_without_the_json_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_jsonref(path: object, default: object) -> object:
        """Fail as `load_ref_json` does when `jsonref` is absent."""
        msg = "pytrove[json]"
        raise ImportError(msg)

    monkeypatch.setattr(template_module, "load_ref_json", no_jsonref)
    path = _write(tmp_path / "templates.json", {"top": {"message": ["plain"]}})

    assert CompiledTemplate.compile_from_file(path)["top"].format()["text"] == "plain"


@needs_pyrogram
@pytest.mark.parametrize("flag", [True, False])
def test_compile_template_accepts_a_plain_bool_flag(flag: bool) -> None:
    compiled = CompiledTemplate.compile_template(
        {"t": {"message": ["x"]}} if not flag else {"message": ["x"]}, is_single_template=flag
    )
    single = compiled if flag else compiled["t"]
    assert isinstance(single, CompiledTemplate)
    assert single.format()["text"] == "x"


def test_has_pyrogram_needs_the_tg_requirement_not_just_the_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pytrove._internal, "_has_requirement", lambda *_: False)
    name = "pytrove.models.template_models._template_probe"
    spec = importlib.util.spec_from_file_location(name, template_module.__file__)
    assert spec is not None and spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, probe)
    spec.loader.exec_module(probe)

    assert probe.HAS_PYROGRAM is False
    with pytest.raises(ImportError, match="pytrove\\[tg\\]"):
        probe.CompiledTemplate()


@pytest.mark.skipif(HAS_PYROGRAM, reason="checks the error raised without the tg extra")
def test_template_needs_the_tg_extra() -> None:
    with pytest.raises(ImportError, match="pytrove\\[tg\\]"):
        CompiledTemplate()
