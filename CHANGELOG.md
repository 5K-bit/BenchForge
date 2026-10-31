# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Recorded a real Ollama run (llama3.2:3b, one Windows machine) in `docs/evidence/model-real-run.*`, with its limits stated.
- `model` benchmarks: time local models through Ollama's HTTP API with a fixed prompt set, fixed seed and temperature 0. Samples are nanoseconds per generated token, so `compare` works unchanged. Records tokens per second, time to first token, reported model memory and an output-stability flag in an optional `metrics` object (result format stays 1; older files read unchanged).
- Loopback-only by default; another host needs `allow_remote = true`. Proxy settings and redirects are ignored.
- `examples/model_demo.py` and `examples/models/benchforge.toml`; recorded stand-in transcript.

## [0.1.0] - 2026-10-30

First working version.

### Added

- A suite file (`benchforge.toml`) with command benchmarks (argument lists, never a shell) and in-process Python callables, strict validation, per-benchmark runs, warm-up, timeout, environment and an optional time budget.
- A runner that records wall-clock samples in nanoseconds, calibrates loop counts for callables, and fingerprints the machine; failures are recorded per benchmark.
- Statistics: median, mean, standard deviation, MAD, 95th percentile and Tukey outlier counts; a Mann-Whitney U test; a seeded bootstrap interval for the ratio of medians.
- `benchforge init`, `run` (exit 2 over budget), `show`, and `compare` (text, Markdown, HTML or JSON; `--threshold`, `--alpha`, `--fail-on-regression`).
- Verdicts: regression, improvement, unchanged, inconclusive (too few samples), errored, added, removed; a warning when the two machines differ.
- A demo suite, synthetic baseline and candidate results, and an acceptance script whose transcript is recorded in `docs/evidence/`.
