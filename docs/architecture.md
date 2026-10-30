# Architecture

```
benchforge.toml ─► model ─► runner ─► resultfile ─► JSON on disk
  suite (strict)     │         │  command: subprocess, no shell
                     │         ├─ callable: import, loop-calibrated
                     │         └─ model: ollama.py → local HTTP API, ns per generated token
                     ▼
two result files ─► compare ─► stats (summary · Mann-Whitney · bootstrap) ─► render
                                                    text · Markdown · HTML · JSON
```

| Module | Job |
|---|---|
| `model.py` | Parse and strictly validate the suite file into frozen dataclasses. |
| `runner.py` | Run a command or callable, take samples with an injectable timer, record per-benchmark errors. |
| `ollama.py` | Model benchmarks: loopback HTTP client for `/api/generate` and `/api/ps` (no redirects, no proxies, size caps), and the per-pass measurement with an injectable backend. |
| `resultfile.py` | Read and write result files (strictly validated), fingerprint the machine. |
| `stats.py` | Summary statistics, the Mann-Whitney U test (normal approximation, tie-corrected), a seeded bootstrap interval. |
| `compare.py` | Turn two result files into one verdict per benchmark. |
| `render.py` | Text, Markdown, HTML and JSON; all text from files is escaped. |
| `cli.py` | `init`, `run`, `show`, `compare` and the exit codes. |

## How a verdict is reached

For each benchmark present in both files:

1. Either side errored or has no samples → **errored**.
2. Fewer than 5 samples on either side → **inconclusive** (the ratio is shown, no test is run).
3. Otherwise compute the ratio of medians (candidate over baseline), a Mann-Whitney p-value and a 95% bootstrap interval for the ratio.
4. `p < alpha` and ratio > 1 + threshold → **regression**; `p < alpha` and ratio < 1 / (1 + threshold) → **improvement**; anything else → **unchanged**, with a note saying whether it was noise or a real but small difference.

Defaults: threshold 10%, alpha 0.01. Benchmarks in only one file are **added** or **removed**.

## Why these choices

- **Medians and a rank test**, not means and a t-test: timing samples are skewed and have outliers.
- **A threshold and a p-value**: significance alone flags tiny real differences; a threshold alone flags noise.
- **A seeded bootstrap**: the interval is the same every time for the same files, so reports are reproducible.
- **Raw samples are stored**, never just summaries, so any later analysis can be redone.

## Adding a statistic

1. Implement it in `stats.py` on plain sequences of floats, with tests on known values.
2. Carry it through `compare.Row` and `render.py`; round numbers in JSON so golden files do not depend on the platform's math library.
3. Regenerate goldens (`UPDATE_GOLDEN=1`) and the evidence, and review the diff.
