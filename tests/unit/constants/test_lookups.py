"""`pytrove.constants.lookups`: the tables cover their enum with normalized keys."""

from __future__ import annotations as _annotations

from pytrove.constants import lookups
from pytrove.constants.lookups import IMAP_DOMAIN_TO_PROVIDER
from pytrove.enums import ImapEmailProvider


def test_imap_domain_table_covers_every_provider_with_lowercase_keys() -> None:
    assert set(IMAP_DOMAIN_TO_PROVIDER.values()) == set(ImapEmailProvider)
    assert all(key == key.lower() for key in IMAP_DOMAIN_TO_PROVIDER)
    assert IMAP_DOMAIN_TO_PROVIDER["hotmail.com"] is ImapEmailProvider.OUTLOOK


def test_imap_domain_table_maps_the_alias_domains() -> None:
    assert IMAP_DOMAIN_TO_PROVIDER["googlemail.com"] is ImapEmailProvider.GMAIL
    assert IMAP_DOMAIN_TO_PROVIDER["msn.com"] is ImapEmailProvider.OUTLOOK
    assert IMAP_DOMAIN_TO_PROVIDER["ymail.com"] is ImapEmailProvider.YAHOO


def test_all_lists_exactly_the_lookups() -> None:
    assert lookups.__all__ == ("IMAP_DOMAIN_TO_PROVIDER",)
