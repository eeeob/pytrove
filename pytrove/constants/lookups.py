"""Lookup tables from a plain key to the enum member it stands for."""

from __future__ import annotations as _annotations

from typing import Final

from ..enums import ImapEmailProvider

IMAP_DOMAIN_TO_PROVIDER: Final[dict[str, ImapEmailProvider]] = {
    "gmail.com": ImapEmailProvider.GMAIL,
    "googlemail.com": ImapEmailProvider.GMAIL,
    "outlook.com": ImapEmailProvider.OUTLOOK,
    "hotmail.com": ImapEmailProvider.OUTLOOK,
    "live.com": ImapEmailProvider.OUTLOOK,
    "msn.com": ImapEmailProvider.OUTLOOK,
    "yahoo.com": ImapEmailProvider.YAHOO,
    "ymail.com": ImapEmailProvider.YAHOO,
    "zoho.com": ImapEmailProvider.ZOHO,
}
"""Lowercase email domain -> its IMAP provider, as `ImapEmailProvider.from_domain` reads it."""

__all__ = ("IMAP_DOMAIN_TO_PROVIDER",)
