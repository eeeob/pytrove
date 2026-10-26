from __future__ import annotations as _annotations

import importlib.util
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from pytrove.validate_tools import contact
from pytrove.validate_tools.contact import (
    is_accessible_received_email,
    is_email,
    is_phone_number,
    is_rc,
)

HAS_PHONENUMBERS = importlib.util.find_spec("phonenumbers") is not None
HAS_AIOIMAPLIB = importlib.util.find_spec("aioimaplib") is not None

needs_phonenumbers = pytest.mark.skipif(not HAS_PHONENUMBERS, reason="needs the phone extra")
needs_aioimaplib = pytest.mark.skipif(not HAS_AIOIMAPLIB, reason="needs the imap extra")


@needs_phonenumbers
@pytest.mark.parametrize(
    ("number", "kwargs", "expected"),
    [
        ("+966 50 123 4567", {}, True),
        ("00966501234567", {}, True),
        ("966501234567", {}, True),
        (966501234567, {}, True),
        ("966501234567", {"resolve": False}, False),
        ("+966 50 123 4567", {"remove_spaces": False}, True),
        ("123", {}, False),
        ("not a number", {}, False),
        (None, {}, False),
        (True, {}, False),
        ("+966\t50 123\n4567", {}, True),
        ("+966\t50 123\n4567", {"remove_spaces": False}, False),
        ("+00966501234567", {}, False),
    ],
)
def test_is_phone_number(number: Any, kwargs: dict[str, Any], expected: bool) -> None:
    assert is_phone_number(number, **kwargs) is expected


@needs_phonenumbers
def test_is_phone_number_accepts_a_parsed_number() -> None:
    phonenumbers = pytest.importorskip("phonenumbers")
    assert is_phone_number(phonenumbers.parse("+966501234567"))


@needs_phonenumbers
def test_is_phone_number_is_false_for_an_invalid_parsed_number() -> None:
    phonenumbers = pytest.importorskip("phonenumbers")
    assert is_phone_number(phonenumbers.parse("+1 555 0100")) is False


@needs_phonenumbers
def test_is_phone_number_is_false_when_the_validity_check_itself_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(number: Any) -> bool:
        """Fail the way a broken metadata lookup would."""
        msg = "boom"
        raise RuntimeError(msg)

    monkeypatch.setattr(contact.phonenumbers, "is_possible_number", explode)
    assert is_phone_number("+966501234567") is False


@needs_phonenumbers
@pytest.mark.parametrize(
    ("rc", "expected"),
    [
        ("SA", True),
        ("sa", True),
        ("ZZ", False),
        ("S1", False),
        ("SAU", False),
        (966, False),
        ("zz", False),
        ("", False),
        (None, False),
        ("\u00c5\u00c5", False),
    ],
)
def test_is_rc(rc: Any, expected: bool) -> None:
    assert is_rc(rc) is expected


@pytest.mark.skipif(HAS_PHONENUMBERS, reason="the phone extra is installed")
def test_the_phone_checks_name_the_phone_extra_when_phonenumbers_is_missing() -> None:
    with pytest.raises(ImportError, match=r"pytrove\[phone\]"):
        is_phone_number("+966501234567")

    with pytest.raises(ImportError, match=r"pytrove\[phone\]"):
        is_rc("sa")


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("user.name+tag@example.co", True),
        ("user@example.com", True),
        ("user@example", False),
        ("not-an-email", False),
        ("@example.com", False),
        ("user@example.com extra", False),
        (None, False),
        (123, False),
        ("user@example.com\n", False),
        ("USER@EXAMPLE.COM", True),
        # A plain pattern, not RFC 5322: consecutive dots in the local part pass.
        ("a..b@example.com", True),
        ("\u00fcser@example.com", False),
    ],
)
def test_is_email(email: Any, expected: bool) -> None:
    assert is_email(email) is expected


class _FakeTransport:
    """Records whether it was closed."""

    closed = False

    def close(self) -> None:
        """Record the close."""
        self.closed = True


class _FakeImap:
    """Stands in for `aioimaplib.IMAP4_SSL`; answers a login with `result` like the real one."""

    error: BaseException | None = None
    hello_error: BaseException | None = None
    logout_error: BaseException | None = None
    result: str = "OK"
    seen: list[tuple[str, int]] = []
    logouts: int = 0
    instances: list[_FakeImap] = []

    def __init__(self, host: str, port: int) -> None:
        """Record which server was asked for."""
        _FakeImap.seen.append((host, port))
        _FakeImap.instances.append(self)
        self.protocol = SimpleNamespace(transport=_FakeTransport())

    async def wait_hello_from_server(self) -> None:
        """Pretend the server greeted us, or raise `hello_error`."""
        if self.hello_error is not None:
            raise self.hello_error

    async def login(self, email: str, password: str) -> SimpleNamespace:
        """Answer with `result`, as aioimaplib does even for a rejected login, or raise `error`."""
        if self.error is not None:
            raise self.error

        return SimpleNamespace(result=self.result)

    async def logout(self) -> None:
        """Log out, or raise `logout_error`."""
        _FakeImap.logouts += 1

        if self.logout_error is not None:
            raise self.logout_error


