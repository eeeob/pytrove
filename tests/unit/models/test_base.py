"""Regression tests for the BaseDataClass field-discovery ordering bug.

__init_subclass__ fires when the `class Foo(BaseDataClass):` statement
executes, i.e. BEFORE any decorator applied to Foo itself (like @dataclass)
runs. Discovering dataclass fields there silently sees an empty field list
for any subclass that ISN'T decorated with @dataclass(slots=True) (which
happens to rebuild the class and re-trigger the hook afterwards). Plain
`@dataclass` subclasses used to lose all field data silently:
to_dict() returned {} and from_dict() ignored every key.

These tests must pass identically for both slotted and non-slotted
subclasses, and regardless of whether an instance was created before
from_dict()/to_dict() is first called.
"""

from __future__ import annotations as _annotations

import json
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

import pytest

from pytrove.models import BaseDataClass

if TYPE_CHECKING:
    from not_importable_here import NameThatIsNotImportableHere  # noqa: TC004 - unimportable on purpose, to test `_resolved_hints` skipping it


class Status(Enum):
    OK = "ok"


@dataclass
class PlainModel(BaseDataClass):
    a: int = 1
    _b: int = 2


@dataclass(slots=True)
class SlottedModel(BaseDataClass):
    a: int = 1
    _b: int = 2


def test_plain_dataclass_field_discovery_not_empty() -> None:
    inst = PlainModel(a=10, _b=20)
    assert inst.to_dict() == {"a": 10, "b": 20}
    assert inst.to_raw_dict() == {"a": 10, "_b": 20}


def test_slotted_dataclass_field_discovery_not_empty() -> None:
    inst = SlottedModel(a=10, _b=20)
    assert inst.to_dict() == {"a": 10, "b": 20}
    assert inst.to_raw_dict() == {"a": 10, "_b": 20}


def test_plain_and_slotted_from_dict_roundtrip_identically() -> None:
    plain = PlainModel.from_dict({"a": 99, "b": 88})
    slotted = SlottedModel.from_dict({"a": 99, "b": 88})
    assert plain.to_dict() == {"a": 99, "b": 88}
    assert slotted.to_dict() == {"a": 99, "b": 88}


def test_from_dict_works_without_prior_instantiation() -> None:
    # Cold path: from_dict() must trigger field discovery itself, without
    # requiring an instance to have been created (via __post_init__) first.
    @dataclass
    class ColdModel(BaseDataClass):
        a: int = 1
        _b: int = 2

    result = ColdModel.from_dict({"a": 5, "b": 6})
    assert result.to_dict() == {"a": 5, "b": 6}


def test_private_field_property_proxy_available_after_construction() -> None:
    inst = PlainModel(a=1, _b=42)
    assert inst.b == 42
    inst.b = 100
    assert inst._b == 100


def test_copy_roundtrip() -> None:
    inst = PlainModel(a=1, _b=2)
    duplicate = inst.copy()
    assert duplicate is not inst
    assert duplicate.to_dict() == inst.to_dict()


def test_multi_level_inheritance_each_class_gets_its_own_fields() -> None:
    # Regression: a naive "already computed?" check based on hasattr() (which
    # walks the MRO) would make a subclass-of-a-subclass see its parent's
    # already-cached field list and skip discovering its own extra fields.
    @dataclass
    class Parent(BaseDataClass):
        x: int = 1

    @dataclass
    class Child(Parent):
        x: int = 1
        y: int = 2

    parent = Parent(x=10)
    assert parent.to_dict() == {"x": 10}

    child = Child(x=10, y=20)
    assert child.to_dict() == {"x": 10, "y": 20}


def test_exclude_none_and_enums_to_values() -> None:
    @dataclass
    class WithEnum(BaseDataClass):
        status: Status = Status.OK
        note: str | None = None

    inst = WithEnum()
    assert inst.to_dict(exclude_none=True, enums_to_values=True) == {"status": "ok"}
    assert inst.to_raw_dict(exclude_none=True, enums_to_values=True) == {"status": "ok"}
    assert WithEnum.__enums_types__ == frozenset({Status})
    assert json.loads(str(inst)) == {"status": "ok"}


def test_values_to_enums_converts_only_where_the_annotation_puts_the_enum() -> None:
    @dataclass
    class Model(BaseDataClass):
        status: Status = Status.OK
        label: str = ""
        by_name: dict[str, Status] | None = None
        notes: list[str] | None = None

    data = {"status": "ok", "label": "ok", "by_name": {"ok": "ok"}, "notes": ["ok"]}
    model = Model.from_dict(data, values_to_enums=True)

    assert model.status is Status.OK
    assert model.label == "ok"  # A `str` field equal to a member's value stays a `str`.
    assert model.by_name == {"ok": Status.OK}  # Values only; the `str` keys stay.
    assert model.notes == ["ok"]
    assert Model.__field_hints__["label"] is str


def test_from_dicts_drop_unknown_keys_and_restore_enums() -> None:
    @dataclass
    class Model(BaseDataClass):
        status: Status | None = None
        _secret: str = ""

    model = Model.from_dict(
        {"status": "ok", "secret": "s", "_secret": "raw", "other": 1}, values_to_enums=True
    )
    assert model.status is Status.OK and model.secret == "s"

    raw = Model.from_raw_dict({"status": None, "_secret": "r", "secret": "x"}, exclude_none=True)
    assert raw.status is None and raw.secret == "r"
    assert Model.from_raw_dict({"status": "ok"}, values_to_enums=True).status is Status.OK
    assert Model.from_dict({"status": None}, exclude_none=True).status is None


