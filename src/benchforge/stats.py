"""Statistics on timing samples: summary, Mann-Whitney U test, bootstrap interval."""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

BOOTSTRAP_ROUNDS = 2000
BOOTSTRAP_SEED = 20261030


@dataclass(frozen=True)
class Summary:
    n: int
    minimum: float
    median: float
    mean: float
    stdev: float
    mad: float
    p95: float
    outliers: int


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile of an already sorted, non-empty sequence."""
    rank = max(1, math.ceil(q / 100 * len(sorted_values)))
    return float(sorted_values[rank - 1])


def quartiles(sorted_values: Sequence[float]) -> tuple[float, float]:
    mid = len(sorted_values) // 2
    lower = sorted_values[:mid]
    upper = sorted_values[mid + len(sorted_values) % 2 :]
    if not lower or not upper:
        return float(sorted_values[0]), float(sorted_values[-1])
    return float(statistics.median(lower)), float(statistics.median(upper))


def summarize(samples: Sequence[int | float]) -> Summary:
    if not samples:
        raise ValueError("no samples")
    ordered = sorted(float(s) for s in samples)
    median = float(statistics.median(ordered))
    q1, q3 = quartiles(ordered)
    spread = q3 - q1
    low, high = q1 - 1.5 * spread, q3 + 1.5 * spread
    return Summary(
        n=len(ordered),
        minimum=ordered[0],
        median=median,
        mean=float(statistics.fmean(ordered)),
        stdev=float(statistics.stdev(ordered)) if len(ordered) > 1 else 0.0,
        mad=float(statistics.median(abs(v - median) for v in ordered)),
        p95=percentile(ordered, 95),
        outliers=sum(1 for v in ordered if v < low or v > high),
    )


def mann_whitney_p(a: Sequence[float], b: Sequence[float]) -> float:
    """Two-sided p-value of the Mann-Whitney U test (normal approximation, tie-corrected)."""
    n1, n2 = len(a), len(b)
    combined = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    total = n1 + n2
    ranks_a = 0.0
    tie_term = 0.0
    i = 0
    while i < total:
        j = i
        while j + 1 < total and combined[j + 1][0] == combined[i][0]:
            j += 1
        count = j - i + 1
        average_rank = (i + j) / 2 + 1
        ranks_a += average_rank * sum(1 for k in range(i, j + 1) if combined[k][1] == 0)
        tie_term += count**3 - count
        i = j + 1
    u1 = ranks_a - n1 * (n1 + 1) / 2
    mean_u = n1 * n2 / 2
    variance = n1 * n2 / 12 * ((total + 1) - tie_term / (total * (total - 1)))
    if variance <= 0:
        return 1.0
    z = max(0.0, abs(u1 - mean_u) - 0.5) / math.sqrt(variance)
    return float(math.erfc(z / math.sqrt(2)))


def bootstrap_ratio_ci(
    base: Sequence[float],
    cand: Sequence[float],
    rounds: int = BOOTSTRAP_ROUNDS,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Interval for median(cand) / median(base). Seeded, so the same input gives the same answer."""
    rng = random.Random(seed)  # noqa: S311 - resampling, not security
    ratios: list[float] = []
    for _ in range(rounds):
        mb = statistics.median(rng.choices(base, k=len(base)))
        mc = statistics.median(rng.choices(cand, k=len(cand)))
        if mb > 0:
            ratios.append(mc / mb)
    ratios.sort()
    if not ratios:
        return (math.nan, math.nan)
    tail = (1 - confidence) / 2
    return (percentile(ratios, tail * 100), percentile(ratios, (1 - tail) * 100))