@pytest.fixture
def fake_imap(monkeypatch: pytest.MonkeyPatch) -> type[_FakeImap]:
    """Replace the IMAP client with `_FakeImap`, reset for each test."""
    monkeypatch.setattr(_FakeImap, "error", None)
    monkeypatch.setattr(_FakeImap, "hello_error", None)
    monkeypatch.setattr(_FakeImap, "logout_error", None)
    monkeypatch.setattr(_FakeImap, "result", "OK")
    monkeypatch.setattr(_FakeImap, "seen", [])
    monkeypatch.setattr(_FakeImap, "logouts", 0)
    monkeypatch.setattr(_FakeImap, "instances", [])
    monkeypatch.setattr(contact.aioimaplib, "IMAP4_SSL", _FakeImap)
    return _FakeImap


@needs_aioimaplib
async def test_is_accessible_received_email_logs_in_to_the_providers_server(
    fake_imap: type[_FakeImap],
) -> None:
    assert await is_accessible_received_email("me@gmail.com", "pw") is True
    assert fake_imap.seen == [("imap.gmail.com", 993)]


@needs_aioimaplib
async def test_is_accessible_received_email_is_false_on_a_failed_login(
    fake_imap: type[_FakeImap],
) -> None:
    fake_imap.error = RuntimeError()
    assert await is_accessible_received_email("me@gmail.com", "pw") is False


@needs_aioimaplib
@pytest.mark.parametrize(("result", "expected"), [("OK", True), ("NO", False), ("BAD", False)])
async def test_is_accessible_received_email_reads_the_login_result(
    fake_imap: type[_FakeImap],
    caplog: pytest.LogCaptureFixture,
    result: str,
    expected: bool,
) -> None:
    fake_imap.result = result

    with caplog.at_level(logging.ERROR):
        assert await is_accessible_received_email("me@gmail.com", "wrong") is expected

    # LOGOUT is valid before authentication too, so a rejected login still logs out cleanly.
    assert fake_imap.logouts == 1
    assert caplog.records == []


@needs_aioimaplib
@pytest.mark.parametrize("error", [OSError(), TimeoutError()])
async def test_is_accessible_received_email_is_false_without_a_greeting(
    fake_imap: type[_FakeImap],
    caplog: pytest.LogCaptureFixture,
    error: BaseException,
) -> None:
    fake_imap.hello_error = error

    with caplog.at_level(logging.ERROR):
        assert await is_accessible_received_email("me@gmail.com", "pw") is False

    assert fake_imap.logouts == 0
    assert fake_imap.instances[0].protocol.transport.closed
    assert caplog.records == []


@needs_aioimaplib
async def test_is_accessible_received_email_survives_a_greeting_failure_without_a_transport(
    fake_imap: type[_FakeImap],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_imap.hello_error = OSError()
    original_init = _FakeImap.__init__

    def init(self: _FakeImap, host: str, port: int) -> None:
        """Build the client, then drop its transport, as when the connection was refused."""
        original_init(self, host, port)
        self.protocol = SimpleNamespace(transport=None)

    monkeypatch.setattr(_FakeImap, "__init__", init)
    assert await is_accessible_received_email("me@gmail.com", "pw") is False


@needs_aioimaplib
async def test_is_accessible_received_email_is_false_for_an_unknown_provider(
    fake_imap: type[_FakeImap],
) -> None:
    assert await is_accessible_received_email("me@unknown.example", "pw") is False
    assert fake_imap.seen == []


@needs_aioimaplib
async def test_is_accessible_received_email_logs_a_failed_logout(
    fake_imap: type[_FakeImap],
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_imap.logout_error = OSError()
    assert await is_accessible_received_email("me@gmail.com", "pw") is True
    assert "Failed to log out" in caplog.text


@pytest.mark.skipif(HAS_AIOIMAPLIB, reason="the imap extra is installed")
async def test_is_accessible_received_email_names_the_imap_extra_when_aioimaplib_is_missing() -> (
    None
):
    with pytest.raises(ImportError, match=r"pytrove\[imap\]"):
        await is_accessible_received_email("me@gmail.com", "pw")
