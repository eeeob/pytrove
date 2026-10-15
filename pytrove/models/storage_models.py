"""Data kept in a file and loaded on first use."""

from __future__ import annotations as _annotations

from dataclasses import dataclass, field
from typing import Any, Generic

from ..async_tools import to_thread
from ..files_tools import read_json, write_json
from ..typings import LockProtocol, PathLike, _KT, _T, _VT
from .base import BaseDataClass


@dataclass(slots=True)
class JsonContainer(Generic[_KT, _VT], BaseDataClass):
    """A JSON object kept in a file, read on first access and written on `save()`.

    Attributes:
        path: The JSON file.
        lock: A lock held while the file is read or written.
        data: The loaded object, or the `object` class itself while nothing is loaded.
    """

    path: PathLike
    lock: LockProtocol | None = None

    data: dict[_KT, _VT] | type[object] = field(default=object, init=False)

    def is_loaded(self) -> bool:
        """Return whether the file has been read."""
        return self.data is not object

    def unload(self) -> None:
        """Drop the loaded data, so the next access reads the file again."""
        self.data = object

    def load(self, **kw: Any) -> None:
        """Read the file, unless it is already loaded.

        Args:
            **kw: Passed to `read_json()`.
        """
        if not self.is_loaded():
            self.data = read_json(self.path, lock=self.lock, **kw)

    def save(self, **kw: Any) -> None:
        """Write the loaded data to the file.

        Args:
            **kw: Passed to `write_json()`.

        Raises:
            RuntimeError: If nothing is loaded.
        """
        if not self.is_loaded():
            msg = "JsonContainer has no data loaded to save"
            raise RuntimeError(msg)

        write_json(self.path, self.data, self.lock, **kw)

    def get(self, key: _KT, default: _T | None = None) -> _VT | _T | None:
        """Return the value under `key`, loading the file first if needed.

        Args:
            key: The key.
            default: Returned if `key` is absent.

        Returns:
            The value, or `default`.
        """
        self.load()
        return self.data.get(key, default)

    def set(self, key: _KT, value: _VT, save_now: bool = False) -> None:
        """Store `value` under `key`, loading the file first if needed.

        Args:
            key: The key.
            value: The value.
            save_now: Write the file afterwards.
        """
        self.load()

        self.data[key] = value

        if save_now:
            self.save()

    def delete(self, key: _KT, save_now: bool = False) -> None:
        """Remove `key` if present, loading the file first if needed.

        Args:
            key: The key.
            save_now: Write the file afterwards, if the key was removed.
        """
        self.load()

        if key in self.data:
            del self.data[key]

            if save_now:
                self.save()

    def update(self, update: dict[_KT, _VT], save_now: bool = False) -> None:
        """Merge `update` into the data, loading the file first if needed.

        Args:
            update: The entries to set.
            save_now: Write the file afterwards.
        """
        self.load()

        self.data.update(update)

        if save_now:
            self.save()

    async def async_load(self, **kw: Any) -> None:
        """Run `load()` in a thread.

        Args:
            **kw: Passed to `read_json()`.
        """
        await to_thread(self.load, **kw)

    async def async_save(self, **kw: Any) -> None:
        """Run `save()` in a thread.

        Args:
            **kw: Passed to `write_json()`.
        """
        await to_thread(self.save, **kw)

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
        return self.data.get(key, default)

    async def async_set(self, key: _KT, value: _VT, save_now: bool = False) -> None:
        """Async `set()`: the file is read and written in a thread.

        Args:
            key: The key.
            value: The value.
            save_now: Write the file afterwards.
        """
        if not self.is_loaded():
            await self.async_load()

        self.data[key] = value

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

        if key in self.data:
            del self.data[key]

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

        self.data.update(update)

        if save_now:
            await self.async_save()


__all__ = ("JsonContainer",)
