"""Every enum pytrove shares between its sections."""

from __future__ import annotations as _annotations

import sys
from enum import Enum, IntEnum, auto
from typing import Any, Final

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:

    class StrEnum(str, Enum):
        """Backport of `enum.StrEnum` for Python 3.10: members are strings, `auto()` is the lowercase name."""

        @staticmethod
        def _generate_next_value_(name: str, start: int, count: int, last_values: list[Any]) -> str:
            """Return the lowercase member name as the value of an `auto()` member.

            Args:
                name: The member's name.
                start: Unused; part of the `Enum` hook signature.
                count: Unused; part of the `Enum` hook signature.
                last_values: Unused; part of the `Enum` hook signature.

            Returns:
                `name` in lowercase.
            """
            del start, count, last_values  # The hook passes them; only the name decides.
            return name.lower()

        __str__ = str.__str__

        def __format__(self, format_spec: str) -> str:
            """Format the member as its string value, as `str.__format__` does.

            Args:
                format_spec: The format specification.

            Returns:
                The formatted value.
            """
            return str.__format__(self, format_spec)


class TriggerOn(StrEnum):
    """Which outcome of a call makes a `DeferredCall` fire."""

    SUCCESS = auto()
    """Fire only when the result is not an exception. The default."""

    ERROR = auto()
    """Fire only when the result is an exception instance."""

    ALWAYS = auto()
    """Fire whatever the result is."""


class TgMessageLength(IntEnum):
    """Telegram's length limits, in characters."""

    TEXT = 4096
    """A text message; the default length `split_tg_message` and `chunk_text` cut at."""

    CAPTION = 1024
    """A media caption."""


class ArchiveFormat(StrEnum):
    """Container and codec `compress_folder` writes; the value is the archive's extension."""

    ZIP = "zip"
    """Deflate, one member per file: compresses in parallel, extracts one file alone, opens in Windows Explorer."""

    TAR_GZ = "tar.gz"
    """Gzip over one tar stream: universally readable, but neither parallel nor randomly accessible."""

    TAR_ZST = "tar.zst"
    """Zstandard over one tar stream: gzip's ratio several times faster. Needs the `archive` extra below 3.14."""


class ArchiveLinkPolicy(StrEnum):
    """What `extract_archive` does with a link member (`ArchiveLimits.symlinks`/`hardlinks`).

    No value lets a link point outside the destination: that is refused
    whatever the policy, because a later member written through it would escape.
    """

    ALLOW = auto()
    """Recreate the link, as long as it points inside the destination."""

    SKIP = auto()
    """Leave the member out and log it."""

    ERROR = auto()
    """Stop the extraction with `ArchivePolicyError`. The default."""


class ArchiveOverwritePolicy(StrEnum):
    """What `extract_archive` does when a member's path is already taken.

    "Taken" covers a file that existed before and one an earlier member just
    wrote (such as `Readme.txt` and `README.TXT` on a case-insensitive disk).
    No value lets a member replace a directory.
    """

    ERROR = auto()
    """Stop the extraction with `ArchivePolicyError`."""

    SKIP = auto()
    """Keep what is there, leave the member out, and log it."""

    OVERWRITE = auto()
    """Replace what is there. The default."""


class ArchiveDuplicatePolicy(StrEnum):
    """What `extract_archive` does with a member name it has already seen; the first one always wins."""

    SKIP = auto()
    """Leave the later duplicates out and log them. The default."""

    ERROR = auto()
    """Stop the extraction with `ArchivePolicyError`."""


class PickleSafety(IntEnum):
    """How much `read_pickle` will reconstruct; a higher member is always at least as strict."""

    NONE = 0
    """No restriction: plain `pickle.loads`. Only for files nothing else can write."""

    BLOCKLIST = 1
    """Everything except known code-execution vectors. A guard against accidents, not attackers."""

    MODULES = 2
    """The safe types plus anything defined in a module listed in `allow_modules`."""

    STRICT = 3
    """Only inert builtin and stdlib types plus `allow_classes`. The default."""


class TruncateSide(StrEnum):
    """Which end of a file `truncate_file` removes."""

    TAIL = "tail"
    """Keep the first `size` bytes; cheap, since the kept bytes do not move."""

    HEAD = "head"
    """Keep the last `size` bytes, as a log wants; the kept part is rewritten."""


class ImapEmailProvider(Enum):
    """A known IMAP provider; the value is its `(host, port)`."""

    GMAIL = ("imap.gmail.com", 993)
    """Google: `gmail.com`."""

    OUTLOOK = ("outlook.office365.com", 993)
    """Microsoft: `outlook.com`, `hotmail.com` and `live.com` all map here."""

    YAHOO = ("imap.mail.yahoo.com", 993)
    """Yahoo: `yahoo.com`."""

    ZOHO = ("imap.zoho.com", 993)
    """Zoho: `zoho.com`."""

    @property
    def host(self) -> str:
        """The IMAP server's host name."""
        return self.value[0]

    @property
    def port(self) -> int:
        """The IMAP server's SSL port."""
        return self.value[1]

    @classmethod
    def from_domain(cls, domain: str) -> ImapEmailProvider | None:
        """Find the provider serving an email domain.

        Args:
            domain: The part of an address after `@`, in any case.

        Returns:
            The provider, or `None` when the domain is not a known one.
        """
        return IMAP_DOMAIN_TO_PROVIDER.get(domain.lower())


class PlatformDevice(StrEnum):
    """A Telegram client platform, as `random_device` draws them."""

    ANDROID = auto()
    """Telegram for Android; the likeliest draw."""

    IOS = auto()
    """Telegram for iOS."""

    DESKTOP = auto()
    """Telegram Desktop; the only platform that draws an OS (Windows or Linux) first."""

    WEB = auto()
    """Telegram Web: the model is a browser user agent, the version a `navigator.platform`."""


class TimeUnit(IntEnum):
    """Durations in seconds."""

    MINUTE = 60
    """60 seconds."""

    HOUR = MINUTE * 60
    """3600 seconds."""

    DAY = HOUR * 24
    """86400 seconds."""

    WEEK = DAY * 7
    """Seven days."""

    MONTH = DAY * 30
    """A fixed 30 days, not a calendar month."""

    YEAR = MONTH * 12
    """Twelve 30-day months (360 days), not a calendar year."""


IMAP_DOMAIN_TO_PROVIDER: Final[dict[str, ImapEmailProvider]] = {
    "gmail.com": ImapEmailProvider.GMAIL,
    "outlook.com": ImapEmailProvider.OUTLOOK,
    "hotmail.com": ImapEmailProvider.OUTLOOK,
    "live.com": ImapEmailProvider.OUTLOOK,
    "yahoo.com": ImapEmailProvider.YAHOO,
    "zoho.com": ImapEmailProvider.ZOHO,
}
"""Lowercase email domain -> its IMAP provider. Defined after the enum because it holds its members."""


__all__ = (
    "ArchiveFormat",
    "ArchiveDuplicatePolicy",
    "ArchiveLinkPolicy",
    "ArchiveOverwritePolicy",
    "ImapEmailProvider",
    "PickleSafety",
    "PlatformDevice",
    "TgMessageLength",
    "TimeUnit",
    "TriggerOn",
    "TruncateSide",
    "IMAP_DOMAIN_TO_PROVIDER",
)
