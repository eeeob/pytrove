from typing import Union, Tuple, Optional, List, Dict, Final, overload
from pathlib import Path

try:
    from pyrogram.types.user_and_chats.user import Link
    from pyrogram import Client as PyroClient
    from pyrogram.enums import ParseMode
    from pyrogram.types import CallbackQuery as Query, Message, User, Chat
    from pyrogram.utils import get_channel_id
except ImportError:
    pass

from .typings import _T, _True, _False, StrInt
from .errors import ValidationError
from .enums import TgMessageLength, PlatformDevice

from ._devices import (
    AndroidDevice, 
    iOSDeivce, 
    WindowsDevice, 
    LinuxDevice, 
    macOSDevice, 
    DeviceInfo
)

from .validate_tools import is_tg_user_id
from .num_tools import to_int
from .text_tools import to_str, clean_spaces
from .date_tools import date_to_stamp, time_utc
from .files_tools import load_json
from .iter_tools import flat_cont
from .email_tools import fetch_emails_from, detect_email_provider

from ._optional import _optional_import


import random
import re

_POINTS: Optional[Tuple[Tuple[int, float]]] = None

_DEVICES: Final[Dict[PlatformDevice, Union[AndroidDevice, Tuple[AndroidDevice, ...]]]] = {
    PlatformDevice.ANDROID: AndroidDevice, 
    PlatformDevice.IOS: iOSDeivce, 
    PlatformDevice.DESKTOP: (WindowsDevice, LinuxDevice, macOSDevice)
}
_FLATTED_DEVICES = flat_cont(_DEVICES.values())


try:
    CHAT_LINK_PATTERN = PyroClient.CHAT_LINK_PATTERN
except (NameError, AttributeError):
    CHAT_LINK_PATTERN = re.compile(r"^(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.(?:org|me|dog)/(?:c/)?)([\w]+)(?:.+)?$")
try:
    INVITE_LINK_PATTERN = PyroClient.INVITE_LINK_PATTERN
except (NameError, AttributeError):
    INVITE_LINK_PATTERN = re.compile(r"^(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.(?:org|me|dog)/(?:joinchat/|\+))([\w-]+)$")
    

def _build_points():
    global _POINTS

    if _POINTS is None:
        _POINTS = tuple(
            (uid, date_to_stamp(date, format="%Y-%m-%d")) 
            for uid, date in load_json(Path(__file__).parent / "data" / "tg_points.json")
        )

@_optional_import(("kurigram", "tg"))
def extract_pyro_update_text(update: Union["Message", "Query"]) -> str:
    if isinstance(update, Message):
        txt = update.text or update.caption or ""
    elif isinstance(update, Query):
        txt = update.data or ""
    else:
        raise ValidationError(f"extract_pyro_update_text doesn't work with {type(update)}")
    
    return txt


@overload
def format_tg_username(
    target: Union[str, "Chat", "User"], 
    with_invite_link: bool = False, 
    with_at: bool = True, 
    ) -> Optional[str]: ...
@overload
def format_tg_username(
    target: Union[str, "Chat", "User"], 
    with_invite_link: bool = False, 
    with_at: bool = True, 
    default: _T = ...
    ) -> Union[str, _T]: ...
@_optional_import(("kurigram", "tg"))
def format_tg_username(
    target: Union[str, "Chat", "User"], 
    with_invite_link: bool = False, 
    with_at: bool = True, 
    default = None
    ):


    if isinstance(target, (User, Chat)):
        target = target.username
    
    if not target:
        return default

    match = CHAT_LINK_PATTERN.match(target.lower())
    
    if not match and INVITE_LINK_PATTERN.match(target.lower()):
        return target if with_invite_link else default
    
    target = (match.group(1) if match else target.replace("@", "")).strip()

    if with_at:
        target = "@" + target
    
    return target
    
@overload
def format_tg_link(
    target: Union[StrInt, "Message", "Chat", "User"], 
    ) -> Optional[str]: ...
@overload
def format_tg_link(
    target: Union[StrInt, "Message", "Chat", "User"], 
    default: _T
    ) -> Union[str, _T]: ...
@_optional_import(("kurigram", "tg"))
def format_tg_link(
    target: Union[StrInt, "Message", "Chat", "User"], 
    default = None
    ):

    if isinstance(target, Message):
        return target.link
    
    if isinstance(target, (User, Chat)):
        target = target.username or getattr(target, "invite_link", None) or target.id
    
    if not target:
        return default
    
    target = to_str(target)
    match = CHAT_LINK_PATTERN.match(target.lower())
    
    if not match and INVITE_LINK_PATTERN.match(target):
        return target
    
    target = to_int((match.group(1) if match else target.replace("@", "")).strip())
    
    if isinstance(target, int):
        target = (
            f"tg://openmessage?user_id={target}" 
            if is_tg_user_id(target) else 
            f"tg://openmessage?chat_id={get_channel_id(target)}" 
        )
    else:
        target = f"https://t.me/{target}"
    
    return target

