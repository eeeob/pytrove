from __future__ import annotations as _annotations

from typing import Any

import phonenumbers
import pytest

from pytrove.validate_tools import contact
from pytrove.validate_tools.contact import (
    is_accessible_received_email,
    is_email,
    is_phone_number,
    is_rc,
    EMAIL_PATTERN,
)


@pytest.mark.parametrize(("number", "kwargs", "expected"), [
    ("+966 50 123 4567", {}, True),
    ("00966501234567", {}, True),
    ("966501234567", {}, True),
    (966501234567, {}, True),
    ("966501234567", {"resolve": False}, False),
    ("+966 50 123 4567", {"remove_spaces": False}, True),
    ("123", {}, False),
    ("not a number", {}, False),
    (None, {}, False),
])
def test_is_phone_number(number: Any, kwargs: dict[str, Any], expected: bool) -> None:
    assert is_phone_number(number, **kwargs) is expected


def test_is_phone_number_accepts_a_parsed_number() -> None:
    assert is_phone_number(phonenumbers.parse("+966501234567"))


@pytest.mark.parametrize(("rc", "expected"), [
    ("SA", True),
    ("sa", True),
    ("ZZ", False),
    ("S1", False),
    ("SAU", False),
    (966, False),
])
def test_is_rc(rc: Any, expected: bool) -> None:
    assert is_rc(rc) is expected


@pytest.mark.parametrize(("email", "expected"), [
    ("user.name+tag@example.co", True),
    ("user@example", False),
    ("@example.com", False),
    ("user@example.com extra", False),
    (None, False),
])
def test_is_email(email: Any, expected: bool) -> None:
    assert is_email(email) is expected


def test_email_pattern_is_anchored() -> None:
    assert EMAIL_PATTERN.fullmatch("a@b.cd")
    assert not EMAIL_PATTERN.match("x a@b.cd")


class _FakeImap:
    """Stands in for `aioimaplib.IMAP4_SSL`; `login` fails with `error` when set."""

    error: BaseException | None = None
    logout_error: BaseException | None = None
    seen: list[tuple[str, int]] = []

    def __init__(self, host: str, port: int) -> None:
        """Record which server was asked for."""
        _FakeImap.seen.append((host, port))

    async def wait_hello_from_server(self) -> None:
        """Pretend the server greeted us."""

    async def login(self, email: str, password: str) -> None:
        """Log in, or raise `error`."""
        if self.error is not None:
            raise self.error

    async def logout(self) -> None:
        """Log out, or raise `logout_error`."""
        if self.logout_error is not None:
            raise self.logout_error


@pytest.fixture
def fake_imap(monkeypatch: pytest.MonkeyPatch) -> type[_FakeImap]:
    """Replace the IMAP client with `_FakeImap`, reset for each test."""
    monkeypatch.setattr(_FakeImap, "error", None)
    monkeypatch.setattr(_FakeImap, "logout_error", None)
    monkeypatch.setattr(_FakeImap, "seen", [])
    monkeypatch.setattr(contact.aioimaplib, "IMAP4_SSL", _FakeImap)
    return _FakeImap


async def test_is_accessible_received_email_logs_in_to_the_providers_server(fake_imap: type[_FakeImap]) -> None:
    assert await is_accessible_received_email("me@gmail.com", "pw") is True
    assert fake_imap.seen == [("imap.gmail.com", 993)]


async def test_is_accessible_received_email_is_false_on_a_failed_login(fake_imap: type[_FakeImap]) -> None:
    fake_imap.error = RuntimeError()
    assert await is_accessible_received_email("me@gmail.com", "pw") is False


async def test_is_accessible_received_email_is_false_for_an_unknown_provider(fake_imap: type[_FakeImap]) -> None:
    assert await is_accessible_received_email("me@unknown.example", "pw") is False
    assert fake_imap.seen == []


async def test_is_accessible_received_email_logs_a_failed_logout(
    fake_imap: type[_FakeImap], caplog: pytest.LogCaptureFixture,
) -> None:
    fake_imap.logout_error = OSError()
    assert await is_accessible_received_email("me@gmail.com", "pw") is True
    assert "Failed to log out" in caplog.text
