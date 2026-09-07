
from typing import (
    Any, Union, Optional,
    Mapping, Type, TypeAlias,
    Tuple, 
    overload, get_args, get_origin,
)

from types import UnionType

import sys

if sys.version_info >= (3, 13):
    from typing import TypeIs
else:
    from typing import TypeGuard as TypeIs

try:
    from typing import Never
except ImportError:  # Python < 3.11
    from typing_extensions import Never

try:
    from typeguard import (
        check_type, check_type_internal,
        checker_lookup_functions,
        TypeCheckMemo, TypeCheckError,
        CollectionCheckStrategy,
    )
except ImportError:
    HAS_TYPEGUARD = False
else:
    HAS_TYPEGUARD = True

from enum import EnumMeta as EnumType, Enum  # EnumType is only an alias for EnumMeta added in 3.11

try:
    from aioimaplib import aioimaplib
except ImportError:
    pass

try:
    from pyrogram import Client
    from pyrogram.utils import get_peer_type
    from pyrogram.types import Message
    from pyrogram.errors import BadRequest
except ImportError:
    pass



from .typings import (
    Container, NotContainer, NestedContainer, 
    StrInt, _True, _False, 
    _T, _KT, _VT, 
)
from .errors import ValidationError

from ._optional import _optional_import

try:
    import phonenumbers
except ImportError:
    pass

import re
import inspect
import logging


try:
    TG_CHANNEL_MSG_LINK_PATTERN = Client.CHANNEL_MESSAGE_LINK_RE
except (NameError, AttributeError):
    TG_CHANNEL_MSG_LINK_PATTERN = re.compile(r"^(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.(?:org|me|dog)/(?:c/)?)([\w]+)(?:/\d+)*/(\d+)/?$")



TG_BOT_COMMAND_PATTERN = re.compile(r"^/[A-Za-z][\w\d]*$")
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

_CONTAINER = tuple(get_origin(arg) or arg for arg in get_args(getattr(Container, "__value__", Container)))
_NOT_CONTAINER = tuple(get_origin(arg) or arg for arg in get_args(getattr(NotContainer, "__value__", NotContainer)))


_ClassInfo: TypeAlias = Union[type, UnionType, Tuple["_ClassInfo", ...]]

log = logging.getLogger(__name__)

def _flatten_class_info(class_info: _ClassInfo) -> Tuple[type, ...]:
    """Normalize `class_info` into the plain tuple-of-types form isinstance()/
    issubclass() have always accepted on every supported version.

    `X | Y` (types.UnionType) is already accepted directly by isinstance()/
    issubclass() on every version this package targets (3.10+), so it isn't
    the problem -- typing.Union[X, Y] is (see the comment above), and that's
    what get_origin()/get_args() unwrap here. Tuples are flattened
    recursively so a tuple mixing plain types, `X | Y`, and `Union[...]`
    members (nested arbitrarily) all resolve the same way.
    """

    if isinstance(class_info, tuple):
        flattened = set()

        for c in class_info:
            flattened.update(_flatten_class_info(c))

        return tuple(flattened)

    origin = get_origin(class_info)

    if origin is Union or origin is UnionType:
        return _flatten_class_info(get_args(class_info))

    return (class_info,)

def is_instance(obj: Any, class_info: _ClassInfo) -> bool:
    """Like isinstance(), but `class_info` may also be (or contain, nested
    inside a tuple) a typing.Union[...] -- which bare isinstance() rejects
    with TypeError on Python < 3.14. `X | Y` already works with isinstance()
    on every version this package supports, so it needs no special handling,
    but is accepted here too for a uniform call site.
    """

    return isinstance(obj, _flatten_class_info(class_info))

def is_subclass(cls: type, class_info: _ClassInfo) -> bool:
    """The issubclass() counterpart of is_instance() -- see its docstring."""

    return issubclass(cls, _flatten_class_info(class_info))


def is_exception(obj: Any) -> TypeIs[BaseException]:
    return isinstance(obj, BaseException)

def is_container(obj: Union['Container[_T]', Any]) -> TypeIs['Container[_T]']:
    return isinstance(obj, _CONTAINER) and not isinstance(obj, _NOT_CONTAINER)

def is_mapping(obj: Union[Mapping[_KT, _VT], Any]) -> TypeIs[Mapping[_KT, _VT]]:
    return isinstance(obj, Mapping)

def is_sub_mapping(obj: Any) -> TypeIs[Type[Mapping]]:
    return isinstance(obj, type) and issubclass(obj, Mapping)

def is_sub_container(obj: Any) -> TypeIs[Type[Container]]:
    return isinstance(obj, type) and issubclass(obj, _CONTAINER) and not issubclass(obj, _NOT_CONTAINER)

