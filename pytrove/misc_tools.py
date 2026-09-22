from __future__ import annotations as _annotations

from typing import Any, Callable, Iterator, Type, overload
from .typings import _CT



import inspect
import secrets
import string
import functools


def unwrap_cls(cls: Type) -> int:
    count = 0

    for name in dir(cls):
        method = getattr(cls, name)
        
        if hasattr(method, "__wrapped__"):
            setattr(cls, name, inspect.unwrap(method))
            count += 1
    
    return count


def generate_secret(
    length: int,
    use_upper: bool = True,
    use_lower: bool = True,
    use_digits: bool = True,
    use_symbols: bool = True,
    ) -> str:

    if length <= 0:
        raise ValueError("Password length must be greater than 0")

    pools = []
    guaranteed = []

    if use_lower:
        pools.append(string.ascii_lowercase)
        guaranteed.append(secrets.choice(string.ascii_lowercase))

    if use_upper:
        pools.append(string.ascii_uppercase)
        guaranteed.append(secrets.choice(string.ascii_uppercase))

    if use_digits:
        pools.append(string.digits)
        guaranteed.append(secrets.choice(string.digits))

    if use_symbols:
        pools.append("!@#$%^&*()-_=+[]{};:,.<>?/")
        guaranteed.append(secrets.choice("!@#$%^&*()-_=+[]{};:,.<>?/"))

    if not pools:
        raise ValueError("At least one character set must be enabled")

    all_chars = "".join(pools)

    if length < len(guaranteed):
        raise ValueError("Length too small for selected options")

    password = guaranteed + [
        secrets.choice(all_chars)
        for _ in range(length - len(guaranteed))
    ]

    secrets.SystemRandom().shuffle(password)

    return "".join(password)


def unwrap(obj: Any, with_prop: bool = True) -> Any:
    """Peel `obj` down to the underlying plain function, through `property`,
    `functools.partialmethod`, and `__wrapped__`-chain wrappers (decorators
    using functools.wraps).

    `functools._unwrap_partialmethod` is a private helper (no public
    equivalent exists) that partialmethod itself uses internally to resolve
    `__wrapped__` on a partialmethod object; reused here so `unwrap()`
    handles partialmethod the same way stdlib introspection does.
    """

    if with_prop and isinstance(obj, property):
        obj = obj.fget

    return functools._unwrap_partialmethod(inspect.unwrap(obj))
        
    
def patch_into(
    target: type,
    *,
    patch_key: str = "should_patch",
    preserve_old: bool = True,
    setter: Callable[[type, str, Any], None] = setattr,
    ) -> Callable[[_CT], _CT]:
    """Class decorator: copy every member of the decorated class marked with
    `patch_key` (an attribute set truthy on the member itself, e.g. via a
    separate `@should_patch` marker decorator) onto `target`, monkey-patching
    `target` in place. The decorated class itself is returned unchanged --
    only `target` is mutated.

    Only members explicitly opted in via `patch_key` are copied, unlike
    patch_cls() below which copies the whole class body by default. Members
    are checked through unwrap() so the marker is found even under
    functools.wraps-style decorators wrapping the actual patched callable.

    If `preserve_old`, an existing `target.name` is saved as `target.oldname`
    before being overwritten, so the original implementation stays reachable.
    """

    def apply(current_class: _CT) -> _CT:
        for name, member in current_class.__dict__.items():
            if not getattr(unwrap(member), patch_key, False):
                continue

            if preserve_old:
                if hasattr(target, name):
                    setattr(target, f"old{name}", getattr(target, name))

            setter(target, name, member)

        return current_class

    return apply   


@overload
def patch_cls(patch_class: _CT) -> _CT: ...
@overload
def patch_cls(
    *, 
    preserve_old: bool = True, 
    setter: Callable[[type, str, Any], None] = setattr, 
    include_dunders: tuple[str, ...] = ("__init__",),
    ) -> Callable[[_CT], _CT]: ...
def patch_cls(
    patch_class: _CT | None = None,
    *,
    preserve_old: bool = True,
    setter: Callable[[type, str, Any], None] = setattr,
    include_dunders: tuple[str, ...] = ("__init__",),
    ):
    """Class decorator: monkey-patch the decorated class's single base with
    every member of the decorated class's own body, then return the base
    (not the decorated class) -- so `patch_class` only ever exists to stage
    the patch and is discarded afterward.

    Unlike patch_into() above, this copies the *entire* class body by
    default, not just members marked for it -- dunder methods are the
    exception, skipped unless explicitly named in `include_dunders`, since
    copying e.g. `__eq__`/`__repr__` unintentionally is rarely what's wanted.
    Requiring exactly one non-`object` base is what makes "the base" well
    defined; multiple bases would leave no single unambiguous patch target.
    """

    def _apply(patch_class: type):
        bases = [b for b in patch_class.__bases__ if b is not object]

        if len(bases) != 1:
            raise TypeError(
                f"{patch_class.__name__} must inherit from exactly one base, "
                f"got {[b.__name__ for b in bases]}"
            )

        target = bases[0]

        for name, member in patch_class.__dict__.items():
            if name.startswith("__") and name.endswith("__"):
                if name not in include_dunders:
                    continue

            if preserve_old:
                if hasattr(target, name):
                    setattr(target, f"old{name}", getattr(target, name))

            setter(target, name, member)

        return target

    
    if patch_class is not None:
        return _apply(patch_class)

    return _apply


def walk_subclasses(cls: Type, include_base: bool = False) -> Iterator[Type]:
    if include_base:
        yield cls

    for sub in cls.__subclasses__():
        yield from walk_subclasses(sub, include_base=True)


__all__ = (
    "unwrap_cls", 
    "generate_secret", 
    "unwrap", 
    "patch_into", 
    "patch_cls", 
    "walk_subclasses", 

    
)