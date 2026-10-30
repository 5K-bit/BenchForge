"""Reports for a single result file and for a comparison. Text from files is escaped."""

from __future__ import annotations

import html
import json
import re
from typing import Any

from . import __version__
from .compare import Comparison, Row
from .resultfile import BenchResult, ResultFile
from .stats import Summary, summarize

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|~])")
VERDICT_ORDER = (
    "regression",
    "errored",
    "inconclusive",
    "improvement",
    "unchanged",
    "added",
    "removed",
)


def md(text: str) -> str:
    flat = " ".join(text.split())
    flat = flat.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _MD_SPECIAL.sub(r"\\\1", flat)


def fmt_ns(value: float) -> str:
    if value < 1_000:
        return f"{value:.0f} ns"
    if value < 1_000_000:
        return f"{value / 1_000:.2f} us"
    if value < 1_000_000_000:
        return f"{value / 1_000_000:.2f} ms"
    return f"{value / 1_000_000_000:.2f} s"


def over_budget(result: BenchResult) -> bool:
    if result.budget_ms is None or not result.samples:
        return False
    return summarize(result.samples).median > result.budget_ms * 1_000_000


# ---- single result -------------------------------------------------------------------------


def show_text(result: ResultFile) -> str:
    lines = [f"BenchForge: {result.suite}", f"recorded {result.created}"]
    lines.append("  " + ", ".join(f"{k} {v}" for k, v in sorted(result.environment.items())))
    for res in result.results:
        if res.error:
            lines.append(f"  {res.id}: FAILED: {res.error}")
            continue
        s = summarize(res.samples) if res.samples else None
        if s is None:
            lines.append(f"  {res.id}: no samples")
            continue
        budget = ""
        if res.budget_ms is not None:
            budget = f"  budget {res.budget_ms:g} ms: " + ("OVER" if over_budget(res) else "ok")
        lines.append(
            f"  {res.id}: median {fmt_ns(s.median)}  min {fmt_ns(s.minimum)}  p95 {fmt_ns(s.p95)}"
            f"  stdev {fmt_ns(s.stdev)}  n={s.n}  outliers {s.outliers}{budget}"
        )
        if res.kind == "model":
            lines.append("      " + _model_line(res))
    return "\n".join(lines) + "\n"


def _model_line(res: BenchResult) -> str:
    m = res.metrics
    parts = ["per generated token"]
    if "tokens_per_s_median" in m:
        parts.append(f"{m['tokens_per_s_median']} tokens/s")
    if "first_token_ms_median" in m:
        parts.append(f"first token {m['first_token_ms_median']} ms")
    memory = m.get("model_memory_bytes")
    if isinstance(memory, int):
        parts.append(f"model memory {memory / (1 << 30):.2f} GiB")
    if m.get("output_stable") == "no":
        parts.append("OUTPUT VARIED between passes")
    return ", ".join(parts)


def show_json(result: ResultFile) -> str:
    from .resultfile import to_json

    return to_json(result)


# ---- comparison ------------------------------------------------------------------------------


def _summary_counts(cmp: Comparison) -> str:
    counts: dict[str, int] = {}
    for row in cmp.rows:
        counts[row.verdict] = counts.get(row.verdict, 0) + 1
    return ", ".join(f"{counts[v]} {v}" for v in VERDICT_ORDER if v in counts) or "nothing compared"


def _ratio(row: Row) -> str:
    if row.ratio is None:
        return "-"
    text = f"{row.ratio:.2f}x"
    if row.ci:
        text += f" [{row.ci[0]:.2f}, {row.ci[1]:.2f}]"
    return text


def _p(row: Row) -> str:
    return "-" if row.p is None else (f"{row.p:.4f}" if row.p >= 0.0001 else "<0.0001")


def _med(s: Summary | None) -> str:
    return "-" if s is None else fmt_ns(s.median)


def compare_text(cmp: Comparison) -> str:
    lines = [
        f"BenchForge: {cmp.cand.suite}",
        f"baseline {cmp.base.created}  candidate {cmp.cand.created}",
        f"regression: slower than {cmp.threshold * 100:g}% with p < {cmp.alpha:g}",
    ]
    for note in cmp.environment_notes:
        lines.append(f"  ! environment differs, so timings may not be comparable ({note})")
    width = max((len(r.id) for r in cmp.rows), default=0)
    for row in cmp.rows:
        lines.append(
            f"  {row.verdict:<12} {row.id:<{width}}  {_med(row.base):>10} -> {_med(row.cand):<10}"
            f"  {_ratio(row):<20} p {_p(row):<8} {row.note}"
        )
    lines.append(_summary_counts(cmp))
    return "\n".join(lines) + "\n"


