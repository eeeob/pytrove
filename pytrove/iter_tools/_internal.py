"""Helpers private to `iter_tools`."""

from __future__ import annotations as _annotations

from collections.abc import MutableSequence
from typing import Any, TypeVar

_MS = TypeVar("_MS", bound=MutableSequence[Any])
"""A mutable sequence, kept with its exact type through `shuffle`."""

__all__ = ("_MS",)
