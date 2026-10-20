"""Random values spread across a window instead of drawn independently."""

from __future__ import annotations as _annotations

import random
from dataclasses import dataclass, field

from .._internal._triangular import _tri_cdf, _tri_icdf
from ._internal import _INV_PHI


@dataclass(slots=True, eq=False)
class Jitter:
    """A stream of random values around `value` that spread across the window instead of piling up near its peak.

    ```python
    j = Jitter(5)                               # +/-10% of 5, i.e. ~[4.5, 5.5]
    j = Jitter(5, decrease=0.2, increase=0.5)   # ~[4.0, 7.5]
    [j() for _ in range(50)]                    # no run of near-equal values
    ```

    Drawing `jitter(...)` independently in a loop keeps landing near the
    peak. This instead walks the window with a golden-ratio (low-discrepancy)
    step in CDF space: every call lands far, in probability, from the one
    before, so the sequence covers the whole window while each value stays
    random and the triangular shape still holds over a run.

    Every field is a plain attribute: reassign `value` between calls to move
    the window.

    Attributes:
        value: The centre the window is built around.
        decrease: The window's low end is `value * (1 - decrease)`.
        increase: The window's high end is `value * (1 + increase)`.
        bias: Where the triangular peak sits, from `0.0` (low end) to `1.0`
            (high end); `0.5` is symmetric. Clamped to `[0, 1]`.
        wobble: How much random noise rides on the golden step, from `0`
            (rigid, predictable spread) to `1` (as loose as the no-cluster
            guarantee allows). Clamped to `[0, 1]`.
        min_distance: A hard floor on the gap from `last`. A step landing
            closer is snapped just past the near edge of that band and the
            walk resynced there; if the window is narrower than the floor,
            the furthest reachable end is returned.
        rng: The `random.Random` to draw from, for a reproducible stream.
        last: The most recent value, `None` before the first call.
    """

    value: float
    decrease: float = 0.1
    increase: float = 0.1
    bias: float = 0.5
    wobble: float = 1.0
    min_distance: float = 0.0
    rng: random.Random | None = None

    last: float | None = field(default=None, init=False)
    _u: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        """Start the walk at a random phase, so two instances differ."""
        self._u = (self.rng or random).random()

    def __call__(self) -> float:
        """Return the next value of the walk.

        Returns:
            A value inside the window, also stored in `last`.
        """
        src = self.rng or random

        low = self.value * (1.0 - self.decrease)
        high = self.value * (1.0 + self.increase)

        if low > high:
            low, high = high, low

        if high <= low:
            self.last = low
            return low

        bias = self.bias
        if bias < 0.0:
            bias = 0.0
        elif bias > 1.0:
            bias = 1.0

        mode = low + (high - low) * bias

        wobble = self.wobble
        if wobble < 0.0:
            wobble = 0.0
        elif wobble > 1.0:
            wobble = 1.0

        # Golden-ratio (Kronecker) recurrence in CDF space. A fixed step of
        # phi^-1 puts every consecutive pair ~0.382 apart on the wrapped
        # unit circle (three-distance theorem); the noise below is capped so
        # the step stays inside ~[0.44, 0.79] and that wrapped gap never
        # falls under ~0.2 -- i.e. two draws in a row can still not cluster.
        step = _INV_PHI
        if wobble:
            noise = _INV_PHI * 0.28 * wobble
            step += src.uniform(-noise, noise)

        self._u = (self._u + step) % 1.0
        result = _tri_icdf(self._u, low, high, mode)

        gap = self.min_distance

        if gap > 0.0 and self.last is not None and abs(result - self.last) < gap:
            # The step landed inside `last +/- gap`. Snap out to the near
            # edge of that band, not by resampling the far side of the
            # window -- that reaches deep into the opposite tail and washes
            # `bias` out. The `** 3` keeps the nudge hugging the edge.
            # Follow the direction the step leaned; flip if that edge is
            # outside the window; take the furthest end if neither fits.
            up = self.last + gap
            down = self.last - gap

            if up <= high and (result >= self.last or down < low):
                result = up + (high - up) * (src.random() ** 3)
            elif down >= low:
                result = down - (down - low) * (src.random() ** 3)
            else:
                result = low if (self.last - low) >= (high - self.last) else high

            # Resync the walk so the next step measures its ~0.38 in CDF
            # space from where the value actually landed.
            self._u = _tri_cdf(result, low, high, mode)

        self.last = result
        return result

    next = __call__

    def reset(self) -> None:
        """Forget `last` and restart the walk from a fresh random phase."""
        self.last = None
        self._u = (self.rng or random).random()


__all__ = ("Jitter",)
