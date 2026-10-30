"""Command line: init, run, show, compare."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, render
from .compare import DEFAULT_ALPHA, DEFAULT_THRESHOLD, compare
from .errors import BenchForgeError
from .model import load_suite
from .resultfile import read_result, write_result
from .runner import run_suite

CONFIG_NAME = "benchforge.toml"
DEFAULT_OUT = "benchforge-result.json"

STARTER = """\
# BenchForge suite. Commands are argument lists (never run through a shell).
# Run 'benchforge run' to record samples, then 'benchforge compare OLD.json NEW.json'.

[suite]
name = "my project"

[[bench]]
id = "startup"
title = "Interpreter start-up"
cmd = ["python", "-c", "pass"]
runs = 20
warmup = 2
# budget_ms = 100          # optional: 'run' exits 2 if the median is over this

# A Python function is timed in-process, many calls per sample:
# [[bench]]
# id = "parse"
# python = "mypackage.bench:parse_sample"
# pythonpath = ["src"]
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchforge", description="Reproducible benchmarks with honest statistics."
    )
    parser.add_argument("--version", action="version", version=f"benchforge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="write a starter suite file")
    init.add_argument("-C", "--root", default=".")
    init.add_argument("--force", action="store_true")

    run = sub.add_parser("run", help="run the suite and record samples")
    run.add_argument("-C", "--root", default=".", help="project folder (default: .)")
    run.add_argument("--config", help=f"suite file (default: ROOT/{CONFIG_NAME})")
    run.add_argument("--out", help=f"result file (default: ROOT/{DEFAULT_OUT})")
    run.add_argument("--only", action="append", default=[], help="run only this benchmark id")
    run.add_argument("--runs", type=int, help="override the number of samples")
    run.add_argument("--warmup", type=int, help="override the number of warm-up runs")

    show = sub.add_parser("show", help="summarise a result file")
    show.add_argument("file")
    show.add_argument("--format", choices=["text", "json"], default="text")

    cmp = sub.add_parser("compare", help="compare a candidate against a baseline")
    cmp.add_argument("baseline")
    cmp.add_argument("candidate")
    cmp.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    cmp.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    cmp.add_argument("--format", choices=["text", "md", "html", "json"], default="text")
    cmp.add_argument("--out", help="write to this file instead of the screen")
    cmp.add_argument("--fail-on-regression", action="store_true", help="exit 2 on any regression")
    return parser


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _init(args: argparse.Namespace) -> int:
    target = Path(args.root) / CONFIG_NAME
    if target.exists() and not args.force:
        raise BenchForgeError(f"{target} already exists (use --force to overwrite)")
    target.parent.mkdir(parents=True, exist_ok=True)
    _write(target, STARTER)
    print(f"wrote {target}")
    return 0


def _run(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if not root.is_dir():
        raise BenchForgeError(f"not a folder: {root}")
    for name, value, low in (("--runs", args.runs, 1), ("--warmup", args.warmup, 0)):
        if value is not None and not low <= value <= 100_000:
            raise BenchForgeError(f"{name} must be from {low} to 100000")
    suite = load_suite(Path(args.config) if args.config else root / CONFIG_NAME)
    result = run_suite(
        suite,
        root,
        only=args.only,
        runs=args.runs,
        warmup=args.warmup,
        progress=lambda bid: print(f"running {bid} ...", file=sys.stderr),
    )
    out = Path(args.out) if args.out else root / DEFAULT_OUT
    write_result(out, result)
    sys.stdout.write(render.show_text(result))
    print(f"wrote {out}")
    if any(r.error for r in result.results):
        return 1
    return 2 if any(render.over_budget(r) for r in result.results) else 0


def _show(args: argparse.Namespace) -> int:
    result = read_result(Path(args.file))
    render_fn = render.show_json if args.format == "json" else render.show_text
    sys.stdout.write(render_fn(result))
    return 0


def _compare(args: argparse.Namespace) -> int:
    if not 0 < args.alpha < 1 or not 0 < args.threshold < 100:
        raise BenchForgeError("--alpha must be between 0 and 1 and --threshold above 0")
    cmp = compare(
        read_result(Path(args.baseline)),
        read_result(Path(args.candidate)),
        args.threshold,
        args.alpha,
    )
    body = {
        "text": render.compare_text,
        "md": render.compare_markdown,
        "html": render.compare_html,
        "json": render.compare_json,
    }[args.format](cmp)
    if args.out:
        _write(Path(args.out), body)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(body)
    return 2 if args.fail_on_regression and cmp.regressions else 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handlers = {"init": _init, "run": _run, "show": _show, "compare": _compare}
    try:
        return handlers[args.command](args)
    except BenchForgeError as exc:
        print(f"benchforge: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"benchforge: {exc.strerror or exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:  # pragma: no cover
        os._exit(1)
