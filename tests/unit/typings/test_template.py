from __future__ import annotations as _annotations

import sys
from typing import Any, get_args

import pytest

from pytrove.typings import (
    TemplateButtonDict,
    TemplateButtonType,
    TemplateConditionalDict,
    TemplateDefaultsDict,
    TemplateDict,
    TemplateEachButtonDict,
    TemplateEachLineDict,
    TemplateLineDict,
    TemplateParseMode,
    TemplatePyroMessage,
    TemplateRichMessageDict,
    template,
)

_DEFAULTS = {"default_keys"}
_CONDITIONAL = {*_DEFAULTS, "any_of", "all_of"}


def test_every_template_type_is_prefixed() -> None:
    assert all(name.startswith("Template") for name in template.__all__)


@pytest.mark.parametrize(
    ("typed_dict", "required", "optional"),
    [
        (TemplateDefaultsDict, set(), _DEFAULTS),
        (TemplateConditionalDict, set(), _CONDITIONAL),
        (TemplateLineDict, {"text"}, _CONDITIONAL),
        (TemplateEachLineDict, {"each", "item"}, set()),
        (TemplateButtonDict, {"text", "type", "value"}, {*_CONDITIONAL, "meta"}),
        (TemplateEachButtonDict, {"each", "item"}, {"row_width"}),
        (
            TemplateRichMessageDict,
            set(),
            {*_DEFAULTS, "html", "markdown", "is_rtl", "skip_entity_detection"},
        ),
        (
            TemplateDict,
            set(),
            {*_DEFAULTS, "message", "buttons", "parse_mode", "rich_message", "key_time"},
        ),
        (TemplatePyroMessage, set(), {"text", "parse_mode", "rich_message", "reply_markup"}),
    ],
)
def test_template_typed_dicts_report_their_required_and_optional_keys(
    typed_dict: Any, required: set[str], optional: set[str]
) -> None:
    assert typed_dict.__required_keys__ == required
    assert typed_dict.__optional_keys__ == optional
    assert set(typed_dict.__annotations__) == required | optional


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="`TypedDict` keeps `__orig_bases__` from 3.12"
)
@pytest.mark.parametrize(
    ("typed_dict", "base"),
    [
        (TemplateConditionalDict, TemplateDefaultsDict),
        (TemplateLineDict, TemplateConditionalDict),
        (TemplateRichMessageDict, TemplateDefaultsDict),
        (TemplateDict, TemplateDefaultsDict),
    ],
)
def test_template_typed_dicts_derive_from_their_base(typed_dict: Any, base: Any) -> None:
    assert base in typed_dict.__orig_bases__


def test_template_button_dicts_extend_their_required_part() -> None:
    assert TemplateButtonDict.__required_keys__ >= TemplateLineDict.__required_keys__
    assert TemplateButtonDict.__optional_keys__ >= TemplateConditionalDict.__optional_keys__


def test_template_literal_aliases() -> None:
    assert get_args(TemplateButtonType) == ("url", "callback_data")
    assert get_args(TemplateParseMode) == ("html", "markdown")
