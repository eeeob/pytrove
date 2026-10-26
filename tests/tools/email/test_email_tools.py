from __future__ import annotations as _annotations

from email.message import EmailMessage
from importlib.util import find_spec
from typing import Any, ClassVar

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

ARABIC_NAME = "علي حسن"
BACKSLASH = chr(92)


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


def _encoded_message(text: str) -> bytes:
    """Build a multipart/alternative email: a quoted-printable text part and a base64 HTML part."""
    msg = EmailMessage()
    msg["From"] = "noreply@telegram.org"
    msg.set_content(text, cte="quoted-printable")
    msg.add_alternative(f"<p>{text}</p>", subtype="html", cte="base64")
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


@needs_bs4
def test_parse_email_bytes_decodes_quoted_printable_and_base64_parts() -> None:
    raw = _encoded_message(f"Hello {ARABIC_NAME}")

    assert b"=D8" in raw  # the text part really is quoted-printable
    assert parse_email_bytes(raw, multi_part_sep="|") == f"Hello {ARABIC_NAME}|Hello {ARABIC_NAME}|"


@needs_bs4
def test_parse_email_bytes_skips_a_non_text_part() -> None:
    msg = EmailMessage()
    msg.set_content("body")
    msg.add_attachment(b"binary", maintype="application", subtype="octet-stream")

    assert parse_email_bytes(msg.as_bytes()) == "body"


@needs_bs4
def test_parse_email_bytes_reads_a_bytearray() -> None:
    assert parse_email_bytes(bytearray(_message("hello"))) == "hello"


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
    """Stands in for `aioimaplib.IMAP4_SSL`: serves `inbox` as a server would and records requests."""

    inbox: ClassVar[dict[int, bytes]] = {}
    search_answer: ClassVar[tuple[str, Any] | None] = None
    fetch_answer: ClassVar[tuple[str, Any] | None] = None
    login_error: ClassVar[Exception | None] = None
    sent: ClassVar[dict[str, Any]] = {}
    logged_out: ClassVar[bool] = False

    def __init__(self, host: str, port: int) -> None:
        """Accept the server address."""

    async def wait_hello_from_server(self) -> None:
        """Pretend the server greeted us."""

    async def login(self, email: str, password: str) -> None:
        """Record the login, or fail with `login_error`."""
        _FakeImap.sent["login"] = (email, password)

        if _FakeImap.login_error is not None:
            raise _FakeImap.login_error

    async def select(self, box: str) -> None:
        """Record the mailbox."""
        _FakeImap.sent["select"] = box

    async def search(self, query: str) -> tuple[str, Any]:
        """Answer with every id in the inbox, as `aioimaplib` shapes it, or `search_answer`."""
        _FakeImap.sent["search"] = query

        if _FakeImap.search_answer is not None:
            return _FakeImap.search_answer

        ids = " ".join(str(uid) for uid in sorted(_FakeImap.inbox)).encode()
        return "OK", [ids, b"SEARCH completed"]

    async def fetch(self, ids: str, what: str) -> tuple[str, Any]:
        """Serve the requested section of each message, as `bytearray`, or `fetch_answer`."""
        _FakeImap.sent["fetch"] = (ids, what)

        if _FakeImap.fetch_answer is not None:
            return _FakeImap.fetch_answer

        # `BODY[]` is the whole message; `BODY[TEXT]` leaves the headers out.
        sections = {
            "BODY.PEEK[]": lambda raw: raw,
            "BODY.PEEK[TEXT]": lambda raw: raw.split(b"\n\n", 1)[1],
        }
        lines: list[bytes | bytearray] = []

        for uid in ids.split(","):
            served = sections[what](_FakeImap.inbox[int(uid)])
            lines += [f"{uid} FETCH (BODY[] {{{len(served)}}}".encode(), bytearray(served), b")"]

        return "OK", [*lines, b"Fetch completed"]

    async def logout(self) -> None:
        """Record the logout."""
        _FakeImap.logged_out = True


@pytest.fixture
def fake_imap(monkeypatch: pytest.MonkeyPatch) -> type[_FakeImap]:
    """Replace the IMAP client with `_FakeImap`, starting from an empty inbox."""
    monkeypatch.setattr(email_tools.aioimaplib, "IMAP4_SSL", _FakeImap)
    monkeypatch.setattr(_FakeImap, "inbox", {})
    monkeypatch.setattr(_FakeImap, "sent", {})
    monkeypatch.setattr(_FakeImap, "logged_out", False)
    return _FakeImap


