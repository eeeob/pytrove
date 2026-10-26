"""Proxies that hand an object out without handing out all of it."""

from __future__ import annotations as _annotations

import weakref
from typing import TYPE_CHECKING, Any

try:
    import wrapt  # type: ignore[import-not-found]  # Optional: the `proxy` extra.
except ImportError:
    HAS_WRAPT = False
else:
    HAS_WRAPT = True

from .._internal import _has_requirement, _unavailable_class
from ..iter_tools import to_frozenset

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..typings import MaybeContainer, _T

# Importable is not enough: a release older than the extra allows may be installed outside it.
HAS_WRAPT = HAS_WRAPT and _has_requirement("proxy", "wrapt")

if HAS_WRAPT:

    class RestrictedProxy(wrapt.ObjectProxy):
        """A transparent proxy that refuses named attributes, by deny-list or allow-list.

        Built on `wrapt.ObjectProxy`, so dunders, `isinstance` and operators pass
        through. The proxy's own state lives under wrapt's `_self_` prefix.

        Reading, setting and deleting a refused name all raise `AttributeError`.
        So does reading `__dict__` (and `vars(proxy)` raises `TypeError`) whenever
        a list is given, since it would show a refused name too; an allow-list may
        name `__dict__` to let it through. An empty allow-list allows nothing.

        It guards against mistakes, not against hostile code: Python has no
        private attributes, and `proxy.__wrapped__` still returns the target,
        since wrapt and `inspect.unwrap` rely on it.
        """

        def __init__(
            self,
            obj: Any,
            blocked: MaybeContainer[str] | None = None,
            allowed: MaybeContainer[str] | None = None,
        ) -> None:
            """Wrap `obj`.

            Args:
                obj: The object.
                blocked: Attributes to refuse; everything else passes.
                allowed: The only attributes to allow.

            Raises:
                ValueError: If both lists are given, even empty.
            """
            if blocked is not None and allowed is not None:
                msg = "blocked and allowed cannot both be provided"
                raise ValueError(msg)

            super().__init__(obj)
            self._self_blocked = to_frozenset(blocked)
            self._self_allowed = None if allowed is None else to_frozenset(allowed)

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
            # `__dict__` holds every attribute, so a deny-list refuses it as a whole.
            elif name in self._self_blocked or (name == "__dict__" and self._self_blocked):
                msg = f"Attribute '{name}' is blocked"
                raise AttributeError(msg)

        @property
        def __dict__(self) -> dict[str, Any]:
            """The target's `__dict__`, if the lists let it through."""
            self._check("__dict__")
            return self.__wrapped__.__dict__

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

        def __delattr__(self, name: str) -> None:
            """Delete an attribute of the wrapped object, if allowed; `_self_` names are the proxy's own.

            Args:
                name: The attribute.
            """
            if not name.startswith("_self_"):
                self._check(name)

            super().__delattr__(name)

    class WeakRestrictedProxy(RestrictedProxy):
        """A `RestrictedProxy` over a weak reference, so it never keeps its target alive."""

        def __init__(
            self,
            obj: _T,
            blocked: MaybeContainer[str] | None = None,
            allowed: MaybeContainer[str] | None = None,
            callback: Callable[[Any], Any] | None = None,
        ) -> None:
            """Wrap a weak proxy of `obj`.

            Args:
                obj: The object.
                blocked: Attributes to refuse.
                allowed: The only attributes to allow.
                callback: Called when `obj` is collected, with the now dead weak
                    proxy (`weakref.proxy` passes it), not with `obj`.
            """
            super().__init__(weakref.proxy(obj, callback), blocked, allowed)

else:
    RestrictedProxy = _unavailable_class("RestrictedProxy", "proxy")
    WeakRestrictedProxy = _unavailable_class("WeakRestrictedProxy", "proxy")

__all__ = (
    "RestrictedProxy",
    "WeakRestrictedProxy",
)