@_optional_import(("kurigram", "tg"))
def parse_tg_target(target: StrInt) -> StrInt:
    """A chat/user target -- an id already, a phone number, a t.me channel-
    message link or a bare/@-prefixed username -- read down to what
    Pyrogram's own methods (get_chat, send_message, ...) actually take: an
    int wherever the target names one, a string otherwise.

    An int is returned as it is; nothing here needs to guess what it
    names. Anything else is read in this order:

      a phone number, once "+", "()", "-" and whitespace are stripped, is
      the digits alone, as an int -- +967 (777) 123-456 and 967777123456
      both resolve the same way.

      a t.me channel-message link (CHAT_LINK_PATTERN, what format_tg_link
      and format_tg_username already match against) gives up the id in
      it, converted through get_channel_id -- the same call format_tg_link
      makes going the other way -- since a bare id parsed out of a link is
      not yet the internal chat id Pyrogram expects. A capture that is not
      itself numeric (a channel's public part, not its id) is returned as
      the string it is instead of being forced through int().

      an invite link (INVITE_LINK_PATTERN) is returned untouched -- there
      is no id to read out of one, an invite hash is not a username.

      anything else is a username, stripped of "@", "+" and whitespace and
      lowercased, exactly what format_tg_username builds back into one.
    """

    if isinstance(target, int):
        return target

    target = clean_spaces(target)
    phone = re.sub(r"[+()\s-]", "", target)

    if phone.isdigit():
        return int(phone)

    match = CHAT_LINK_PATTERN.match(target.lower())

    if not match:
        if INVITE_LINK_PATTERN.match(target):
            return target
        return re.sub(r"[@+\s]", "", target.lower())

    try:
        return get_channel_id(int(match.group(1)))
    except ValueError:
        return match.group(1)

@_optional_import(("kurigram", "tg"))
def format_hidden_tg_link(
    url: str, 
    text: str, 
    parse_mode: Optional["ParseMode"] = None
    ) -> str:

    # Add hidden text because some Telegram clients hide or remove short links.
    # When that happens, the real text does not appear, so we slightly extend the
    # text to keep the links visible and effective in the message without changing
    # the actual link itself.
    if len(text) <= 3:
        text += "⁪⁬⁪⁬⁮⁪⁬⁪⁬⁮⁪⁬⁪⁬⁮⁪⁬⁪⁬⁮⁪⁬⁪⁬⁮⁪⁬⁪⁬⁮⁪⁬⁪⁬⁮⁪⁬⁪⁬⁮⁪⁬⁪⁬⁮⁪⁬⁪⁬⁮⁪⁬⁪⁬⁮⁪⁬⁪⁬⁮ ⁪⁬⁪⁬⁮⁪⁬⁪⁬⁮ ⁪⁬"

    if parse_mode is None:
        parse_mode = ParseMode.HTML

    return Link(
        url, text, parse_mode
    )()

@_optional_import(("kurigram", "tg"))
def mention_tg_user(
    user_id: int, 
    user_full_name: Optional[str] = None, 
    parse_mode: Optional["ParseMode"] = None
    ) -> str:

    if user_full_name is None:
        user_full_name = "Deleted Account"

    return format_hidden_tg_link(
        f"tg://user?id={user_id}", 
        user_full_name, 
        parse_mode
    )

def split_tg_message(
    text: str, 
    length: int = TgMessageLength.TEXT, 
    reverse: bool = False, 
    ) -> List[str]:

    text = text.strip()

    if len(text) <= length:
        return [text]
    
    lines = text.splitlines(True)

    if reverse:
        lines = reversed(lines)

    messages: List[str] = []
    current = ""

    for line in lines:
        if len(current) + len(line) <= length:
            current = (line + current) if reverse else (current + line)
        else:
            if current:
                messages.append(current)
            
            current = line

            while len(current) > length:
                if reverse:
                    messages.append(current[-length:])
                    current = current[:-length]
                else:
                    messages.append(current[:length])
                    current = current[length:]

    if current:
        messages.append(current)
    
    return [m.strip() for m in messages if m.strip()]


@overload
def rand_tg_device(platform_device: Optional[PlatformDevice] = ..., to_tuple: _False = False) -> DeviceInfo: ...
@overload
def rand_tg_device(platform_device: Optional[PlatformDevice] = ..., *, to_tuple: _True) -> Tuple[str, str]: ...
def rand_tg_device(platform_device: Optional[PlatformDevice] = None, to_tuple: bool = False):
    device = (
        _DEVICES[platform_device] 
        if platform_device is not None 
        else random.choice(_FLATTED_DEVICES)
        ).RandomDevice()

    if to_tuple:
        device = device.model, device.version
    
    return device
    

def _interpolate_time(
    uid: int, 
    id1: int, t1: float, 
    id2: int, t2: float
    ):

    if id1 == id2:
        return t1

    ratio = (uid - id1) / (id2 - id1)
    ts = t1 + (t2 - t1) * ratio

    return min(ts, time_utc())

def tg_account_created_at(user_id: int):
    _build_points()
    
    points = _POINTS
    
    if user_id <= points[0][0]:
        return points[0][1]

    for i in range(len(points)-1):
        id1, t1 = points[i]
        id2, t2 = points[i+1]

        if id1 <= user_id <= id2:
            return _interpolate_time(user_id, id1, t1, id2, t2)

    return _interpolate_time(user_id, *points[-2], *points[-1])


@_optional_import(("aioimaplib", "imap"), ("beautifulsoup4", "bs4"))
async def fetch_tg_email_code(
    email: str, 
    password: str, 
    full_name: str, 
    code_length: int
    ):

    code_pattern = re.compile(fr"\b\d{code_length}\b")

    async for message in fetch_emails_from(email, password, detect_email_provider(email)):
        match = code_pattern.search(message)

        if match and full_name in message:
            return match.group()




__all__ = (
    "extract_pyro_update_text", 
    "format_tg_username",
    "format_tg_link",
    "parse_tg_target",
    "format_hidden_tg_link",
    "mention_tg_user", 
    "split_tg_message", 
    "rand_tg_device", 
    "tg_account_created_at", 
    "fetch_tg_email_code", 


)
