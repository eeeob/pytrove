"""The dataclass base every serialisable model builds on."""

from __future__ import annotations as _annotations

import json
import sys
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ..data_tools import clean_none_values, enum_to_value
from ._internal import _iter_enums, _resolved_hints, _to_enums

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass
class BaseDataClass:
    """A dataclass base that converts to and from a dict.

    Two conventions apply to every subclass:

    - A field named with a leading underscore (`_foo`) is private: its public
      name drops that one underscore (`foo`), a `foo` property proxying to it
      is generated unless the class already defines `foo`, and
      `to_dict()`/`from_dict()` (but not the `*_raw_dict` variants) use the
      public name while reading and writing the field itself. A public name
      that is also another field's name is refused.
    - `values_to_enums` turns a raw value into an enum member only where the
      field's annotation puts that enum: `status: Status` converts the field,
      `dict[str, Status]` its values, a `TypedDict` the keys typed as enums,
      and a `str` field is never touched. `enums_to_values` turns every member
      back into its value.

    Both are computed once per subclass by `_ensure_field_meta()`.

    Example:
        >>> from dataclasses import dataclass
        >>> @dataclass
        ... class Point(BaseDataClass):
        ...     x: int
        ...     _tag: str = "p"
        >>> p = Point(1)
        >>> p.tag
        'p'
        >>> p.to_dict()
        {'x': 1, 'tag': 'p'}
        >>> p.to_raw_dict()
        {'x': 1, '_tag': 'p'}
        >>> Point.from_dict({"x": 2, "tag": "q", "extra": 0})
        Point(x=2, _tag='q')
    """

    __public_field_names__: ClassVar[list[str]]
    """Field names without a leading underscore, in definition order."""

    __private_field_names__: ClassVar[list[str]]
    """The public names of underscore fields (`_foo` -> `foo`, one underscore dropped), in definition order."""

    __raw_private_fields__: ClassVar[frozenset[str]]
    """The underscore fields under their raw names (`_foo`), as `from_raw_dict()` accepts them."""

    __enums_types__: ClassVar[frozenset[type[Enum]]]
    """Every enum class named anywhere in a field annotation."""

    __field_hints__: ClassVar[dict[str, Any]]
    """Each field's resolved annotation by raw name, which `values_to_enums` follows; an unresolvable one is absent."""

    @classmethod
    def _ensure_field_meta(cls) -> None:
        """Compute and cache which fields are public or private, and which enums the annotations name.

        The cache is checked with `"__public_field_names__" in vars(cls)`, not
        `hasattr`, which would also see a base class's cache: each subclass
        gets its own. That marker is assigned last, so a thread that sees it
        also sees every other cached attribute.

        Raises:
            TypeError: If `cls` is not a dataclass, or a private field's public
                name is also another field's name.
        """
        if "__public_field_names__" in vars(cls):
            return

        if not is_dataclass(cls):
            msg = f"{cls.__name__} must be dataclass"
            raise TypeError(msg)

        public = []
        private = []

        names = {f.name for f in fields(cls)}
        hints = _resolved_hints(cls)
        cls.__field_hints__ = {name: hints[name] for name in names if name in hints}
        cls.__enums_types__ = frozenset(
            enum for hint in cls.__field_hints__.values() for enum in _iter_enums(hint)
        )

        for f in fields(cls):
            name = f.name

            if name.startswith("_"):
                # Drop exactly one underscore, so `"_" + pname` gives `name` back.
                pname = name[1:]

                if pname in names:
                    msg = (
                        f"{cls.__name__} has both {name!r} and {pname!r}; their public names clash"
                    )
                    raise TypeError(msg)

                private.append(pname)

                if not hasattr(cls, pname):
                    prop = property(
                        fget=lambda self, _n=name: getattr(self, _n),
                        fset=lambda self, value, _n=name: setattr(self, _n, value),
                        fdel=lambda self, _n=name: delattr(self, _n),
                    )

                    setattr(cls, pname, prop)

            else:
                public.append(name)

        cls.__raw_private_fields__ = frozenset(f"_{n}" for n in private)
        cls.__private_field_names__ = private
        cls.__public_field_names__ = public

    def __post_init__(self) -> None:
        """Create the private-field properties as soon as an instance exists.

        A subclass that defines its own `__post_init__` must call
        `super().__post_init__()` to keep this.
        """
        self.__class__._ensure_field_meta()

    def to_raw_dict(
        self, exclude_none: bool = False, enums_to_values: bool = False
    ) -> dict[str, Any]:
        """Return the fields under their raw names, as `dataclasses.asdict()` does.

        The conversion is deep: a nested dataclass becomes a dict and every
        list, dict and tuple is copied.

        Args:
            exclude_none: Drop `None` values.
            enums_to_values: Replace enum members with their values.

        Returns:
            The fields, private ones keeping their leading underscore.
        """
        dct = asdict(self)

        if exclude_none:
            dct = clean_none_values(dct)
        if enums_to_values:
            dct = enum_to_value(dct)

        return dct

    def to_dict(self, exclude_none: bool = False, enums_to_values: bool = False) -> dict[str, Any]:
        """Return the fields under their public names.

        The conversion is shallow, unlike `to_raw_dict()`: each value is the
        field's own object, so a nested dataclass stays an instance and a list
        or dict is the instance's own, not a copy. Each private field is read
        directly, never through a property of the same public name.

        Args:
            exclude_none: Drop `None` values.
            enums_to_values: Replace enum members with their values.

        Returns:
            The fields, private ones without their leading underscore.
        """
        self.__class__._ensure_field_meta()

        dct = {name: getattr(self, name) for name in self.__class__.__public_field_names__} | {
            name: getattr(self, f"_{name}") for name in self.__class__.__private_field_names__
        }

        if exclude_none:
            dct = clean_none_values(dct)
        if enums_to_values:
            dct = enum_to_value(dct)

        return dct

    @classmethod
    def from_raw_dict(
        cls,
        data: Mapping[str, Any],
        exclude_none: bool = False,
        values_to_enums: bool = False,
    ) -> Self:
        """Build an instance from fields under their raw names; unknown keys are ignored.

        A field declared with `init=False` is set on the instance after it is
        built, so it round-trips through `to_raw_dict()` too. A nested
        dataclass field is taken as given: a dict that `to_raw_dict()` made
        from it stays a dict, so `copy()` is the way to duplicate a model
        with nested dataclasses.

        Args:
            data: The fields, private ones with their leading underscore.
            exclude_none: Drop `None` values first, so their fields take their defaults.
            values_to_enums: Turn raw values into enum members where the annotations put an enum.

        Returns:
            The new instance.
        """
        cls._ensure_field_meta()

        private = cls.__raw_private_fields__
        public = cls.__public_field_names__
        kept: Mapping[str, Any] = {k: v for k, v in data.items() if k in private or k in public}

        if exclude_none:
            kept = clean_none_values(kept)

        if values_to_enums and cls.__enums_types__:
            hints = cls.__field_hints__
            kept = {k: _to_enums(v, hints[k]) if k in hints else v for k, v in kept.items()}

        no_init = {f.name for f in fields(cls) if not f.init}
        instance = cls(**{k: v for k, v in kept.items() if k not in no_init})

        for name in no_init & kept.keys():
            setattr(instance, name, kept[name])

        return instance

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        exclude_none: bool = False,
        values_to_enums: bool = False,
    ) -> Self:
        """Build an instance from fields under their public names; unknown keys are ignored.

        A nested dataclass field is taken as given: a dict that `to_dict()`
        made from it stays a dict, so `copy()` is the way to duplicate a model
        with nested dataclasses.

        Args:
            data: The fields, private ones without their leading underscore.
            exclude_none: Drop `None` values first, so their fields take their defaults.
            values_to_enums: Turn raw values into enum members where the annotations put an enum.

        Returns:
            The new instance.
        """
        cls._ensure_field_meta()

        private = cls.__private_field_names__
        public = cls.__public_field_names__
        raw = {
            (f"_{k}" if k in private else k): v
            for k, v in data.items()
            if k in private or k in public
        }

        return cls.from_raw_dict(raw, exclude_none, values_to_enums)

    def copy(self) -> Self:
        """Return a deep copy, made by `copy.deepcopy()`.

        Nested dataclasses keep their types and `init=False` fields keep their
        values; `__post_init__` does not run again.

        Returns:
            The copy.

        Raises:
            TypeError: If a field cannot be deep-copied (a lock, say).
        """
        return deepcopy(self)

    def __str__(self) -> str:
        """Return the public fields as indented JSON, enums as values and `None` dropped."""
        return json.dumps(self.to_dict(True, True), indent=4, ensure_ascii=False, default=str)


__all__ = ("BaseDataClass",)
