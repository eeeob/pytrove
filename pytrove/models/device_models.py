"""The device a Telegram client reports."""

from __future__ import annotations as _annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """One plausible device: a model string and an OS version that model runs."""

    model: str
    """What the client sends as `device_model`."""

    version: str
    """What the client sends as `system_version`."""

    def __str__(self) -> str:
        """Return the model and version, separated by a space."""
        return f"{self.model} {self.version}"

    def to_dict(self) -> dict[str, str]:
        """Return the two fields under the names Telegram's `initConnection` uses.

        Returns:
            `{"device_model": ..., "system_version": ...}`.
        """
        return {"device_model": self.model, "system_version": self.version}


__all__ = ("DeviceInfo",)
