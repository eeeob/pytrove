"""Data kept in a file and loaded on first use."""

from __future__ import annotations as _annotations

import sys
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Generic, cast, overload

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from ..async_tools import to_thread
from ..files_tools import read_json, write_json
from ..typings import JsonValue, LockProtocol, PathLike, _KT, _T, _VT
from .base import BaseDataClass


@dataclass(slots=True)
class JsonContainer(BaseDataClass, Generic[_KT, _VT]):
    """A JSON object kept in a file, read on first access and written on `save()`."""

    path: PathLike
    """The JSON file."""

    lock: LockProtocol | None = None
    """A lock held while the file is read or written; `None` for no locking."""

    data: dict[_KT, _VT] | None = field(default=None, init=False)
    """The loaded object, or `None` while nothing is loaded; `unload()` puts it back to `None`."""

    def is_loaded(self) -> bool:
        """Return whether the file has been read."""
        return self.data is not None

    def unload(self) -> None:
        """Drop the loaded data, so the next access reads the file again."""
        self.data = None

    def load(self, **kw: Any) -> None:
        """Read the file, unless it is already loaded; a missing file loads as `{}`.

        Args:
            **kw: Passed to `read_json()`.

        Raises:
            TypeError: If the file does not hold a JSON object.
        """
        if self.data is not None:
            return

        data = read_json(self.path, lock=self.lock, **kw)

        if not isinstance(data, dict):
            msg = f"JsonContainer needs a JSON object in {self.path}, not {type(data).__name__}"
            raise TypeError(msg)

        # JSON is untyped: the caller states the shape through `_KT`/`_VT`.
        self.data = cast("dict[_KT, _VT]", data)

    def copy(self) -> Self:
        """Return a deep copy that shares this container's `lock`.

        The lock guards the file, which the copy shares, so it is not copied:
        a `threading.Lock` cannot be, and a fresh `asyncio.Lock` would let the
        two containers write the file at once. Everything else is deep-copied.

        Returns:
            The copy.
        """
        return deepcopy(self, {id(self.lock): self.lock})

    def _loaded_data(self) -> dict[_KT, _VT]:
        """Return the loaded object.

        Returns:
            The loaded object.

        Raises:
            RuntimeError: If nothing is loaded.
        """
        if self.data is None:
            msg = "JsonContainer has no data loaded"
            raise RuntimeError(msg)

        return self.data

    def save(self, **kw: Any) -> None:
        """Write the loaded data to the file.

        Args:
            **kw: Passed to `write_json()`.

        Raises:
            RuntimeError: If nothing is loaded.
        """
        # The data came from JSON, so it is JSON again whatever `_KT`/`_VT` say.
        write_json(self.path, cast("JsonValue", self._loaded_data()), self.lock, **kw)

    @overload
    def get(self, key: _KT) -> _VT | None: ...
    @overload
    def get(self, key: _KT, default: _T) -> _VT | _T: ...
    def get(self, key: _KT, default: _T | None = None) -> _VT | _T | None:
        """Return the value under `key`, loading the file first if needed.

        Args:
            key: The key.
            default: Returned if `key` is absent.

        Returns:
            The value, or `default`.
        """
        self.load()
        return self._loaded_data().get(key, default)

    def set(self, key: _KT, value: _VT, save_now: bool = False) -> None:
        """Store `value` under `key`, loading the file first if needed.

        Args:
            key: The key.
            value: The value.
            save_now: Write the file afterwards.
        """
        self.load()

        self._loaded_data()[key] = value

        if save_now:
            self.save()

    def delete(self, key: _KT, save_now: bool = False) -> None:
        """Remove `key` if present, loading the file first if needed.

        Args:
            key: The key.
            save_now: Write the file afterwards, if the key was removed.
        """
        self.load()
        data = self._loaded_data()

        if key in data:
            del data[key]

            if save_now:
                self.save()

    def update(self, update: dict[_KT, _VT], save_now: bool = False) -> None:
        """Merge `update` into the data, loading the file first if needed.

        Args:
            update: The entries to set.
            save_now: Write the file afterwards.
        """
        self.load()

        self._loaded_data().update(update)

        if save_now:
            self.save()

    async def async_load(self, **kw: Any) -> None:
        """Run `load()` in a thread.

        Args:
            **kw: Passed to `read_json()`.
        """
        await to_thread(self.load, **kw)

    async def async_save(self, **kw: Any) -> None:
        """Write the loaded data to the file in a thread.

        The data is deep-copied on the calling thread first, so a change made
        while the write runs, such as an `async_set()`, can neither tear it
        nor reach the file.

        Args:
            **kw: Passed to `write_json()`.

        Raises:
            RuntimeError: If nothing is loaded.
        """
        # The data came from JSON, so it is JSON again whatever `_KT`/`_VT` say.
        data = cast("JsonValue", deepcopy(self._loaded_data()))
        await to_thread(write_json, self.path, data, self.lock, **kw)

    @overload
    async def async_get(self, key: _KT) -> _VT | None: ...
    @overload
    async def async_get(self, key: _KT, default: _T) -> _VT | _T: ...
    async def async_get(self, key: _KT, default: _T | None = None) -> _VT | _T | None:
        """Async `get()`: the file is read in a thread.

        Args:
            key: The key.
            default: Returned if `key` is absent.

        Returns:
            The value, or `default`.
        """
        if not self.is_loaded():
            await self.async_load()
        return self._loaded_data().get(key, default)

    async def async_set(self, key: _KT, value: _VT, save_now: bool = False) -> None:
        """Async `set()`: the file is read and written in a thread.

        Args:
            key: The key.
            value: The value.
            save_now: Write the file afterwards.
        """
        if not self.is_loaded():
            await self.async_load()

        self._loaded_data()[key] = value

        if save_now:
            await self.async_save()

    async def async_delete(self, key: _KT, save_now: bool = False) -> None:
        """Async `delete()`: the file is read and written in a thread.

        Args:
            key: The key.
            save_now: Write the file afterwards, if the key was removed.
        """
        if not self.is_loaded():
            await self.async_load()
        data = self._loaded_data()

        if key in data:
            del data[key]

            if save_now:
                await self.async_save()

    async def async_update(self, update: dict[_KT, _VT], save_now: bool = False) -> None:
        """Async `update()`: the file is read and written in a thread.

        Args:
            update: The entries to set.
            save_now: Write the file afterwards.
        """
        if not self.is_loaded():
            await self.async_load()

        self._loaded_data().update(update)

        if save_now:
            await self.async_save()


__all__ = ("JsonContainer",)
