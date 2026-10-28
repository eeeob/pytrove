from __future__ import annotations as _annotations

import gc
import weakref

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
def test_restricted_proxy_refuses_writes_and_reads_outside_its_lists() -> None:
    box = _Box(3)
    blocked = RestrictedProxy(box, blocked={"n", "m"})
    allowed = RestrictedProxy(box, allowed=["n"])

    with pytest.raises(AttributeError, match="blocked"):
        blocked.n = 1

    with pytest.raises(AttributeError, match="blocked"):
        _ = blocked.m

    with pytest.raises(AttributeError, match="not allowed"):
        _ = allowed.other

    assert box.n == 3


@needs_wrapt
def test_restricted_proxy_refuses_deleting_a_refused_name() -> None:
    box = _Box(3)
    box.other = 1
    blocked = RestrictedProxy(box, blocked="n")
    allowed = RestrictedProxy(box, allowed="other")

    with pytest.raises(AttributeError, match="blocked"):
        del blocked.n

    with pytest.raises(AttributeError, match="not allowed"):
        del allowed.n

    assert box.n == 3
    del allowed.other
    assert not hasattr(box, "other")


@needs_wrapt
def test_restricted_proxy_refuses_dict_whenever_a_list_is_given() -> None:
    box = _Box(3)

    for proxy in (RestrictedProxy(box, blocked="n"), RestrictedProxy(box, allowed="n")):
        with pytest.raises(AttributeError):
            _ = proxy.__dict__

        with pytest.raises(TypeError):
            vars(proxy)

    assert RestrictedProxy(box).__dict__ == {"n": 3}
    assert vars(RestrictedProxy(box, allowed=("n", "__dict__"))) == {"n": 3}


@needs_wrapt
def test_restricted_proxy_still_exposes_wrapped_as_documented() -> None:
    box = _Box(3)
    assert RestrictedProxy(box, blocked="n").__wrapped__ is box


@needs_wrapt
def test_restricted_proxy_keeps_its_own_state_under_self() -> None:
    proxy = RestrictedProxy(_Box(), allowed=[])
    proxy._self_note = 1
    assert proxy._self_note == 1
    del proxy._self_note


@needs_wrapt
def test_restricted_proxy_with_an_empty_allow_list_allows_nothing() -> None:
    proxy = RestrictedProxy(_Box(3), allowed=[])

    with pytest.raises(AttributeError, match="not allowed"):
        _ = proxy.n

    with pytest.raises(AttributeError, match="not allowed"):
        proxy.n = 1


@needs_wrapt
def test_restricted_proxy_with_an_empty_deny_list_allows_everything() -> None:
    box = _Box(3)
    proxy = RestrictedProxy(box, blocked=[])
    assert proxy.n == 3
    assert proxy.__dict__ == {"n": 3}


@needs_wrapt
def test_restricted_proxy_refuses_both_lists() -> None:
    with pytest.raises(ValueError, match="cannot both"):
        RestrictedProxy(_Box(), blocked="a", allowed="b")

    with pytest.raises(ValueError, match="cannot both"):
        RestrictedProxy(_Box(), blocked=[], allowed=["b"])


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


@needs_wrapt
def test_weak_restricted_proxy_calls_back_with_the_dead_proxy() -> None:
    received: list[object] = []
    target = _Box(4)
    weak = WeakRestrictedProxy(target, allowed="n", callback=received.append)
    assert weak.n == 4

    with pytest.raises(AttributeError, match="not allowed"):
        _ = weak.other

    del target
    gc.collect()
    assert len(received) == 1
    assert type(received[0]) is weakref.ProxyType


@pytest.mark.skipif(HAS_WRAPT, reason="the proxy extra is installed")
def test_the_proxies_name_the_proxy_extra_when_wrapt_is_missing() -> None:
    for cls in (RestrictedProxy, WeakRestrictedProxy):
        with pytest.raises(ImportError, match=r"pytrove\[proxy\]"):
            cls(_Box())

        with pytest.raises(ImportError, match=r"pytrove\[proxy\]"):
            isinstance(_Box(), cls)

        with pytest.raises(ImportError, match=r"pytrove\[proxy\]"):
            issubclass(_Box, cls)

        with pytest.raises(ImportError, match=r"pytrove\[proxy\]"):

            class Sub(cls):  # ty: ignore[unsupported-base]  # The stand-in refuses subclassing.
                """Refused."""
