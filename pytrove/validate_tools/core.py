"""Type and shape checks, and the `validation` guard."""

from __future__ import annotations as _annotations

import inspect
import sys
from collections.abc import Callable, Mapping
from typing import Any, overload

if sys.version_info >= (3, 13):
    from typing import TypeIs
else:
    from typing import TypeGuard as TypeIs

if sys.version_info >= (3, 11):
    from typing import Never
else:
    from typing_extensions import Never

from ..errors import ValidationError
from ..typings import Container, NestedContainer, _False, _KT, _T, _True, _VT
from ._internal import _ClassInfo, _flatten_class_info, _is_container, _CONTAINER, _NOT_CONTAINER


def is_instance(obj: Any, class_info: _ClassInfo) -> bool:
    """Check `isinstance`, also accepting `typing.Union[...]` anywhere in `class_info`.

    Bare `isinstance` rejects `typing.Union` before Python 3.14.

    Args:
        obj: The value to test.
        class_info: A type, an `X | Y` or `Union[...]`, or a nested tuple of them.

    Returns:
        Whether `obj` is an instance of any type named.
    """
    return isinstance(obj, _flatten_class_info(class_info))


def is_subclass(cls: type, class_info: _ClassInfo) -> bool:
    """Check `issubclass`, also accepting `typing.Union[...]` anywhere in `class_info`.

    Args:
        cls: The class to test.
        class_info: A type, an `X | Y` or `Union[...]`, or a nested tuple of them.

    Returns:
        Whether `cls` is a subclass of any type named.
    """
    return issubclass(cls, _flatten_class_info(class_info))


def is_exception(obj: Any) -> TypeIs[BaseException]:
    """Tell whether `obj` is an exception instance.

    Args:
        obj: The value to test.

    Returns:
        Whether it is a `BaseException`.
    """
    return isinstance(obj, BaseException)


def is_container(obj: Container[_T] | Any) -> TypeIs[Container[_T]]:
    """Tell whether `obj` is a container, which excludes strings, bytes, enums and awaitables.

    Args:
        obj: The value to test.

    Returns:
        Whether it is a `Container` and not a `NotContainer`.
    """
    return _is_container(obj)


def is_mapping(obj: Mapping[_KT, _VT] | Any) -> TypeIs[Mapping[_KT, _VT]]:
    """Tell whether `obj` is a mapping.

    Args:
        obj: The value to test.

    Returns:
        Whether it is a `collections.abc.Mapping`.
    """
    return isinstance(obj, Mapping)


def is_sub_mapping(obj: Any) -> TypeIs[type[Mapping]]:
    """Tell whether `obj` is a mapping class.

    Args:
        obj: The value to test.

    Returns:
        Whether it is a class deriving from `Mapping`.
    """
    return isinstance(obj, type) and issubclass(obj, Mapping)


def is_sub_container(obj: Any) -> TypeIs[type[Container]]:
    """Tell whether `obj` is a container class, in `is_container`'s sense.

    Args:
        obj: The value to test.

    Returns:
        Whether it is a class deriving from a container class and from no `NotContainer` one.
    """
    return isinstance(obj, type) and issubclass(obj, _CONTAINER) and not issubclass(obj, _NOT_CONTAINER)


def iscoroutinefunction_wrapped(f: Callable[..., Any]) -> bool:
    """Check `inspect.iscoroutinefunction`, seeing through `functools.wraps` wrappers.

    A sync wrapper around an async function reads as a plain function to
    `inspect`; this walks the `__wrapped__` chain and stops at the first
    coroutine function it meets.

    Args:
        f: The callable to test.

    Returns:
        Whether `f` or anything it wraps is a coroutine function.
    """
    is_coro = False

    def _stop(func: Callable[..., Any]) -> bool:
        """Record and stop at the first coroutine function in the chain.

        Args:
            func: One callable in the `__wrapped__` chain.

        Returns:
            Whether to stop unwrapping here.
        """
        nonlocal is_coro

        if inspect.iscoroutinefunction(func):
            is_coro = True
            return True

        return False

    unwrapped = inspect.unwrap(f, stop=_stop)
    return is_coro or inspect.iscoroutinefunction(unwrapped)


@overload
def validation(cond: _True, custom_exc: BaseException | str | None = None) -> None: ...
@overload
def validation(cond: _False, custom_exc: BaseException | str | None = None) -> Never: ...
def validation(cond: bool, custom_exc: BaseException | str | None = None) -> None:
    """Raise unless `cond` holds.

    Args:
        cond: The condition that must be true.
        custom_exc: The exception to raise, or a message for a `ValidationError`.

    Raises:
        BaseException: `custom_exc` itself, when it is an exception.
        ValidationError: When `cond` is false and `custom_exc` is a message or `None`.
    """
    if cond:
        return

    if is_exception(custom_exc):
        raise custom_exc from None

    if isinstance(custom_exc, str):
        raise ValidationError(custom_exc)

    raise ValidationError


def all_of(*values: Any) -> bool:
    """Tell whether every value is truthy.

    Args:
        *values: The values to test.

    Returns:
        `all(values)`.
    """
    return all(values)


def any_of(*values: Any) -> bool:
    """Tell whether any value is truthy.

    Args:
        *values: The values to test.

    Returns:
        `any(values)`.
    """
    return any(values)


def all_deep(*values: NestedContainer[Any]) -> bool:
    """Tell whether every leaf is truthy, flattening nested containers; `None` leaves are skipped.

    Args:
        *values: Leaves or containers of them, at any depth.

    Returns:
        Whether every non-`None` leaf is truthy.
    """
    from ..iter_tools import iter_flat_cont

    return all(iter_flat_cont(values))


def any_deep(*values: NestedContainer[Any]) -> bool:
    """Tell whether any leaf is truthy, flattening nested containers; `None` leaves are skipped.

    Args:
        *values: Leaves or containers of them, at any depth.

    Returns:
        Whether any non-`None` leaf is truthy.
    """
    from ..iter_tools import iter_flat_cont

    return any(iter_flat_cont(values))


__all__ = (
    "is_instance",
    "is_subclass",
    "is_exception",
    "is_container",
    "is_mapping",
    "is_sub_mapping",
    "is_sub_container",
    "iscoroutinefunction_wrapped",
    "validation",
    "all_of",
    "any_of",
    "all_deep",
    "any_deep",
)
