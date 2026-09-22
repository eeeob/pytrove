from __future__ import annotations as _annotations

try:
    from aioimaplib import aioimaplib
except ImportError:
    pass

from .enums import ImapEmailProvider
from .errors import ValidationError

from .validate_tools import is_email
from .async_tools import to_thread, safe_await

from ._optional import _optional_import

import email 
import html

try:
    import bs4
except ImportError:
    pass


@_optional_import(("beautifulsoup4", "bs4"))
def parse_email_bytes(bytes_msg: bytearray, multi_part_sep: str = "\n") -> str:
    msg = email.message_from_bytes(bytes_msg)
    text = ""

    for part in msg.walk():
        if part.get_content_maintype().lower() != "text":
            continue

        if payload := part.get_payload(decode=True):
        
            charset = part.get_content_charset() or "utf-8"

            try:
                content = payload.decode(charset, errors="ignore")
            except:
                content = payload.decode(errors="ignore")

            sub_content_type = part.get_content_subtype().lower()

            if sub_content_type == "html":
                soup = bs4.BeautifulSoup(content, "html.parser")
                content = html.unescape(soup.get_text(separator="\n")).strip()
            else:
                content = content.strip()
            

            if content:
                text += content + multi_part_sep

                
    return text.strip()


def detect_email_provider(email: str) -> ImapEmailProvider | None:
    if not is_email(email):
        raise ValidationError(f"{email} is not valid email")

    return ImapEmailProvider.from_domain(email.split("@")[-1].lower())


@_optional_import(("aioimaplib", "imap"), ("beautifulsoup4", "bs4"))
async def fetch_emails_from(
    email: str, 
    password: str, 
    provider: ImapEmailProvider, 
    sender: str = "noreply@telegram.org", 
    limit: int = 10, 
    from_old: bool = False, 
    ):


    client = aioimaplib.IMAP4_SSL(host=provider.host, port=provider.port)

    await client.wait_hello_from_server()
    await client.login(email, password)
    await client.select("INBOX")

    try:
        status, data = await client.search(f'FROM "{sender}"')

        if status != "OK":
            raise ValidationError("Invalid Email Status %s" % status)
        
        if not data or not data[0]:
            raise ValidationError("Invalid Email data %s" % data)

        status, messages = await client.fetch(",".join(data[0].decode().split()[-limit:]), "BODY.PEEK[TEXT]")

        if status != "OK":
            raise ValidationError("Invalid Fetch Email Status %s" % status)

        if not isinstance(messages, list):
            raise ValidationError("Invalid Fetch Email data %s" % data)
    finally:
        await safe_await(client.logout())
    
    messages = sorted(
        (
            (int(messages[i].split(b' ')[0].decode()), messages[i+1])
            for i in range(0, len(messages) - 1, 3)
        ), 
        key=lambda item: item[0], 
        reverse=not from_old
    )

    for _, message in messages:
        yield await to_thread(
            parse_email_bytes, 
            message, 
        )


__all__ = (
    "parse_email_bytes", 
    "detect_email_provider", 
    "fetch_emails_from", 

)

