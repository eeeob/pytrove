from __future__ import annotations as _annotations

import importlib.util
import logging
import math
import sys
from collections import Counter, OrderedDict, defaultdict, deque, namedtuple
from collections.abc import Iterator, Mapping, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

import pytest

from pytrove.enums import TimeUnit
from pytrove.errors import ValidationError
from pytrove.models._internal import (
    _INV_PHI,
    _WOBBLE_SPREAD,
    _LoggerModel,
    _enum_member,
    _is_enum,
    _iter_enums,
    _resolved_hints,
    _to_enums,
    _union_to_enums,
)

if TYPE_CHECKING:
    from decimal import Decimal
    from pathlib import Path


class _Base:
    """Annotated with an importable type."""

    unit: TimeUnit


class _Child(_Base):
    """Adds an annotation naming a type imported only for type checking."""

    amount: Decimal
    count: int


def test_resolved_hints_skips_unresolvable_annotations() -> None:
    assert _resolved_hints(_Child) == {"unit": TimeUnit, "count": int}


class _Override(_Base):
    """Replaces its base's annotation."""

    unit: int


class _Broken:
    """Annotations that fail with errors other than `NameError`."""

    missing_attribute: math.NotThere
    not_subscriptable: int[str]
    count: int


def test_resolved_hints_lets_a_subclass_annotation_replace_its_bases() -> None:
    assert _resolved_hints(_Override) == {"unit": int}


def test_resolved_hints_skips_attribute_and_type_errors() -> None:
    assert _resolved_hints(_Broken) == {"count": int}


