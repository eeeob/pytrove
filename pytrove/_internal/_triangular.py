"""Triangular-distribution math shared by `num_tools.jitter` and `models.Jitter`."""

from __future__ import annotations as _annotations

from math import isnan, sqrt


def _clamp01(x: float) -> float:
    """Clamp `x` into `[0.0, 1.0]`, reading NaN as `0.0`.

    `min(max(x, 0.0), 1.0)` alone lets NaN through, since every comparison with
    it is false, and a NaN bias or wobble would then poison every later value.

    Args:
        x: The value to clamp.

    Returns:
        `x` inside `[0.0, 1.0]`.
    """
    if isnan(x):
        return 0.0
    return min(max(x, 0.0), 1.0)


def _tri_window(
    value: float, decrease: float, increase: float, bias: float
) -> tuple[float, float, float]:
    """Build the triangular window `jitter` and `Jitter` draw from.

    The ends are `value * (1 - decrease)` and `value * (1 + increase)`, put in
    order so a negative `value` works. The peak sits at the fraction `bias`
    (clamped by `_clamp01`) of the way from the low end to the high end.

    Args:
        value: The centre the window is built around.
        decrease: How far below it the window reaches, as a fraction of it.
        increase: How far above it the window reaches, as a fraction of it.
        bias: Where the peak sits, from `0.0` (low end) to `1.0` (high end).

    Returns:
        `(low, high, mode)`; the window is empty when `high <= low`, and then
        `mode == low`.

    Example:
        >>> _tri_window(100, 0.1, 0.2, 0.5)
        (90.0, 120.0, 105.0)
        >>> _tri_window(-10, 0.5, 0.5, 0.0)
        (-15.0, -5.0, -15.0)
    """
    low = value * (1.0 - decrease)
    high = value * (1.0 + increase)

    if low > high:
        low, high = high, low

    if high <= low:
        return low, high, low

    return low, high, low + (high - low) * _clamp01(bias)


def _tri_cdf(x: float, low: float, high: float, mode: float) -> float:
    """Compute the triangular CDF, `P(X <= x)` for `X ~ Triangular(low, high, mode)`.

    `mode == low` and `mode == high` are both safe: the branch whose
    denominator would be zero is the one no `x` inside `(low, high)` reaches.
    An empty or negative support (`high <= low`) is a point mass at `low`,
    matching `_tri_icdf`.

    Args:
        x: The point to evaluate.
        low: The lower end of the support.
        high: The upper end of the support.
        mode: The peak, between `low` and `high`.

    Returns:
        The probability mass at or below `x`, between `0.0` and `1.0`.
    """
    span = high - low

    if span <= 0.0:
        return 1.0 if x >= low else 0.0

    if x <= low:
        return 0.0

    if x >= high:
        return 1.0

    if x <= mode:
        return (x - low) * (x - low) / (span * (mode - low))

    return 1.0 - (high - x) * (high - x) / (span * (high - mode))


def _tri_icdf(u: float, low: float, high: float, mode: float) -> float:
    """Compute the triangular quantile, the `x` with `_tri_cdf(x) == u`.

    A uniform draw for `u` gives a triangular sample, and a draw confined to
    `[_tri_cdf(a), _tri_cdf(b)]` gives one truncated to `[a, b]` with no
    draw-and-retry, which is how `jitter` avoids bunching.

    Args:
        u: A probability; clamped by `_clamp01`, so one outside `[0.0, 1.0]`
            gives an end of the support rather than a math domain error.
        low: The lower end of the support.
        high: The upper end of the support.
        mode: The peak, between `low` and `high`.

    Returns:
        The point below which a fraction `u` of the mass lies, or `low`
        when the support is empty or negative.
    """
    span = high - low

    if span <= 0.0:
        return low

    u = _clamp01(u)
    peak = (mode - low) / span

    if u <= peak:
        return low + sqrt(u * span * (mode - low))

    return high - sqrt((1.0 - u) * span * (high - mode))


__all__ = (
    "_clamp01",
    "_tri_cdf",
    "_tri_icdf",
    "_tri_window",
)
