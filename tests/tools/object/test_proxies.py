from __future__ import annotations as _annotations

import gc

import pytest

from pytrove.object_tools import RestrictedProxy, WeakRestrictedProxy
from pytrove.object_tools.proxies import HAS_WRAPT

needs_wrapt = pytest.mark.skipif(not HAS_WRAPT, reason="needs the proxy extra")


class _Box:
    """A weak-referenceable value."""

    def __init__(self, n: int = 0) -> None:
        """Store `n`."""
        self.n = n


@needs_wrapt
def test_restricted_proxy_blocks_or_allows_named_attributes() -> None:
    box = _Box(3)
    blocked = RestrictedProxy(box, blocked="n")
    allowed = RestrictedProxy(box, allowed=["n"])
    assert allowed.n == 3
    assert blocked.__class__ is _Box
    assert isinstance(blocked, _Box)

    with pytest.raises(AttributeError, match="blocked"):
        _ = blocked.n

    with pytest.raises(AttributeError, match="not allowed"):
        allowed.other = 1

    allowed.n = 5
    assert box.n == 5

    blocked.other = 2
    assert box.other == 2


@needs_wrapt
def test_restricted_proxy_refuses_both_lists() -> None:
    with pytest.raises(ValueError, match="cannot both"):
        RestrictedProxy(_Box(), blocked="a", allowed="b")


@needs_wrapt
def test_weak_restricted_proxy_does_not_keep_its_target_alive() -> None:
    collected: list[object] = []
    target = _Box(4)
    weak = WeakRestrictedProxy(target, blocked="secret", callback=collected.append)
    assert weak.n == 4

    with pytest.raises(AttributeError, match="blocked"):
        _ = weak.secret

    del target
    gc.collect()
    assert len(collected) == 1

    with pytest.raises(ReferenceError):
        _ = weak.n


@pytest.mark.skipif(HAS_WRAPT, reason="the proxy extra is installed")
def test_the_proxies_name_the_proxy_extra_when_wrapt_is_missing() -> None:
    for cls in (RestrictedProxy, WeakRestrictedProxy):
        with pytest.raises(ImportError, match=r"pytrove\[proxy\]"):
            cls(_Box())
