"""The dataclass base every serialisable model builds on."""

from __future__ import annotations as _annotations

import json
import sys
from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, get_args, get_origin

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ..data_tools import clean_none_values, enum_to_value, value_to_enum
from ._internal import _resolved_hints

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


@dataclass
class BaseDataClass:
    """A dataclass base that converts to and from a dict.

    Two conventions apply to every subclass:

    - A field named with a leading underscore (`_foo`) is private: a `foo`
      property proxying to it is generated, and `to_dict()`/`from_dict()`
      (but not the `*_raw_dict` variants) use the public name `foo`.
    - Enum types found anywhere in a field's annotation, nested ones included,
      can be converted between members and raw values with
      `enums_to_values`/`values_to_enums`.

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
    """The public names of underscore fields (`_foo` -> `foo`), in definition order."""

    __raw_private_fields__: ClassVar[frozenset[str]]
    """The underscore fields under their raw names (`_foo`), as `from_raw_dict()` accepts them."""

    __enums_types__: ClassVar[frozenset[type[Enum]]]
    """Every enum class named anywhere in a field annotation, for `values_to_enums`."""

    @classmethod
    def _ensure_field_meta(cls) -> None:
        """Compute and cache which fields are public or private, and which enums the annotations name.

        The cache is checked with `"__public_field_names__" in vars(cls)`, not
        `hasattr`, which would also see a base class's cache: each subclass
        gets its own.

        Raises:
            TypeError: If `cls` is not a dataclass.
        """
        if "__public_field_names__" in vars(cls):
            return

        if not is_dataclass(cls):
            msg = f"{cls.__name__} must be dataclass"
            raise TypeError(msg)

        public = []
        private = []

        def _deep_extract(value: Any) -> Iterator[type[Enum]]:
            """Yield every enum class inside a type hint, walking `get_origin()`/`get_args()`."""
            if isinstance(value, type) and issubclass(value, Enum):
                yield value
            elif (origin := get_origin(value)) is not None:
                for arg in (*(get_args(value) or ()), origin):
                    yield from _deep_extract(arg)

        names = {f.name for f in fields(cls)}
        hints = _resolved_hints(cls)
        cls.__enums_types__ = frozenset(
            enum for name in names if name in hints for enum in _deep_extract(hints[name])
        )

        for f in fields(cls):
            name = f.name
            pname = name.lstrip("_")

            if name.startswith("_"):
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
        cls.__public_field_names__ = public
        cls.__private_field_names__ = private

    def __post_init__(self) -> None:
        """Create the private-field properties as soon as an instance exists.

        A subclass that defines its own `__post_init__` must call
        `super().__post_init__()` to keep this.
        """
        self.__class__._ensure_field_meta()

    def to_raw_dict(
        self, without_none_values: bool = False, enums_to_values: bool = False
    ) -> dict[str, Any]:
        """Return the fields under their raw names, as `dataclasses.asdict()` does.

        Args:
            without_none_values: Drop `None` values.
            enums_to_values: Replace enum members with their values.

        Returns:
            The fields, private ones keeping their leading underscore.
        """
        dct = asdict(self)

        if without_none_values:
            dct = clean_none_values(dct)
        if enums_to_values:
            dct = enum_to_value(dct)

        return dct

    def to_dict(
        self, without_none_values: bool = False, enums_to_values: bool = False
    ) -> dict[str, Any]:
        """Return the fields under their public names.

        Args:
            without_none_values: Drop `None` values.
            enums_to_values: Replace enum members with their values.

        Returns:
            The fields, private ones without their leading underscore.
        """
        self.__class__._ensure_field_meta()

        dct = {name: getattr(self, name) for name in self.__class__.__public_field_names__} | {
            name: getattr(self, name) for name in self.__class__.__private_field_names__
        }

        if without_none_values:
            dct = clean_none_values(dct)
        if enums_to_values:
            dct = enum_to_value(dct)

        return dct

    @classmethod
    def from_raw_dict(
        cls,
        data: Mapping[str, Any],
        without_none_values: bool = False,
        values_to_enums: bool = False,
    ) -> Self:
        """Build an instance from fields under their raw names; unknown keys are ignored.

        Args:
            data: The fields, private ones with their leading underscore.
            without_none_values: Drop `None` values first, so their fields take their defaults.
            values_to_enums: Turn raw values back into the enum members the annotations name.

        Returns:
            The new instance.
        """
        cls._ensure_field_meta()

        private = cls.__raw_private_fields__
        public = cls.__public_field_names__
        kept: Mapping[str, Any] = {k: v for k, v in data.items() if k in private or k in public}

        if without_none_values:
            kept = clean_none_values(kept)

        if values_to_enums and cls.__enums_types__:
            kept = value_to_enum(kept, cls.__enums_types__, "v")

        return cls(**kept)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        without_none_values: bool = False,
        values_to_enums: bool = False,
    ) -> Self:
        """Build an instance from fields under their public names; unknown keys are ignored.

        Args:
            data: The fields, private ones without their leading underscore.
            without_none_values: Drop `None` values first, so their fields take their defaults.
            values_to_enums: Turn raw values back into the enum members the annotations name.

        Returns:
            The new instance.
        """
        cls._ensure_field_meta()

        private = cls.__private_field_names__
        public = cls.__public_field_names__
        renamed = {k: v for k, v in data.items() if k in private or k in public}

        for name in private:
            if name in renamed:
                renamed[f"_{name}"] = renamed.pop(name)

        kept: Mapping[str, Any] = renamed

        if without_none_values:
            kept = clean_none_values(kept)

        if values_to_enums and cls.__enums_types__:
            kept = value_to_enum(kept, cls.__enums_types__, "v")

        return cls(**kept)

    def copy(self) -> Self:
        """Return a deep copy, rebuilt through `to_raw_dict()`.

        Returns:
            The copy.

        Raises:
            TypeError: If a field cannot be deep-copied (a lock, say).
        """
        return self.__class__.from_raw_dict(self.to_raw_dict())

    def __str__(self) -> str:
        """Return the public fields as indented JSON, enums as values and `None` dropped."""
        return json.dumps(self.to_dict(True, True), indent=4, ensure_ascii=False, default=str)


__all__ = ("BaseDataClass",)
