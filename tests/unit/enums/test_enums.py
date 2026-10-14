from __future__ import annotations as _annotations

import enum

import pytest

import pytrove.enums
from pytrove.enums import (
    ArchiveDuplicatePolicy,
    ArchiveFormat,
    ArchiveLinkPolicy,
    ArchiveOverwritePolicy,
    ImapEmailProvider,
    PickleSafety,
    PlatformDevice,
    StrEnum,
    TgMessageLength,
    TimeUnit,
    TriggerOn,
    TruncateSide,
    IMAP_DOMAIN_TO_PROVIDER,
)


def test_the_entry_point_exports_every_enum_and_the_domain_table() -> None:
    assert set(pytrove.enums.__all__) == {
        "ArchiveFormat", "ArchiveDuplicatePolicy", "ArchiveLinkPolicy", "ArchiveOverwritePolicy",
        "ImapEmailProvider", "PickleSafety", "PlatformDevice", "TgMessageLength", "TimeUnit",
        "TriggerOn", "TruncateSide", "IMAP_DOMAIN_TO_PROVIDER",
    }


def test_str_enum_members_are_strings_with_lowercase_auto_values() -> None:
    class Color(StrEnum):
        RED = enum.auto()

    assert Color.RED == "red"
    assert isinstance(Color.RED, str)
    assert str(Color.RED) == "red"
    assert f"{Color.RED}" == "red"


def test_trigger_on_values() -> None:
    assert [m.value for m in TriggerOn] == ["success", "error", "always"]


def test_tg_message_length_limits() -> None:
    assert TgMessageLength.TEXT == 4096
    assert TgMessageLength.CAPTION == 1024


def test_archive_format_values_are_the_extensions() -> None:
    assert [m.value for m in ArchiveFormat] == ["zip", "tar.gz", "tar.zst"]


@pytest.mark.parametrize(("policy", "values"), [
    (ArchiveLinkPolicy, ["allow", "skip", "error"]),
    (ArchiveOverwritePolicy, ["error", "skip", "overwrite"]),
    (ArchiveDuplicatePolicy, ["skip", "error"]),
])
def test_archive_policy_values(policy: type[StrEnum], values: list[str]) -> None:
    assert [m.value for m in policy] == values
    assert all(policy(v) == v for v in values)


def test_pickle_safety_is_ordered_by_strictness() -> None:
    assert PickleSafety.NONE < PickleSafety.BLOCKLIST < PickleSafety.MODULES < PickleSafety.STRICT
    assert [m.value for m in PickleSafety] == [0, 1, 2, 3]


def test_truncate_side_values() -> None:
    assert TruncateSide.TAIL == "tail"
    assert TruncateSide.HEAD == "head"


@pytest.mark.parametrize(("provider", "host"), [
    (ImapEmailProvider.GMAIL, "imap.gmail.com"),
    (ImapEmailProvider.OUTLOOK, "outlook.office365.com"),
    (ImapEmailProvider.YAHOO, "imap.mail.yahoo.com"),
    (ImapEmailProvider.ZOHO, "imap.zoho.com"),
])
def test_imap_provider_host_and_port(provider: ImapEmailProvider, host: str) -> None:
    assert provider.host == host
    assert provider.port == 993


@pytest.mark.parametrize(("domain", "provider"), [
    ("gmail.com", ImapEmailProvider.GMAIL),
    ("GMAIL.COM", ImapEmailProvider.GMAIL),
    ("hotmail.com", ImapEmailProvider.OUTLOOK),
    ("live.com", ImapEmailProvider.OUTLOOK),
    ("yahoo.com", ImapEmailProvider.YAHOO),
    ("unknown.example", None),
])
def test_imap_provider_from_domain(domain: str, provider: ImapEmailProvider | None) -> None:
    assert ImapEmailProvider.from_domain(domain) is provider


def test_imap_domain_table_covers_every_provider_with_lowercase_keys() -> None:
    assert set(IMAP_DOMAIN_TO_PROVIDER.values()) == set(ImapEmailProvider)
    assert all(key == key.lower() for key in IMAP_DOMAIN_TO_PROVIDER)


def test_platform_device_values() -> None:
    assert [m.value for m in PlatformDevice] == ["android", "ios", "desktop", "web"]


def test_time_unit_values_in_seconds() -> None:
    assert TimeUnit.MINUTE == 60
    assert TimeUnit.HOUR == 3600
    assert TimeUnit.DAY == 86400
    assert TimeUnit.WEEK == 7 * 86400
    assert TimeUnit.MONTH == 30 * 86400
    assert TimeUnit.YEAR == 360 * 86400
