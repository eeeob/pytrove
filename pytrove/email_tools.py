"""Reading emails: provider detection, IMAP fetching and text extraction."""

from __future__ import annotations as _annotations

import html
from email import message_from_bytes
from typing import TYPE_CHECKING

try:
    from aioimaplib import aioimaplib  # type: ignore[import-not-found]  # Optional: the `imap` extra.
except ImportError:
    pass

try:
    import bs4  # type: ignore[import-not-found]  # Optional: the `bs4` extra.
except ImportError:
    pass

from ._internal import _optional_import
from .async_tools import safe_await, to_thread
from .enums import ImapEmailProvider
from .errors import ValidationError
from .validate_tools import is_email

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@_optional_import("bs4")
def parse_email_bytes(bytes_msg: bytes | bytearray, multi_part_sep: str = "\n") -> str:
    """Extract the readable text of a raw email, HTML parts converted to plain text.

    Args:
        bytes_msg: The raw message.
        multi_part_sep: Placed after each text part.

    Returns:
        The text of every non-empty text part, stripped.
    """
    msg = message_from_bytes(bytes_msg)
    text = ""

    for part in msg.walk():
        payload = part.get_payload(decode=True)

        if (
            part.get_content_maintype().lower() != "text"
            or not isinstance(payload, bytes)
            or not payload
        ):
            continue

        charset = part.get_content_charset() or "utf-8"

        try:
            content = payload.decode(charset, errors="ignore")
        except LookupError:
            content = payload.decode(errors="ignore")

        if part.get_content_subtype().lower() == "html":
            content = html.unescape(
                bs4.BeautifulSoup(content, "html.parser").get_text(separator="\n")
            ).strip()
        else:
            content = content.strip()

        if content:
            text += content + multi_part_sep

    return text.strip()


def detect_email_provider(email: str) -> ImapEmailProvider | None:
    """Find the IMAP provider serving an address.

    Args:
        email: The address.

    Returns:
        The provider, or `None` for an unknown domain.

    Raises:
        ValidationError: If `email` is not an address.

    Example:
        >>> detect_email_provider("user@gmail.com")
        <ImapEmailProvider.GMAIL: ('imap.gmail.com', 993)>
        >>> detect_email_provider("user@example.com") is None
        True
    """
    if not is_email(email):
        msg = f"{email} is not valid email"
        raise ValidationError(msg)

    return ImapEmailProvider.from_domain(email.rsplit("@", maxsplit=1)[-1].lower())


@_optional_import("imap", "bs4")
async def fetch_emails_from(
    email: str,
    password: str,
    provider: ImapEmailProvider,
    sender: str = "noreply@telegram.org",
    limit: int = 10,
    from_old: bool = False,
) -> AsyncIterator[str]:
    r"""Yield the text of the latest emails from one sender in the inbox.

    Args:
        email: The address to log in with.
        password: The password or app password.
        provider: The IMAP server.
        sender: The sender to search for; `"` and `\` are escaped in the query.
        limit: How many of the newest matches to read; 0 or less reads none.
        from_old: Whether to yield oldest first instead of newest first.

    Yields:
        Each message's text, read from the whole message so its MIME parts are
        decoded; nothing when no email matches.

    Raises:
        ValidationError: If `sender` holds a line break, or the server answers a
            search or fetch with an error.
    """
    if "\r" in sender or "\n" in sender:
        msg = f"sender must not contain a line break: {sender!r}"
        raise ValidationError(msg)

    # An IMAP quoted string escapes `\` and `"` with a backslash.
    quoted_sender = sender.replace("\\", "\\\\").replace('"', '\\"')
    client = aioimaplib.IMAP4_SSL(host=provider.host, port=provider.port)

    try:
        await client.wait_hello_from_server()
        await client.login(email, password)
        await client.select("INBOX")

        status, data = await client.search(f'FROM "{quoted_sender}"')

        if status != "OK":
            msg = f"Invalid Email Status {status}"
            raise ValidationError(msg)

        if not data:
            msg = f"Invalid Email data {data}"
            raise ValidationError(msg)

        # A search with no match answers a bare `* SEARCH`, which leaves `data[0]` empty.
        ids = data[0].decode().split()[-limit:] if limit > 0 else []

        if not ids:
            return

        status, messages = await client.fetch(",".join(ids), "BODY.PEEK[]")

        if status != "OK":
            msg = f"Invalid Fetch Email Status {status}"
            raise ValidationError(msg)

        if not isinstance(messages, list):
            msg = f"Invalid Fetch Email data {messages}"
            raise ValidationError(msg)
    finally:
        await safe_await(client.logout())

    # The server returns a header line, the body, and a closing line per message.
    ordered = sorted(
        (
            (int(messages[i].split(b" ")[0].decode()), messages[i + 1])
            for i in range(0, len(messages) - 1, 3)
        ),
        key=lambda item: item[0],
        reverse=not from_old,
    )

    for _, message in ordered:
        yield await to_thread(parse_email_bytes, message)


__all__ = (
    "parse_email_bytes",
    "detect_email_provider",
    "fetch_emails_from",
)
