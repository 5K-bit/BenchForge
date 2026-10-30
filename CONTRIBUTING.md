# Contributing

Thanks for your interest in PacketStory.

## Ways to help

- Report a verdict that was wrong (a regression missed, or noise called a regression) with two small result files of made-up numbers.
- Add a statistic or a report format (see [docs/architecture.md](docs/architecture.md#adding-a-statistic)) or improve the docs.

## Development

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
ruff check . && ruff format --check .
mypy
python -m pytest --cov                            # must pass before you open a PR
python examples/acceptance.py --out /tmp/evidence # the comparison workflow end to end
```

## Guidelines

- The core uses only the Python standard library.
- No network calls. Commands run as argument lists, never through a shell.
- Treat result files as hostile input: validate types, cap sizes, never trust a count.
- Verdicts need a named threshold and tests on both sides of it. Say "noise" only when a test supports it.
- Randomness is seeded (the bootstrap), so the same two files always give the same report.
- Changing report text on purpose? Regenerate the golden files with `UPDATE_GOLDEN=1 python -m pytest tests/unit/test_render_fuzz.py` and the evidence with `python examples/acceptance.py --out docs/evidence`, and review the diff.
- Demo numbers must be made up and labelled synthetic. Never commit timings from a customer's system.
- Do not add claims (speed, platform support, security) that a test or recorded evidence does not back up.
- Use clear commit messages and keep pull requests focused.