def test_from_dict_renames_the_keys_and_builds_through_from_raw_dict() -> None:
    @dataclass
    class Model(BaseDataClass):
        status: Status | None = Status.OK
        _secret: str | None = "default"

    public = {"status": "ok", "secret": None, "_secret": "ignored"}
    for options in ((False, False), (True, False), (False, True), (True, True)):
        assert Model.from_dict(public, *options) == Model.from_raw_dict(
            {"status": "ok", "_secret": None}, *options
        )
    assert Model.from_dict(public, exclude_none=True).secret == "default"


def test_field_meta_requires_a_dataclass() -> None:
    # Every subclass inherits `__dataclass_fields__`, so call the method on a plain class directly.
    class Plain:
        pass

    with pytest.raises(TypeError, match="must be dataclass"):
        BaseDataClass._ensure_field_meta.__func__(Plain)


def test_base_dataclass_survives_an_unresolvable_annotation() -> None:
    @dataclass
    class Model(BaseDataClass):
        value: NameThatIsNotImportableHere | None = None

    Model._ensure_field_meta()

    assert Model.__enums_types__ == frozenset()


def test_only_fields_contribute_enum_types() -> None:
    @dataclass
    class Model(BaseDataClass):
        DEFAULT: ClassVar[Status] = Status.OK
        note: str = ""

    Model._ensure_field_meta()

    assert Model.__enums_types__ == frozenset()


def test_private_field_keeps_an_attribute_the_class_already_defines() -> None:
    @dataclass
    class Custom(BaseDataClass):
        _x: int = 1

        @property
        def x(self) -> str:
            """Return a value the generated property would not."""
            return "custom"

    Custom._ensure_field_meta()

    assert Custom().x == "custom"
    assert Custom(_x=5)._x == 5


@dataclass
class Inner(BaseDataClass):
    n: int = 1
    tags: list[str] = field(default_factory=list)


@dataclass
class Outer(BaseDataClass):
    inner: Inner = field(default_factory=Inner)
    items: list[int] = field(default_factory=list)
    computed: int = field(default=0, init=False)


def test_copy_is_deep_and_keeps_nested_dataclasses_and_init_false_fields() -> None:
    outer = Outer(Inner(2, ["a"]), [1])
    outer.computed = 7

    duplicate = outer.copy()

    assert type(duplicate.inner) is Inner
    assert duplicate == outer and duplicate.computed == 7
    assert duplicate.inner is not outer.inner and duplicate.inner.tags is not outer.inner.tags
    assert duplicate.items is not outer.items


def test_copy_raises_for_a_field_that_cannot_be_deep_copied() -> None:
    @dataclass
    class Locked(BaseDataClass):
        lock: object = None

    with pytest.raises(TypeError):
        Locked(threading.Lock()).copy()


def test_from_dicts_set_an_init_false_field_after_construction() -> None:
    raw = Outer.from_raw_dict({"items": [1], "computed": 5})
    assert raw.items == [1] and raw.computed == 5

    public = Outer.from_dict({"computed": 3})
    assert public.computed == 3

    assert Outer.from_raw_dict(Outer().to_raw_dict() | {"computed": 9}).computed == 9


def test_to_dict_is_shallow_and_to_raw_dict_is_deep() -> None:
    outer = Outer(Inner(2, ["a"]), [1])

    shallow = outer.to_dict()
    assert shallow["inner"] is outer.inner and shallow["items"] is outer.items

    deep = outer.to_raw_dict()
    assert deep["inner"] == {"n": 2, "tags": ["a"]}
    assert deep["items"] == [1] and deep["items"] is not outer.items


def test_to_dict_reads_a_private_field_not_a_property_of_its_public_name() -> None:
    @dataclass
    class Custom(BaseDataClass):
        _x: int = 1

        @property
        def x(self) -> str:
            """Return a value the field does not hold."""
            return "custom"

    assert Custom(_x=5).to_dict() == {"x": 5}
    assert Custom.from_dict({"x": 6})._x == 6


def test_private_field_drops_exactly_one_underscore() -> None:
    @dataclass
    class Dunder(BaseDataClass):
        __x__: int = 1

    model = Dunder(__x__=5)
    assert model.to_dict() == {"_x__": 5}
    assert model.copy().__x__ == 5
    assert Dunder.from_dict({"_x__": 3}).__x__ == 3
    assert Dunder.__private_field_names__ == ["_x__"]
    assert Dunder.__raw_private_fields__ == frozenset({"__x__"})


def test_private_field_whose_public_name_is_another_field_is_refused() -> None:
    @dataclass
    class Both(BaseDataClass):
        a: int = 1
        _a: int = 2

    with pytest.raises(TypeError, match="clash"):
        Both()


def test_field_meta_publishes_its_cache_marker_last() -> None:
    @dataclass
    class Model(BaseDataClass):
        a: int = 1
        _b: int = 2

    Model._ensure_field_meta()

    cache = (
        "__enums_types__",
        "__field_hints__",
        "__raw_private_fields__",
        "__private_field_names__",
        "__public_field_names__",
    )
    # A class `__dict__` keeps assignment order.
    assert [name for name in vars(Model) if name in cache][-1] == "__public_field_names__"


def test_generated_property_deletes_the_private_field() -> None:
    inst = SlottedModel(a=1, _b=42)
    del inst.b
    assert not hasattr(inst, "_b")
