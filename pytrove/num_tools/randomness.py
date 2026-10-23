"""Drawing random values around a target."""

from __future__ import annotations as _annotations

import random

from .._internal import _tri_cdf, _tri_icdf


def jitter(
    value: float,
    decrease: float,
    increase: float,
    bias: float = 0.5,
    previous: float | None = None,
    min_distance: float = 0.0,
    *,
    rng: random.Random | None = None,
) -> float:
    """Draw a random value near `value`, from a triangular shape over a window around it.

    The window is `[value * (1 - decrease), value * (1 + increase)]`, its ends
    ordered first so a negative `value` works. `previous` and `min_distance`
    cut the band `previous ± min_distance` out of it, and the draw comes from
    what is left by inverse transform, never by retrying. If the band covers
    the whole window, the end furthest from `previous` is returned. Repeated
    calls are independent draws that cluster near the peak; use `Jitter` for
    a sequence that spreads.

    Changed after 1.1.2: this replaces `jitter(base, minus=2, plus=2)`, which drew
    uniformly from the absolute window `[max(0, base - minus), base + plus]`.
    `jitter(base, minus, plus)` becomes `jitter(base, minus / base, plus / base)`;
    for the old uniform draw, call `random.uniform` on that window directly.

    Args:
        value: The target.
        decrease: How far below it the window reaches, as a fraction of it.
        increase: How far above it the window reaches, as a fraction of it.
        bias: Where the peak sits, from the low end (`0.0`) to the high end
            (`1.0`); clamped into that range.
        previous: The last value drawn, to keep away from.
        min_distance: The absolute gap to keep from `previous`.
        rng: The generator to draw from, for a reproducible stream.

    Returns:
        A value inside the window.

    Example:
        >>> 90.0 <= jitter(100, decrease=0.1, increase=0.2) <= 120.0
        True
    """
    src = rng or random

    low = value * (1.0 - decrease)
    high = value * (1.0 + increase)

    if low > high:
        low, high = high, low

    if high <= low:
        return low

    bias = min(max(bias, 0.0), 1.0)
    mode = low + (high - low) * bias

    if previous is None or min_distance <= 0.0:
        return _tri_icdf(src.random(), low, high, mode)

    cut_low = max(previous - min_distance, low)
    cut_high = min(previous + min_distance, high)

    if cut_low >= cut_high:  # The band misses the window.
        return _tri_icdf(src.random(), low, high, mode)

    left = (low, cut_low) if cut_low > low else None
    right = (cut_high, high) if cut_high < high else None

    if left is None:
        if right is None:  # The band covers the window.
            return low if (previous - low) >= (high - previous) else high

        seg = right
    elif right is None:
        seg = left
    else:
        mass_left = _tri_cdf(left[1], low, high, mode) - _tri_cdf(left[0], low, high, mode)
        mass_right = _tri_cdf(right[1], low, high, mode) - _tri_cdf(right[0], low, high, mode)
        total = mass_left + mass_right

        if total > 0.0:
            seg = left if src.random() * total < mass_left else right
        else:  # Both tails carry almost no mass.
            span_left = left[1] - left[0]
            span_total = span_left + (right[1] - right[0])
            seg = left if src.random() * span_total < span_left else right

    a, b = seg
    u_low = _tri_cdf(a, low, high, mode)
    u_high = _tri_cdf(b, low, high, mode)

    if u_high <= u_low:
        return (a + b) * 0.5

    return _tri_icdf(src.uniform(u_low, u_high), low, high, mode)


__all__ = ("jitter",)
