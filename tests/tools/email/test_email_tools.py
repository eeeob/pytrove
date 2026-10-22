from __future__ import annotations as _annotations

from email.message import EmailMessage
from importlib.util import find_spec
from typing import Any

import pytest

from pytrove import email_tools
from pytrove.email_tools import detect_email_provider, fetch_emails_from, parse_email_bytes
from pytrove.enums import ImapEmailProvider
from pytrove.errors import ValidationError

_HAS_BS4 = find_spec("bs4") is not None
_HAS_IMAP = find_spec("aioimaplib") is not None

needs_bs4 = pytest.mark.skipif(not _HAS_BS4, reason="needs the `bs4` extra")
needs_imap = pytest.mark.skipif(
    not (_HAS_IMAP and _HAS_BS4), reason="needs the `imap` and `bs4` extras"
)


def _message(plain: str | None = None, html_body: str | None = None) -> bytes:
    """Build a raw email with the given parts."""
    msg = EmailMessage()

    if plain is not None:
        msg.set_content(plain)
    if html_body is not None:
        if plain is None:
            msg.set_content(html_body, subtype="html")
        else:
            msg.add_alternative(html_body, subtype="html")

    return msg.as_bytes()


@needs_bs4
def test_parse_email_bytes_reads_plain_and_html_parts() -> None:
    assert parse_email_bytes(_message("hello")) == "hello"
    assert parse_email_bytes(_message(html_body="<p>a &amp; b</p>")) == "a & b"
    assert parse_email_bytes(_message("x", "<b>y</b>"), multi_part_sep="|") == "x|y|"


@needs_bs4
def test_parse_email_bytes_skips_blank_parts_and_falls_back_on_an_unknown_charset() -> None:
    assert parse_email_bytes(_message("  \n", "<p> </p>")) == ""

    raw = b'Content-Type: text/plain; charset="no-such-charset"\n\nplain\n'
    assert parse_email_bytes(raw) == "plain"


@pytest.mark.skipif(_HAS_BS4, reason="needs the `bs4` extra to be missing")
def test_parse_email_bytes_needs_the_bs4_extra() -> None:
    with pytest.raises(ImportError, match=r"pytrove\[bs4\]"):
        parse_email_bytes(_message("hello"))


def test_detect_email_provider() -> None:
    assert detect_email_provider("me@Gmail.com") is ImapEmailProvider.GMAIL
    assert detect_email_provider("me@unknown.example") is None

    with pytest.raises(ValidationError, match="not valid email"):
        detect_email_provider("nope")


class _FakeImap:
    """Stands in for `aioimaplib.IMAP4_SSL` with canned answers."""

    search_answer: tuple[str, list[bytes]] = ("OK", [b"1 2"])
    fetch_answer: tuple[str, Any] = ("OK", [])
    logged_out = False

    def __init__(self, host: str, port: int) -> None:
        """Accept the server address."""

    async def wait_hello_from_server(self) -> None:
        """Pretend the server greeted us."""

    async def login(self, email: str, password: str) -> None:
        """Pretend to log in."""

    async def select(self, box: str) -> None:
        """Pretend to open a mailbox."""

    async def search(self, query: str) -> tuple[str, list[bytes]]:
        """Return the canned search answer."""
        return self.search_answer

    async def fetch(self, ids: str, what: str) -> tuple[str, Any]:
        """Return the canned fetch answer."""
        return self.fetch_answer

    async def logout(self) -> None:
        """Record the logout."""
        _FakeImap.logged_out = True


@pytest.fixture
def fake_imap(monkeypatch: pytest.MonkeyPatch) -> type[_FakeImap]:
    """Replace the IMAP client with `_FakeImap`."""
    monkeypatch.setattr(email_tools.aioimaplib, "IMAP4_SSL", _FakeImap)
    monkeypatch.setattr(_FakeImap, "logged_out", False)
    return _FakeImap


async def _collect(**kwargs: Any) -> list[str]:
    """Run `fetch_emails_from` against Gmail and collect what it yields."""
    return [
        text
        async for text in fetch_emails_from("me@gmail.com", "pw", ImapEmailProvider.GMAIL, **kwargs)
    ]


@needs_imap
async def test_fetch_emails_from_yields_newest_first(
    fake_imap: type[_FakeImap], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        fake_imap,
        "fetch_answer",
        (
            "OK",
            [
                b"1 FETCH (BODY[TEXT] {5}",
                _message("first"),
                b")",
                b"2 FETCH (BODY[TEXT] {6}",
                _message("second"),
                b")",
                b"done",
            ],
        ),
    )
    assert await _collect() == ["second", "first"]
    assert await _collect(from_old=True) == ["first", "second"]
    assert fake_imap.logged_out


@needs_imap
async def test_fetch_emails_from_yields_nothing_for_a_zero_limit(
    fake_imap: type[_FakeImap],
) -> None:
    assert await _collect(limit=0) == []


@needs_imap
@pytest.mark.parametrize(
    ("search", "fetch", "message"),
    [
        (("NO", [b""]), ("OK", []), "Invalid Email Status"),
        (("OK", [b""]), ("OK", []), "Invalid Email data"),
        (("OK", [b"1"]), ("NO", []), "Invalid Fetch Email Status"),
        (("OK", [b"1"]), ("OK", None), "Invalid Fetch Email data"),
    ],
)
async def test_fetch_emails_from_rejects_bad_answers(
    fake_imap: type[_FakeImap],
    monkeypatch: pytest.MonkeyPatch,
    search: Any,
    fetch: Any,
    message: str,
) -> None:
    monkeypatch.setattr(fake_imap, "search_answer", search)
    monkeypatch.setattr(fake_imap, "fetch_answer", fetch)

    with pytest.raises(ValidationError, match=message):
        await _collect()

    assert fake_imap.logged_out


@pytest.mark.skipif(_HAS_IMAP and _HAS_BS4, reason="needs the `imap` or `bs4` extra to be missing")
async def test_fetch_emails_from_needs_the_imap_and_bs4_extras() -> None:
    with pytest.raises(ImportError, match=r"pytrove\[imap, bs4\]"):
        await _collect()