async def _collect(**kwargs: Any) -> list[str]:
    """Run `fetch_emails_from` against Gmail and collect what it yields."""
    return [
        text
        async for text in fetch_emails_from("me@gmail.com", "pw", ImapEmailProvider.GMAIL, **kwargs)
    ]


@needs_imap
async def test_fetch_emails_from_yields_newest_first(fake_imap: type[_FakeImap]) -> None:
    fake_imap.inbox.update({1: _message("first"), 2: _message("second")})

    assert await _collect() == ["second", "first"]
    assert await _collect(from_old=True) == ["first", "second"]
    assert fake_imap.logged_out
    assert fake_imap.sent == {
        "login": ("me@gmail.com", "pw"),
        "select": "INBOX",
        "search": 'FROM "noreply@telegram.org"',
        "fetch": ("1,2", "BODY.PEEK[]"),
    }


@needs_imap
async def test_fetch_emails_from_decodes_a_multipart_message(fake_imap: type[_FakeImap]) -> None:
    fake_imap.inbox[1] = _encoded_message(f"Hello {ARABIC_NAME}, your code is 123456")

    [text] = await _collect()

    assert f"Hello {ARABIC_NAME}, your code is 123456" in text
    assert "Content-Type" not in text
    assert "=D8" not in text


@needs_imap
@pytest.mark.parametrize(
    ("limit", "fetched"),
    [(2, "2,3"), (3, "1,2,3"), (5, "1,2,3"), (1, "3")],
)
async def test_fetch_emails_from_reads_the_newest_limit_ids(
    fake_imap: type[_FakeImap], limit: int, fetched: str
) -> None:
    fake_imap.inbox.update({uid: _message(f"m{uid}") for uid in (1, 2, 3)})

    assert len(await _collect(limit=limit)) == len(fetched.split(","))
    assert fake_imap.sent["fetch"] == (fetched, "BODY.PEEK[]")


@needs_imap
@pytest.mark.parametrize("limit", [0, -1])
async def test_fetch_emails_from_yields_nothing_for_a_limit_below_one(
    fake_imap: type[_FakeImap], limit: int
) -> None:
    fake_imap.inbox[1] = _message("first")

    assert await _collect(limit=limit) == []
    assert "fetch" not in fake_imap.sent
    assert fake_imap.logged_out


@needs_imap
async def test_fetch_emails_from_yields_nothing_when_no_email_matches(
    fake_imap: type[_FakeImap],
) -> None:
    # `aioimaplib` turns a bare `* SEARCH` into `[b"", b"SEARCH completed"]`.
    assert await _collect() == []
    assert "fetch" not in fake_imap.sent
    assert fake_imap.logged_out


@needs_imap
async def test_fetch_emails_from_escapes_the_sender_in_the_query(
    fake_imap: type[_FakeImap],
) -> None:
    await _collect(sender=f'a"b{BACKSLASH}c')

    assert fake_imap.sent["search"] == f'FROM "a{BACKSLASH}"b{BACKSLASH}{BACKSLASH}c"'


@needs_imap
@pytest.mark.parametrize("sender", ["a\nb", "a\rb"])
async def test_fetch_emails_from_refuses_a_sender_with_a_line_break(
    fake_imap: type[_FakeImap], sender: str
) -> None:
    with pytest.raises(ValidationError, match="line break"):
        await _collect(sender=sender)

    assert fake_imap.sent == {}


@needs_imap
async def test_fetch_emails_from_logs_out_when_the_login_fails(
    fake_imap: type[_FakeImap], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fake_imap, "login_error", OSError("refused"))

    with pytest.raises(OSError, match="refused"):
        await _collect()

    assert fake_imap.logged_out


@needs_imap
@pytest.mark.parametrize(
    ("search", "fetch", "message"),
    [
        (("NO", [b""]), ("OK", []), "Invalid Email Status"),
        (("OK", []), ("OK", []), "Invalid Email data"),
        (("OK", None), ("OK", []), "Invalid Email data"),
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