@_optional_import(("kurigram", "tg"))
def is_tg_channel_id(value: Any) -> TypeIs[int]:
    try:
        return isinstance(value, int) and get_peer_type(value) == "channel"
    except ValueError:
        return False
    
@_optional_import(("kurigram", "tg"))
def is_tg_user_id(value: Any) -> TypeIs[int]:
    try:
        return isinstance(value, int) and get_peer_type(value) == "user"
    except ValueError:
        return False

def is_tg_bot_token(bot_token: Any) -> TypeIs[str]:
    if not isinstance(bot_token, str) or ":" not in bot_token:
        return False

    parts = bot_token.split(":")

    return (
        len(parts) == 2
        and parts[0].isdecimal()
    )

@_optional_import(("kurigram", "tg"))
def is_tg_bot_command(message: Union["Message", str]) -> TypeIs[str]:
    if isinstance(message, Message):
        message = message.text or ""

    return (
        isinstance(message, str)
        and bool(message)
        and bool(TG_BOT_COMMAND_PATTERN.match(message))
    )

def is_tg_channel_message_link(message_link: Any) -> TypeIs[str]:
    return (
        isinstance(message_link, str)
        and bool(TG_CHANNEL_MSG_LINK_PATTERN.match(message_link.lower()))
    )

@overload
def is_tg_otp_code(code: Any, with_str: _True = True, remove_spaces: bool = False) -> TypeIs[StrInt]: ...
@overload
def is_tg_otp_code(code: Any, with_str: _False) -> TypeIs[int]: ...
def is_tg_otp_code(code, with_str = True, remove_spaces = False):
    if isinstance(code, int):
        return len(str(code)) == 5
    elif isinstance(code, str):
        if with_str:
            if remove_spaces:
                from .text_tools import clean_spaces
                code = clean_spaces(code)
            from .num_tools import to_int
            return len(code) == 5 and isinstance(to_int(code, False), int)
    
    return False

@_optional_import(("phonenumbers", "phone"))
def is_phone_number(
    phone_number: Union[StrInt, "phonenumbers.PhoneNumber"], 
    remove_spaces: bool = True, 
    resolve: bool = True
    ) -> TypeIs[StrInt]:

    if isinstance(phone_number, phonenumbers.PhoneNumber):
        parsed_number = phone_number

    elif isinstance(phone_number, (int, str)):
        phone_number = str(phone_number)
        
        if remove_spaces:
            from .text_tools import clean_spaces
            phone_number = clean_spaces(phone_number)
        
        if resolve:
            if phone_number.startswith("00"):
                phone_number = phone_number[2:]

            if not phone_number.startswith("+"):
                phone_number = "+" + phone_number
        
        try:
            parsed_number = phonenumbers.parse(phone_number)
        except Exception:
            return False
    else:
        return False
    
    try:
        return (
            phonenumbers.is_possible_number(parsed_number) 
            and phonenumbers.is_valid_number(parsed_number)
        )
    except Exception:
        return False

@_optional_import(("phonenumbers", "phone"))
def is_rc(rc: Any) -> TypeIs[str]:
    return isinstance(rc, str) \
    and rc.isalpha() and len(rc) == 2 \
    and rc.lower() != "zz" \
    and phonenumbers.country_code_for_region(rc.upper()) != 0
    
def is_email(email: Any) -> TypeIs[str]:
    return isinstance(email, str) \
    and bool(EMAIL_PATTERN.fullmatch(email))

def iscoroutinefunction_wrapped(f):
    """Like inspect.iscoroutinefunction(), but also sees through wrappers.

    inspect.iscoroutinefunction() only inspects `f` itself, so a sync def
    wrapping an async function (e.g. functools.wraps-style decorators that
    don't forward the coroutine-ness of the wrapped callable) reads as a
    plain function. inspect.unwrap() walks the `__wrapped__` chain instead;
    `_stop` is its stop-condition callback, called on every object in that
    chain -- as soon as one of them is itself a coroutine function, it
    records that and tells unwrap() to stop early there.
    """

    is_coro = False

    def _stop(func):
        nonlocal is_coro

        if inspect.iscoroutinefunction(func):
            is_coro = True
            return True
        
        return False

    unwrapped = inspect.unwrap(f, stop=_stop)
    return is_coro or inspect.iscoroutinefunction(unwrapped)