@pytest.mark.skipif(sys.version_info < (3, 14), reason="deferred annotations arrived in 3.14")
def test_resolved_hints_reads_a_module_without_the_future_import(tmp_path: Path) -> None:
    # Without `from __future__ import annotations` a 3.14 module defers its
    # annotations, and reading their values would raise `NameError`.
    source = tmp_path / "deferred_model.py"
    source.write_text(
        "\n".join(
            [
                "from dataclasses import dataclass",
                "from typing import TYPE_CHECKING",
                "from pytrove.enums import TimeUnit",
                "from pytrove.models import BaseDataClass",
                "if TYPE_CHECKING:",
                "    from decimal import Decimal",
                "@dataclass",
                "class Model(BaseDataClass):",
                "    amount: Decimal | None = None",
                "    unit: TimeUnit | None = None",
            ]
        ),
        encoding="utf-8",
    )
    spec = importlib.util.spec_from_file_location("deferred_model", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    hints = _resolved_hints(module.Model)
    assert hints["unit"] == TimeUnit | None and "amount" not in hints
    assert module.Model(unit=TimeUnit.MINUTE).to_dict(enums_to_values=True)["unit"] == 60


def test_inv_phi_is_the_golden_ratio_step() -> None:
    assert math.isclose(_INV_PHI, (5**0.5 - 1) / 2)


def test_wobble_spread_keeps_the_step_inside_its_no_cluster_bounds() -> None:
    assert _INV_PHI * (1 + _WOBBLE_SPREAD) < 0.8
    assert _INV_PHI * (1 - _WOBBLE_SPREAD) > 0.44


def test_logger_model_resolves_the_logger() -> None:
    model = _LoggerModel(logger="pytrove.test.internal")
    assert model.resolve_logger() is logging.getLogger("pytrove.test.internal")
    assert model.logger is logging.getLogger("pytrove.test.internal")

    with pytest.raises(ValidationError):
        _LoggerModel(logger=object()).resolve_logger()


def test_logger_model_resolves_none_to_the_root_logger() -> None:
    model = _LoggerModel()
    assert model.resolve_logger() is logging.getLogger()
    assert model.logger is logging.getLogger()


def test_logger_model_passes_a_logger_through() -> None:
    logger = logging.getLogger("pytrove.test.internal.instance")
    model = _LoggerModel(logger=logger)
    assert model.resolve_logger() is logger and model.logger is logger


class _Colour(Enum):
    RED = "red"


class _Size(Enum):
    BIG = "big"


_Pair = namedtuple("_Pair", "label colour")  # noqa: PYI024  # A runtime namedtuple is what the rebuild has to handle.


class _Meta(TypedDict, total=False):
    """A mapping where only `style` is an enum."""

    style: _Colour
    label: str


def test_is_enum_tells_an_enum_class_from_anything_else() -> None:
    assert _is_enum(_Colour)
    assert not _is_enum(_Colour.RED)
    assert not _is_enum(str)
    assert not _is_enum(list[_Colour])


def test_iter_enums_walks_generics_unions_and_typeddicts() -> None:
    assert set(_iter_enums(dict[str, list[_Colour] | None])) == {_Colour}
    assert set(_iter_enums(_Meta)) == {_Colour}
    assert set(_iter_enums(tuple[_Colour, _Size])) == {_Colour, _Size}
    assert list(_iter_enums(dict[str, int])) == []


def test_enum_member_converts_a_known_leaf_value_only() -> None:
    assert _enum_member(_Colour, "red") is _Colour.RED
    assert _enum_member(_Colour, _Colour.RED) is _Colour.RED
    assert _enum_member(_Colour, "blue") == "blue"
    assert _enum_member(_Colour, ["red"]) == ["red"]  # A container is never a member's value.
    assert _enum_member(_Colour, {"red": 1}) == {"red": 1}


def test_union_to_enums_tries_enum_arms_first_then_deeper_ones_in_order() -> None:
    assert _union_to_enums("red", (str, _Colour)) is _Colour.RED
    assert _union_to_enums(["red"], (list[_Colour], type(None))) == [_Colour.RED]
    assert _union_to_enums("big", (_Colour, _Size)) is _Size.BIG
    assert _union_to_enums("other", (str, _Colour)) == "other"


@pytest.mark.parametrize(
    ("hint", "value", "expected"),
    [
        (_Colour, "red", _Colour.RED),
        (str, "red", "red"),
        (Annotated[_Colour, "doc"], "red", _Colour.RED),
        (_Colour | None, "red", _Colour.RED),
        (dict[str, _Colour], {"red": "red"}, {"red": _Colour.RED}),
        (dict[_Colour, str], {"red": "red"}, {_Colour.RED: "red"}),
        (list[_Colour], ["red", "x"], [_Colour.RED, "x"]),
        (set[_Colour], {"red"}, {_Colour.RED}),
        (tuple[_Colour, ...], ("red", "red"), (_Colour.RED, _Colour.RED)),
        (tuple[str, _Colour], ("red", "red"), ("red", _Colour.RED)),
        (tuple[str, _Colour], ("red",), ("red",)),  # The length does not fit the hint.
        (
            _Meta,
            {"style": "red", "label": "red", "x": "red"},
            {"style": _Colour.RED, "label": "red", "x": "red"},
        ),
        (list[str], ["red"], ["red"]),
        (Any, "red", "red"),
    ],
    ids=repr,
)
def test_to_enums_converts_exactly_where_the_hint_puts_an_enum(
    hint: Any, value: Any, expected: Any
) -> None:
    assert _to_enums(value, hint) == expected


def test_to_enums_leaves_a_value_with_no_enum_below_untouched() -> None:
    data = {"a": ["red"]}
    assert _to_enums(data, dict[str, list[str]]) is data  # Not rebuilt.


def test_to_enums_rebuilds_a_container_as_its_own_type() -> None:
    ordered = _to_enums(OrderedDict(a="red"), dict[str, _Colour])
    assert type(ordered) is OrderedDict and ordered == {"a": _Colour.RED}

    factory = _to_enums(defaultdict(list, a="red"), Mapping[str, _Colour])
    assert type(factory) is defaultdict and factory.default_factory is list
    assert factory == {"a": _Colour.RED}

    pair = _to_enums(_Pair("x", "red"), tuple[str, _Colour])
    assert type(pair) is _Pair and pair == ("x", _Colour.RED)

    assert _to_enums(deque(["red"]), Sequence[_Colour]) == deque([_Colour.RED])


def test_to_enums_converts_an_iterator_lazily() -> None:
    converted = _to_enums(iter(["red"]), Iterator[_Colour])
    assert not isinstance(converted, list)
    assert list(converted) == [_Colour.RED]


def test_to_enums_leaves_strings_and_counters_alone() -> None:
    # A `str` is iterable, but never a container of members.
    assert _to_enums("red", list[_Colour]) == "red"
    counter = Counter(red=2)
    assert _to_enums(counter, Counter[_Colour]) is counter  # Its keys alone would lose the counts.
