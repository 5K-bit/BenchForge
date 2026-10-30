# Security Policy

## Intended use

BenchForge runs the commands and Python functions that **your own suite file** names, measures them, and writes a result file. It makes no network connections itself and sends nothing anywhere.

## What BenchForge protects, and what it does not

- **A suite file is code.** `cmd` entries are started as argument lists (no shell), and `python = "module:function"` entries import your module and call it. Treat `benchforge.toml` like a build script: do not run `benchforge run` on a suite from a source you would not run code from. Comparing and showing result files never runs anything.
- **Result files are hostile input.** They are parsed strictly: types are checked, files over 64 MiB and sample lists over 100,000 are refused, samples must be positive whole numbers. A 300-case mutation test feeds damaged result files through every report.
- **Paths stay in the project.** `cwd` and `pythonpath` must be relative with forward slashes; a symlink that leads outside the folder is refused.
- **Reports are escaped.** Names from files are escaped for Markdown and HTML; JSON is written by the standard library.
- **Verdicts are statistics, not proof.** A comparison can miss a real slowdown (too few samples, a noisy machine) or flag noise (a one-in-a-hundred chance at the default setting). Benchmarks on shared CI runners are noisy.
- **Timings can leak information.** A result file records the Python version, platform and CPU count. Look before you publish one.

The full analysis is in [docs/threat-model.md](docs/threat-model.md).

## Reporting a vulnerability

If you find a way to make a crafted result file crash or stall BenchForge, inject markup into a report, escape the project folder, or make `compare` run something, please report it privately through GitHub's **Security → Report a vulnerability** on this repository rather than a public issue.

Include the BenchForge version (`benchforge --version`), your OS and Python version, and the smallest files that reproduce it. Use made-up data only. Expect an initial response within a few days.
