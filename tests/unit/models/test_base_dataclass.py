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
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import pytest

from pytrove.models import BaseDataClass

if TYPE_CHECKING:
    from not_importable_here import NameThatIsNotImportableHere


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


def test_without_none_values_and_enums_to_values() -> None:
    @dataclass
    class WithEnum(BaseDataClass):
        status: Status = Status.OK
        note: str | None = None

    inst = WithEnum()
    assert inst.to_dict(without_none_values=True, enums_to_values=True) == {"status": "ok"}
    assert inst.to_raw_dict(without_none_values=True, enums_to_values=True) == {"status": "ok"}
    assert WithEnum.__enums_types__ == frozenset({Status})
    assert json.loads(str(inst)) == {"status": "ok"}


def test_from_dicts_drop_unknown_keys_and_restore_enums() -> None:
    @dataclass
    class Model(BaseDataClass):
        status: Status | None = None
        _secret: str = ""

    model = Model.from_dict({"status": "ok", "secret": "s", "_secret": "raw", "other": 1}, values_to_enums=True)
    assert model.status is Status.OK and model.secret == "s"

    raw = Model.from_raw_dict({"status": None, "_secret": "r", "secret": "x"}, without_none_values=True)
    assert raw.status is None and raw.secret == "r"
    assert Model.from_raw_dict({"status": "ok"}, values_to_enums=True).status is Status.OK
    assert Model.from_dict({"status": None}, without_none_values=True).status is None


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
