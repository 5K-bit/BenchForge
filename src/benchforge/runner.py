"""Run benchmarks: commands as child processes (never through a shell), or Python callables."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .errors import BenchForgeError
from .model import Bench, Suite
from .resultfile import BenchResult, ResultFile, fingerprint

Timer = Callable[[], int]
Executor = Callable[[Bench, Path], None]
MAX_LOOPS = 1 << 24
OUTPUT_TAIL = 300


def _inside(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise BenchForgeError(f"{rel!r} resolves outside the project folder") from None
    return target


def run_command(bench: Bench, root: Path) -> None:
    """Run the benchmark's command once; a non-zero exit or a timeout is an error."""
    env = dict(os.environ)
    env.update(dict(bench.env))
    cwd = _inside(root, bench.cwd)
    try:
        proc = subprocess.run(  # noqa: S603 - argv list from the suite file, no shell
            list(bench.argv),
            cwd=cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=bench.timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise BenchForgeError(f"timed out after {bench.timeout_s:g} s") from None
    except OSError as exc:
        raise BenchForgeError(f"could not start {bench.argv[0]!r}: {exc.strerror or exc}") from None
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", errors="replace").strip()[-OUTPUT_TAIL:]
        raise BenchForgeError(f"exited with status {proc.returncode}: {tail}")


def load_callable(bench: Bench, root: Path) -> Callable[[], object]:
    module_name, _, attr = bench.target.partition(":")
    added = [str(_inside(root, p)) for p in (bench.pythonpath or (".",))]
    sys.path[:0] = added
    try:
        module = importlib.import_module(module_name)
        func = getattr(module, attr, None)
    except Exception as exc:  # the suite names code to import; report whatever it raises
        raise BenchForgeError(f"cannot import {bench.target}: {exc}") from None
    finally:
        for entry in added:
            if entry in sys.path:
                sys.path.remove(entry)
    if not callable(func):
        raise BenchForgeError(f"{bench.target} is not callable")
    return func  # type: ignore[no-any-return]


def measure_callable(
    func: Callable[[], object], bench: Bench, runs: int, warmup: int, timer: Timer
) -> tuple[int, list[int]]:
    """Pick a loop count so one sample lasts about min_sample_ms, then take `runs` samples."""
    target_ns = int(bench.min_sample_ms * 1_000_000)
    loops = 1
    while loops < MAX_LOOPS:
        start = timer()
        for _ in range(loops):
            func()
        if timer() - start >= target_ns:
            break
        loops *= 2
    for _ in range(warmup):
        for _ in range(loops):
            func()
    samples: list[int] = []
    for _ in range(runs):
        start = timer()
        for _ in range(loops):
            func()
        samples.append(max(1, (timer() - start) // loops))
    return loops, samples


def run_bench(
    bench: Bench,
    root: Path,
    *,
    runs: int | None = None,
    warmup: int | None = None,
    timer: Timer = time.perf_counter_ns,
    executor: Executor = run_command,
) -> BenchResult:
    n_runs = runs if runs is not None else bench.runs
    n_warm = warmup if warmup is not None else bench.warmup
    try:
        if bench.kind == "callable":
            loops, samples = measure_callable(
                load_callable(bench, root), bench, n_runs, n_warm, timer
            )
        else:
            for _ in range(n_warm):
                executor(bench, root)
            samples = []
            for _ in range(n_runs):
                start = timer()
                executor(bench, root)
                samples.append(max(1, timer() - start))
            loops = 1
    except BenchForgeError as exc:
        return BenchResult(bench.id, bench.title, bench.kind, 1, (), str(exc), bench.budget_ms)
    except Exception as exc:  # a benchmarked function may raise anything
        return BenchResult(
            bench.id,
            bench.title,
            bench.kind,
            1,
            (),
            f"{type(exc).__name__}: {exc}",
            bench.budget_ms,
        )
    return BenchResult(
        bench.id, bench.title, bench.kind, loops, tuple(samples), None, bench.budget_ms
    )


def run_suite(
    suite: Suite,
    root: Path,
    *,
    only: list[str] | None = None,
    runs: int | None = None,
    warmup: int | None = None,
    timer: Timer = time.perf_counter_ns,
    executor: Executor = run_command,
    now: datetime | None = None,
    progress: Callable[[str], None] | None = None,
) -> ResultFile:
    wanted = set(only or [])
    unknown = wanted - {b.id for b in suite.benches}
    if unknown:
        raise BenchForgeError(f"no such benchmark: {', '.join(sorted(unknown))}")
    results: list[BenchResult] = []
    for bench in suite.benches:
        if wanted and bench.id not in wanted:
            continue
        if progress:
            progress(bench.id)
        results.append(
            run_bench(bench, root, runs=runs, warmup=warmup, timer=timer, executor=executor)
        )
    moment = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    return ResultFile(
        suite.name, moment.strftime("%Y-%m-%dT%H:%M:%SZ"), fingerprint(), tuple(results)
    )
