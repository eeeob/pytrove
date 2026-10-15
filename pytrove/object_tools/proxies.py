"""Proxies that hand an object out without handing out all of it."""

from __future__ import annotations as _annotations

import weakref
from collections.abc import Callable
from typing import Any

try:
    import wrapt
except ImportError:
    HAS_WRAPT = False
else:
    HAS_WRAPT = True

from .._internal._optional import _unavailable_class
from ..iter_tools import to_frozenset
from ..typings import MaybeContainer, _T

if HAS_WRAPT:

    class RestrictedProxy(wrapt.ObjectProxy):
        """A transparent proxy that refuses named attributes, by deny-list or allow-list.

        Built on `wrapt.ObjectProxy`, so dunders, `isinstance` and operators pass
        through. The proxy's own state lives under wrapt's `_self_` prefix.
        """

        def __init__(
            self, obj: Any, blocked: MaybeContainer[str] | None = None, allowed: MaybeContainer[str] | None = None,
        ) -> None:
            """Wrap `obj`.

            Args:
                obj: The object.
                blocked: Attributes to refuse; everything else passes.
                allowed: The only attributes to allow.

            Raises:
                ValueError: If both lists are given.
            """
            blocked = to_frozenset(blocked)
            allowed = to_frozenset(allowed)

            if blocked and allowed:
                msg = "blocked and allowed cannot both be provided"
                raise ValueError(msg)

            super().__init__(obj)
            self._self_blocked = blocked
            self._self_allowed = allowed or None

        def _check(self, name: str) -> None:
            """Refuse a name the lists do not allow.

            Args:
                name: The attribute.

            Raises:
                AttributeError: If it is blocked or not allowed.
            """
            if self._self_allowed is not None:
                if name not in self._self_allowed:
                    msg = f"Attribute '{name}' is not allowed"
                    raise AttributeError(msg)
            elif name in self._self_blocked:
                msg = f"Attribute '{name}' is blocked"
                raise AttributeError(msg)

        def __getattr__(self, name: str) -> Any:
            """Read an attribute of the wrapped object, if allowed.

            Args:
                name: The attribute.

            Returns:
                Its value.
            """
            self._check(name)
            return super().__getattr__(name)

        def __setattr__(self, name: str, value: Any) -> None:
            """Set an attribute on the wrapped object, if allowed; `_self_` names are the proxy's own.

            Args:
                name: The attribute.
                value: Its value.
            """
            if not name.startswith("_self_"):
                self._check(name)

            super().__setattr__(name, value)

    class WeakRestrictedProxy(RestrictedProxy):
        """A `RestrictedProxy` over a weak reference, so it never keeps its target alive."""

        def __init__(
            self,
            obj: _T,
            blocked: MaybeContainer[str] | None = None,
            allowed: MaybeContainer[str] | None = None,
            callback: Callable[[_T], Any] | None = None,
        ) -> None:
            """Wrap a weak proxy of `obj`.

            Args:
                obj: The object.
                blocked: Attributes to refuse.
                allowed: The only attributes to allow.
                callback: Called when `obj` is collected.
            """
            super().__init__(weakref.proxy(obj, callback), blocked, allowed)

else:
    RestrictedProxy = _unavailable_class("RestrictedProxy", ("wrapt", "proxy"))
    WeakRestrictedProxy = _unavailable_class("WeakRestrictedProxy", ("wrapt", "proxy"))

__all__ = (
    "RestrictedProxy",
    "WeakRestrictedProxy",
)
