from __future__ import annotations
import math
import time


def _alpha(cutoff_hz: float, dt: float) -> float:
    # smoothing factor from cutoff frequency
    tau = 1.0 / (2.0 * math.pi * cutoff_hz)
    return 1.0 / (1.0 + tau / max(dt, 1e-6))


class LowPass:
    def __init__(self, x0: float = 0.0):
        self.x = x0
        self.initialized = False

    def reset(self):
        self.initialized = False

    def apply(self, x: float, a: float) -> float:
        if not self.initialized:
            self.x = x
            self.initialized = True
            return x
        self.x = a * x + (1.0 - a) * self.x
        return self.x


class OneEuro:
    """
    One Euro Filter (Casiez et al. 2012).
    Smooths jitter when slow, low latency when fast.
    """

    def __init__(self, min_cutoff: float = 2.2, beta: float = 0.08, d_cutoff: float = 1.0):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)

        self._x = LowPass()
        self._dx = LowPass()
        self._last_t = None

    def reset(self):
        self._x.reset()
        self._dx.reset()
        self._last_t = None

    def apply(self, x: float, t: float | None = None) -> float:
        if t is None:
            t = time.time()

        if self._last_t is None:
            self._last_t = t
            self._x.initialized = False
            self._dx.initialized = False
            return self._x.apply(x, 1.0)

        dt = max(1e-4, t - self._last_t)
        self._last_t = t

        # derivative of signal
        prev = self._x.x if self._x.initialized else x
        dx = (x - prev) / dt

        a_d = _alpha(self.d_cutoff, dt)
        edx = self._dx.apply(dx, a_d)

        cutoff = self.min_cutoff + self.beta * abs(edx)
        a = _alpha(cutoff, dt)
        return self._x.apply(x, a)
