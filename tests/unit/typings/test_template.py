from __future__ import annotations as _annotations

import pytest

from pytrove.typings import TemplateDict, TemplatePyroMessage, template


def test_every_template_type_is_prefixed() -> None:
    assert all(name.startswith("Template") for name in template.__all__)


@pytest.mark.parametrize("typed_dict", [TemplateDict, TemplatePyroMessage])
def test_template_dict_keys_are_all_declared_optional(typed_dict: type) -> None:
    # The annotations are deferred strings (rule 4.2), so `__required_keys__` cannot be trusted on every version.
    annotations = [getattr(v, "__forward_arg__", v) for v in typed_dict.__annotations__.values()]
    assert annotations
    assert all(v.startswith("NotRequired[") for v in annotations)
