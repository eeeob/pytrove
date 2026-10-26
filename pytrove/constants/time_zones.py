"""Fixed-offset time zones."""

from __future__ import annotations as _annotations

from datetime import timedelta, timezone
from typing import Final

TZ_UTC_PLUS_3: Final[timezone] = timezone(timedelta(hours=3), "UTC+3")
"""A fixed UTC+3 offset named `"UTC+3"`, independent of the machine's local zone."""

__all__ = ("TZ_UTC_PLUS_3",)