def compare_markdown(cmp: Comparison) -> str:
    out = [f"# BenchForge: {md(cmp.cand.suite)}", ""]
    out.append(
        f"Baseline {md(cmp.base.created)} · candidate {md(cmp.cand.created)} · "
        f"a regression is slower than {cmp.threshold * 100:g}% with p < {cmp.alpha:g} · "
        f"{_summary_counts(cmp)}"
    )
    out.append("")
    for note in cmp.environment_notes:
        out.append(f"> Environment differs, so timings may not be comparable: {md(note)}")
    if cmp.environment_notes:
        out.append("")
    out += ["| Verdict | Benchmark | Baseline | Candidate | Ratio (95% interval) | p | Note |"]
    out += ["|---|---|---|---|---|---|---|"]
    for row in cmp.rows:
        out.append(
            f"| {row.verdict.upper()} | {md(row.title)} | {_med(row.base)} | {_med(row.cand)} "
            f"| {_ratio(row)} | {_p(row)} | {md(row.note)} |"
        )
    out += [
        "",
        f"_BenchForge {__version__}. Medians of wall-clock samples; ratio is candidate over "
        "baseline. A benchmark measures one machine on one day._",
    ]
    return "\n".join(out) + "\n"


_CSS = """
:root{--bg:#0c1220;--fg:#f3f5fa;--mute:#99a7bc;--line:#283345;--accent:#2dd4bf}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
main{max-width:64rem;margin:0 auto;padding:2rem 1rem}h1{margin:0 0 .25rem}.mute{color:var(--mute)}
table{border-collapse:collapse;width:100%;margin:1rem 0}
td,th{border-bottom:1px solid var(--line);padding:.4rem .6rem;text-align:left}
.tag{font:700 .75rem ui-monospace,monospace;padding:.15rem .5rem;border:1px solid var(--mute);
border-radius:.25rem}.improvement,.unchanged{color:#3ddc97;border-color:#3ddc97}
.regression,.errored{color:#ff7a59;border-color:#ff7a59}
.inconclusive,.added,.removed{color:#ff9f1c;border-color:#ff9f1c}
.bar{height:.5rem;background:var(--accent);border-radius:.25rem;min-width:2px}
.bar.cand{background:#99a7bc}
"""


def compare_html(cmp: Comparison) -> str:
    e = html.escape
    peak = max([s.median for r in cmp.rows for s in (r.base, r.cand) if s is not None] or [1.0])
    rows: list[str] = []
    for row in cmp.rows:

        def bar(s: Summary | None, cls: str) -> str:
            if s is None:
                return ""
            width = max(1.0, s.median / peak * 100)
            return f'<div class="bar {cls}" style="width:{width:.1f}%"></div>'

        rows.append(
            f'<tr><td><span class="tag {e(row.verdict)}">{e(row.verdict.upper())}</span></td>'
            f"<td>{e(row.title)}<div>{bar(row.base, 'base')}{bar(row.cand, 'cand')}</div></td>"
            f"<td>{e(_med(row.base))}</td><td>{e(_med(row.cand))}</td>"
            f"<td>{e(_ratio(row))}</td><td>{e(_p(row))}</td><td>{e(row.note)}</td></tr>"
        )
    notes = "".join(
        f'<p class="mute">Environment differs, so timings may not be comparable: {e(n)}</p>'
        for n in cmp.environment_notes
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>BenchForge: {e(cmp.cand.suite)}</title><style>{_CSS}</style></head><body><main>"
        f"<h1>BenchForge: {e(cmp.cand.suite)}</h1>"
        f'<p class="mute">Baseline {e(cmp.base.created)} · candidate {e(cmp.cand.created)} · '
        f"regression means slower than {cmp.threshold * 100:g}% with p &lt; {cmp.alpha:g} · "
        f"{e(_summary_counts(cmp))}</p>{notes}"
        "<table><thead><tr><th>Verdict</th><th>Benchmark (grey bar: candidate)</th>"
        "<th>Baseline</th>"
        "<th>Candidate</th><th>Ratio (95% interval)</th><th>p</th><th>Note</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f'<p class="mute">BenchForge {e(__version__)}. Medians of wall-clock samples; a benchmark '
        "measures one machine on one day.</p></main></body></html>\n"
    )


def compare_json(cmp: Comparison) -> str:
    rows: list[dict[str, Any]] = []
    for r in cmp.rows:
        rows.append(
            {
                "id": r.id,
                "verdict": r.verdict,
                "baseline_median_ns": None if r.base is None else round(r.base.median, 1),
                "candidate_median_ns": None if r.cand is None else round(r.cand.median, 1),
                "ratio": None if r.ratio is None else round(r.ratio, 4),
                "ratio_ci95": [round(v, 4) for v in r.ci] if r.ci else None,
                "p": None if r.p is None else round(r.p, 6),
                "note": r.note,
            }
        )
    doc = {
        "benchforge": __version__,
        "suite": cmp.cand.suite,
        "threshold": cmp.threshold,
        "alpha": cmp.alpha,
        "environment_differences": list(cmp.environment_notes),
        "regressions": len(cmp.regressions),
        "rows": rows,
    }
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"
