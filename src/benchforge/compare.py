"""Compare two result files: is the candidate slower or faster, or is it just noise?"""

from __future__ import annotations

from dataclasses import dataclass

from .resultfile import BenchResult, ResultFile
from .stats import Summary, bootstrap_ratio_ci, mann_whitney_p, summarize

MIN_SAMPLES = 5
DEFAULT_THRESHOLD = 0.10
DEFAULT_ALPHA = 0.01


@dataclass(frozen=True)
class Row:
    id: str
    title: str
    verdict: str  # regression improvement unchanged inconclusive errored added removed
    base: Summary | None
    cand: Summary | None
    ratio: float | None
    ci: tuple[float, float] | None
    p: float | None
    note: str


@dataclass(frozen=True)
class Comparison:
    base: ResultFile
    cand: ResultFile
    threshold: float
    alpha: float
    rows: tuple[Row, ...]
    environment_notes: tuple[str, ...]

    @property
    def regressions(self) -> list[Row]:
        return [r for r in self.rows if r.verdict == "regression"]


def _row(base: BenchResult, cand: BenchResult, threshold: float, alpha: float) -> Row:
    title = cand.title
    if base.error or cand.error:
        who = "baseline" if base.error else "candidate"
        return Row(cand.id, title, "errored", None, None, None, None, None, f"{who} run failed")
    if not base.samples or not cand.samples:
        return Row(cand.id, title, "errored", None, None, None, None, None, "no samples")
    sb, sc = summarize(base.samples), summarize(cand.samples)
    ratio = sc.median / sb.median
    if sb.n < MIN_SAMPLES or sc.n < MIN_SAMPLES:
        note = f"needs at least {MIN_SAMPLES} samples on each side (have {sb.n} and {sc.n})"
        return Row(cand.id, title, "inconclusive", sb, sc, ratio, None, None, note)
    b = [float(s) for s in base.samples]
    c = [float(s) for s in cand.samples]
    p = mann_whitney_p(b, c)
    ci = bootstrap_ratio_ci(b, c)
    if p < alpha and ratio > 1 + threshold:
        verdict, note = "regression", f"{(ratio - 1) * 100:.1f}% slower"
    elif p < alpha and ratio < 1 / (1 + threshold):
        verdict, note = "improvement", f"{(1 - ratio) * 100:.1f}% faster"
    elif p < alpha:
        verdict, note = "unchanged", "differs, but within the threshold"
    else:
        verdict, note = "unchanged", "difference is within noise"
    return Row(cand.id, title, verdict, sb, sc, ratio, ci, p, note)


def compare(
    base: ResultFile,
    cand: ResultFile,
    threshold: float = DEFAULT_THRESHOLD,
    alpha: float = DEFAULT_ALPHA,
) -> Comparison:
    base_by = {r.id: r for r in base.results}
    cand_by = {r.id: r for r in cand.results}
    rows: list[Row] = []
    for bid in sorted(set(base_by) | set(cand_by)):
        if bid not in cand_by:
            rows.append(
                Row(
                    bid,
                    base_by[bid].title,
                    "removed",
                    None,
                    None,
                    None,
                    None,
                    None,
                    "only in baseline",
                )
            )
        elif bid not in base_by:
            rows.append(
                Row(
                    bid,
                    cand_by[bid].title,
                    "added",
                    None,
                    None,
                    None,
                    None,
                    None,
                    "only in candidate",
                )
            )
        else:
            rows.append(_row(base_by[bid], cand_by[bid], threshold, alpha))
    notes = tuple(
        f"{key}: baseline {base.environment.get(key, '?')}, "
        f"candidate {cand.environment.get(key, '?')}"
        for key in sorted(set(base.environment) | set(cand.environment))
        if key != "benchforge" and base.environment.get(key) != cand.environment.get(key)
    )
    return Comparison(base, cand, threshold, alpha, tuple(rows), notes)
