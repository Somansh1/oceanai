"""Wilson score interval — honest error bars on small eval sets."""
from __future__ import annotations

import math


def wilson_interval(passed: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return 0.0, 1.0
    p = passed / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom)
