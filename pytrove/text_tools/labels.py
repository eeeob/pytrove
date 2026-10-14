"""Status labels for display, with an emoji mark."""

from __future__ import annotations as _annotations

from typing import Any, Literal


def y_or_n(value: Any) -> Literal["✅", "❌"]:
    """Turn a truth value into a check or a cross mark.

    Args:
        value: The value to judge.

    Returns:
        `"✅"` when truthy, else `"❌"`.
    """
    return "✅" if value else "❌"


def en_or_dis(value: Any) -> Literal["مفعل ✅", "معطل ❌"]:
    """Turn a truth value into the Arabic for "enabled" or "disabled".

    Args:
        value: The value to judge.

    Returns:
        `"مفعل ✅"` when truthy, else `"معطل ❌"`.
    """
    return "مفعل ✅" if value else "معطل ❌"


def op_or_cl(value: Any) -> Literal["مفتوح ✅", "مغلق ❌"]:
    """Turn a truth value into the Arabic for "open" or "closed".

    Args:
        value: The value to judge.

    Returns:
        `"مفتوح ✅"` when truthy, else `"مغلق ❌"`.
    """
    return "مفتوح ✅" if value else "مغلق ❌"


__all__ = (
    "y_or_n",
    "en_or_dis",
    "op_or_cl",
)
