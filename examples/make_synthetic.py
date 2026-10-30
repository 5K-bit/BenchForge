"""Write the synthetic baseline and candidate result files used by the recorded comparison.

    python examples/make_synthetic.py [--out examples/demo]

The numbers are made up (seeded log-normal noise around chosen medians); they stand in for two
runs of a project so the comparison output is reproducible byte for byte.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

ENV = {
    "benchforge": "0.1.0",
    "cpus": "8",
    "implementation": "CPython",
    "machine": "x86_64",
    "platform": "Linux-6.8-x86_64",
    "python": "3.13.1",
}

# id, title, baseline median (ns), candidate median (ns), baseline n, candidate n, noise (sigma)
PLAN = [
    ("parse-config", "Parse a config file", 410_000, 414_000, 30, 30, 0.04),
    ("render-report", "Render the report", 2_100_000, 2_700_000, 30, 30, 0.04),
    ("compile-rules", "Compile the rule set", 9_800_000, 6_900_000, 30, 30, 0.05),
    ("cold-start", "Cold start", 180_000_000, 181_000_000, 3, 3, 0.03),
    ("legacy-export", "Legacy export", 55_000_000, 0, 20, 0, 0.04),
]
ADDED = ("new-index", "Build the search index", 3_300_000, 20, 0.04)


def samples(rng: random.Random, median: int, count: int, sigma: float) -> list[int]:
    return [max(1, round(median * rng.lognormvariate(0, sigma))) for _ in range(count)]


def doc(suite: str, created: str, benches: list[dict[str, object]]) -> str:
    out = {
        "format": 1,
        "suite": suite,
        "created": created,
        "environment": ENV,
        "benchmarks": benches,
    }
    return json.dumps(out, indent=1, sort_keys=True) + "\n"


def bench(bid: str, title: str, values: list[int]) -> dict[str, object]:
    return {
        "id": bid,
        "title": title,
        "kind": "command",
        "unit": "ns",
        "loops": 1,
        "samples": values,
        "error": None,
        "budget_ms": None,
    }


def build() -> tuple[str, str]:
    rng = random.Random(2026)  # noqa: S311 - reproducible demo data, not security
    base: list[dict[str, object]] = []
    cand: list[dict[str, object]] = []
    for bid, title, mb, mc, nb, nc, sigma in PLAN:
        base.append(bench(bid, title, samples(rng, mb, nb, sigma)))
        if nc:
            cand.append(bench(bid, title, samples(rng, mc, nc, sigma)))
    bid, title, med, count, sigma = ADDED
    cand.append(bench(bid, title, samples(rng, med, count, sigma)))
    suite = "Orchard Sync (synthetic)"
    return (
        doc(suite, "2026-10-01T12:00:00Z", base),
        doc(suite, "2026-10-29T12:00:00Z", cand),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(Path(__file__).parent / "demo"))
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    base, cand = build()
    (out / "baseline.json").write_text(base, encoding="utf-8", newline="\n")
    (out / "candidate.json").write_text(cand, encoding="utf-8", newline="\n")
    print(f"wrote {out}/baseline.json and candidate.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
