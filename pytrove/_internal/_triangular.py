"""Triangular-distribution math shared by `num_tools.jitter` and `models.Jitter`."""

from __future__ import annotations as _annotations

from math import sqrt


def _tri_cdf(x: float, low: float, high: float, mode: float) -> float:
    """Compute the triangular CDF, `P(X <= x)` for `X ~ Triangular(low, high, mode)`.

    `mode == low` and `mode == high` are both safe: the branch whose
    denominator would be zero is the one no `x` inside `(low, high)` reaches.

    Args:
        x: The point to evaluate.
        low: The lower end of the support.
        high: The upper end of the support.
        mode: The peak, between `low` and `high`.

    Returns:
        The probability mass at or below `x`, between `0.0` and `1.0`.
    """
    if x <= low:
        return 0.0

    if x >= high:
        return 1.0

    span = high - low

    if x <= mode:
        return (x - low) * (x - low) / (span * (mode - low))

    return 1.0 - (high - x) * (high - x) / (span * (high - mode))


def _tri_icdf(u: float, low: float, high: float, mode: float) -> float:
    """Compute the triangular quantile, the `x` with `_tri_cdf(x) == u`.

    A uniform draw for `u` gives a triangular sample, and a draw confined to
    `[_tri_cdf(a), _tri_cdf(b)]` gives one truncated to `[a, b]` with no
    draw-and-retry, which is how `jitter` avoids bunching.

    Args:
        u: A probability between `0.0` and `1.0`.
        low: The lower end of the support.
        high: The upper end of the support.
        mode: The peak, between `low` and `high`.

    Returns:
        The point below which a fraction `u` of the mass lies, or `low`
        when the support is empty.
    """
    span = high - low

    if span <= 0.0:
        return low

    peak = (mode - low) / span

    if u <= peak:
        return low + sqrt(u * span * (mode - low))

    return high - sqrt((1.0 - u) * span * (high - mode))


__all__ = (
    "_tri_cdf",
    "_tri_icdf",
)
