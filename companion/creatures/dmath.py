"""Platform-independent trig.

``math.sin``/``math.cos`` come from the C library and may differ in the last
bit between Linux, Windows and macOS, which can flip a pixel. These versions
use only IEEE-754 + - * / and ``round`` (all correctly rounded everywhere), so
the same pose rasterises to the same pixels on every OS.
"""
from __future__ import annotations

PI = 3.141592653589793
TAU = 6.283185307179586
HALF_PI = 1.5707963267948966


def _sin_core(x: float) -> float:
    # x in [-pi/2, pi/2]; odd Taylor series to x^15 (|err| < 1e-9)
    x2 = x * x
    return x * (1.0 + x2 * (-1.0 / 6 + x2 * (1.0 / 120 + x2 * (-1.0 / 5040 + x2 * (
        1.0 / 362880 + x2 * (-1.0 / 39916800 + x2 * (1.0 / 6227020800
                                                    - x2 / 1307674368000.0)))))))


def sin(x: float) -> float:
    x = x - TAU * round(x / TAU)          # [-pi, pi]
    if x > HALF_PI:
        x = PI - x
    elif x < -HALF_PI:
        x = -PI - x
    return _sin_core(x)


def cos(x: float) -> float:
    return sin(x + HALF_PI)


def deg(a: float) -> float:
    """Degrees -> radians."""
    return a * (PI / 180.0)


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def smooth(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def wave(t: float) -> float:
    """sin over a 0..1 cycle."""
    return sin(t * TAU)


def snap(x: float, step: float = 1.0 / 64) -> float:
    """Quantise a coordinate so near-ties can't flip pixels between OSes."""
    return round(x / step) * step