@_optional_import(("kurigram", "tg"))
async def is_valid_tg_app(api_id: StrInt, api_hash: str) -> bool:
    """Whether `api_id`/`api_hash` actually work, by trying to connect with
    them -- the only way to know for certain, since Telegram is the one
    party that can say so.

    Only BadRequest -- Telegram's own family for a rejected request, which
    is what a wrong or banned pair comes back as -- is read as "no".
    Anything else (no network, a timeout, Telegram itself being down) is a
    failure to find out, not an answer, and is left to propagate rather
    than being reported as an invalid pair.
    """

    try:
        api_id = int(api_id)
    except (TypeError, ValueError):
        return False
    
    c = Client(f"check_session_{api_id}", api_id=api_id, api_hash=api_hash, in_memory=True, no_updates=True)

    try:
        await c.connect()
    except BadRequest:
        return False
    else:
        return True
    finally:
        try:
            await c.disconnect()
        except Exception:
            log.exception("Failed to disconnect the Telegram client")

@_optional_import(("aioimaplib", "imap"))
async def is_accessible_received_email(email: str, password: str):
    from .email_tools import detect_email_provider

    provider = detect_email_provider(email)

    if provider is None:
        return False

    c = aioimaplib.IMAP4_SSL(host=provider.host, port=provider.port)

    try:
        await c.wait_hello_from_server()
        await c.login(email, password)
    except Exception:
        return False
    else:
        return True
    finally:
        try:
            await c.logout()
        except Exception:
            log.exception("Failed to log out from the IMAP server")
    
@overload
def validation(cond: _True, custom_exc: Optional[Union[BaseException, str]] = None) -> None: ...
@overload
def validation(cond: _False, custom_exc: Optional[Union[BaseException, str]] = None) -> Never: ...
def validation(cond: bool, custom_exc = None):
    if not cond:
        if is_exception(custom_exc):
            raise custom_exc from None
        elif isinstance(custom_exc, str):
            raise ValidationError(custom_exc)
        raise ValidationError

def all_of(*values: Any) -> bool:
    return all(values)
def any_of(*values: Any) -> bool:
    return any(values)

def all_deep(*values: NestedContainer[Any]) -> bool:
    from .iter_tools import iter_flat_cont
    return all(iter_flat_cont(values))
def any_deep(*values: NestedContainer[Any]) -> bool:
    from .iter_tools import iter_flat_cont
    return any(iter_flat_cont(values))



@_optional_import(("typeguard", "typecheck"))
def checker_lookup(origin_type: Any, *_):
    """typeguard checker_lookup_functions hook (registered at import time,
    below), giving check_type()/validate_type() two behaviors typeguard
    doesn't have out of the box:

        - checking a value against an Enum class succeeds for any of that
        enum's *values*, not just its members -- `check_type(1, SomeIntEnum)`
        passes if `SomeIntEnum(1)` is valid, without requiring the caller to
        already hold an enum member;
        - checking a value against this package's own `Container` type (e.g.
        `NestedContainer[int]`) recurses into it and validates every element
        against the type argument, since typeguard has no built-in notion of
        this project's Container union.

    typeguard calls every registered lookup with the type being checked and
    returns the first non-None validator; returning None here means "not one
    of ours, let typeguard's own lookups handle it".
    """

    def validate_enum(value, origin_type: EnumType, *_):
        try:
            origin_type(value)
        except (ValueError, TypeError) as exc:
            raise TypeCheckError(str(exc)) from exc

    def validate_container(value, origin_type, args: Tuple[Any], memo: TypeCheckMemo, *_):
        if not is_container(value):
            raise TypeCheckError("is not container")

        if not args or args == (Any,):
            return

        samples = memo.config.collection_check_strategy.iterate_samples(value)

        for i, v in enumerate(samples):
            try:
                check_type_internal(v, args[0], memo)
            except TypeCheckError as exc:
                exc.append_path_element(f"item {i}")
                raise

    if isinstance(origin_type, type) and issubclass(origin_type, Enum):
        return validate_enum

    if is_sub_container(origin_type):
        return validate_container

@_optional_import(("typeguard", "typecheck"))
def validate_type(value: Any, annotation: Any) -> None:
    try:
        return check_type(
            value, annotation,
            typecheck_fail_callback=None,
            collection_check_strategy=CollectionCheckStrategy.ALL_ITEMS
            )
    except TypeCheckError as exc:
        raise ValidationError(str(exc)) from exc


if HAS_TYPEGUARD:
    checker_lookup_functions.append(checker_lookup)







    

__all__ = (
    "is_exception",
    "is_container",
    "is_tg_channel_id",
    "is_tg_user_id",
    "is_tg_bot_token",
    "is_tg_bot_command",
    "is_tg_channel_message_link",
    "is_mapping", 
    "is_tg_otp_code", 
    "is_phone_number", 
    "is_rc", 
    "is_email", 
    "validation", 
    "all_of",
    "any_of",
    "all_deep",
    "any_deep", 
    "is_valid_tg_app", 
    "is_accessible_received_email", 
    "is_sub_mapping", 
    "is_sub_container", 
    "validate_type",
    "iscoroutinefunction_wrapped",
    "is_instance",
    "is_subclass",

)