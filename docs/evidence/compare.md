# BenchForge: Orchard Sync \(synthetic\)

Baseline 2026-10-01T12:00:00Z · candidate 2026-10-29T12:00:00Z · a regression is slower than 10% with p < 0.01 · 1 regression, 1 inconclusive, 1 improvement, 1 unchanged, 1 added, 1 removed

| Verdict | Benchmark | Baseline | Candidate | Ratio (95% interval) | p | Note |
|---|---|---|---|---|---|---|
| INCONCLUSIVE | Cold start | 182.30 ms | 176.08 ms | 0.97x | - | needs at least 5 samples on each side \(have 3 and 3\) |
| IMPROVEMENT | Compile the rule set | 9.86 ms | 6.96 ms | 0.71x [0.68, 0.73] | <0.0001 | 29.4% faster |
| REMOVED | Legacy export | - | - | - | - | only in baseline |
| ADDED | Build the search index | - | - | - | - | only in candidate |
| UNCHANGED | Parse a config file | 410.47 us | 412.44 us | 1.00x [0.98, 1.03] | 0.7845 | difference is within noise |
| REGRESSION | Render the report | 2.10 ms | 2.72 ms | 1.30x [1.26, 1.32] | <0.0001 | 29.7% slower |

_BenchForge 0.1.0. Medians of wall-clock samples; ratio is candidate over baseline. A benchmark measures one machine on one day._
