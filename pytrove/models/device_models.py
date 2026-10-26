"""The device a Telegram client reports."""

from __future__ import annotations as _annotations

from dataclasses import asdict, astuple, dataclass


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """One plausible device: a model string and an OS version that model runs.

    The fields carry the names Telegram's `initConnection` uses, so every view
    of the device derives from them.
    """

    device_model: str
    """The device model, as the client sends it."""

    system_version: str
    """The OS version that model runs, as the client sends it."""

    def __str__(self) -> str:
        """Return the model and version, separated by a space.

        Example:
            >>> str(DeviceInfo("Pixel 9", "SDK 35"))
            'Pixel 9 SDK 35'
        """
        return " ".join(astuple(self))

    def to_dict(self) -> dict[str, str]:
        """Return the fields by name, ready to pass to a Telegram client.

        Example:
            >>> DeviceInfo("Pixel 9", "SDK 35").to_dict()
            {'device_model': 'Pixel 9', 'system_version': 'SDK 35'}
        """
        return asdict(self)

    def to_tuple(self) -> tuple[str, str]:
        """Return `(device_model, system_version)`.

        Example:
            >>> DeviceInfo("Pixel 9", "SDK 35").to_tuple()
            ('Pixel 9', 'SDK 35')
        """
        return astuple(self)


__all__ = ("DeviceInfo",)
