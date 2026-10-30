"""Run BenchForge's comparison workflow on the synthetic demo results and record it.

    python examples/acceptance.py --out /tmp/evidence

No clock is involved, so the transcript and reports are reproducible byte for byte.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent / "demo"


class Run:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def say(self, text: str) -> None:
        self.lines.append(text)

    def cli(self, *args: str) -> int:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "benchforge", *args],
            capture_output=True,
            text=True,
            check=False,
            cwd=DEMO,
        )
        self.say("$ benchforge " + " ".join(args))
        for stream in (proc.stdout, proc.stderr):
            self.lines.extend(stream.splitlines())
        self.say(f"[exit {proc.returncode}]")
        self.say("")
        return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    out = Path(parser.parse_args(argv).out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    run = Run()
    run.say("== 1. What was recorded ==")
    run.cli("show", "baseline.json")
    run.say("== 2. Compare the candidate with the baseline ==")
    run.cli("compare", "baseline.json", "candidate.json")
    run.say("== 3. Gate a pipeline on regressions ==")
    code = run.cli("compare", "baseline.json", "candidate.json", "--fail-on-regression")
    run.say("== 4. A run compared with itself is within noise ==")
    run.cli("compare", "baseline.json", "baseline.json", "--fail-on-regression")
    run.say("== 5. A stricter threshold, a looser one ==")
    run.cli("compare", "baseline.json", "candidate.json", "--threshold", "0.5")
    run.say("== 6. Missing file ==")
    run.cli("compare", "baseline.json", "nope.json")
    for fmt, name in (("md", "compare.md"), ("html", "compare.html"), ("json", "compare.json")):
        subprocess.run(  # noqa: S603
            [sys.executable, "-m", "benchforge", "compare", "baseline.json", "candidate.json"]
            + ["--format", fmt, "--out", str(out / name)],
            check=True,
            capture_output=True,
            cwd=DEMO,
        )
    (out / "acceptance-transcript.txt").write_text(
        "\n".join(run.lines), encoding="utf-8", newline="\n"
    )
    print(f"wrote {out}")
    return 0 if code == 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
