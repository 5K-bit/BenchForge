"""Result files: the recorded samples and the machine they were taken on."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .errors import BenchForgeError

MAX_RESULT_BYTES = 64 << 20
MAX_SAMPLES = 100_000
MAX_BENCHES = 1000


@dataclass(frozen=True)
class BenchResult:
    id: str
    title: str
    kind: str
    loops: int
    samples: tuple[int, ...]
    error: str | None = None
    budget_ms: float | None = None


@dataclass(frozen=True)
class ResultFile:
    suite: str
    created: str
    environment: dict[str, str]
    results: tuple[BenchResult, ...]


def fingerprint() -> dict[str, str]:
    return {
        "benchforge": __version__,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(terse=True),
        "machine": platform.machine(),
        "cpus": str(os.cpu_count() or 0),
    }


def to_json(result: ResultFile) -> str:
    doc: dict[str, Any] = {
        "format": 1,
        "suite": result.suite,
        "created": result.created,
        "environment": dict(sorted(result.environment.items())),
        "benchmarks": [
            {
                "id": r.id,
                "title": r.title,
                "kind": r.kind,
                "unit": "ns",
                "loops": r.loops,
                "samples": list(r.samples),
                "error": r.error,
                "budget_ms": r.budget_ms,
            }
            for r in result.results
        ],
    }
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def write_result(path: Path, result: ResultFile) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(to_json(result), encoding="utf-8", newline="\n")
    os.replace(temp, path)


def _str(value: Any, where: str, limit: int = 300) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{where} must be a string of at most {limit} characters")
    return value


def read_result(path: Path) -> ResultFile:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        raise BenchForgeError(f"result file not found: {path}") from None
    except OSError as exc:
        raise BenchForgeError(f"cannot read {path}: {exc.strerror or exc}") from None
    if size > MAX_RESULT_BYTES:
        raise BenchForgeError(f"{path}: larger than {MAX_RESULT_BYTES >> 20} MiB")
    try:
        raw = json.loads(path.read_bytes())
        if raw["format"] != 1:
            raise ValueError("unsupported format")
        env_raw = raw["environment"]
        if not isinstance(env_raw, dict) or len(env_raw) > 64:
            raise ValueError("environment must be a small object")
        env = {
            _str(k, "environment key", 64): _str(v, "environment value") for k, v in env_raw.items()
        }
        items = raw["benchmarks"]
        if not isinstance(items, list) or len(items) > MAX_BENCHES:
            raise ValueError("benchmarks must be a list")
        results: list[BenchResult] = []
        seen: set[str] = set()
        for item in items:
            bid = _str(item["id"], "id", 64)
            if bid in seen:
                raise ValueError(f"duplicate benchmark {bid!r}")
            seen.add(bid)
            samples = item["samples"]
            if not isinstance(samples, list) or len(samples) > MAX_SAMPLES:
                raise ValueError(f"{bid}: samples must be a list of at most {MAX_SAMPLES}")
            if not all(isinstance(s, int) and not isinstance(s, bool) and s > 0 for s in samples):
                raise ValueError(f"{bid}: samples must be positive whole numbers of nanoseconds")
            loops = item.get("loops", 1)
            if isinstance(loops, bool) or not isinstance(loops, int) or loops < 1:
                raise ValueError(f"{bid}: loops must be a positive whole number")
            budget = item.get("budget_ms")
            if budget is not None and (
                isinstance(budget, bool) or not isinstance(budget, int | float)
            ):
                raise ValueError(f"{bid}: budget_ms must be a number")
            error = item.get("error")
            results.append(
                BenchResult(
                    id=bid,
                    title=_str(item.get("title", bid), "title", 200),
                    kind=_str(item.get("kind", "command"), "kind", 20),
                    loops=loops,
                    samples=tuple(samples),
                    error=None if error is None else _str(error, "error", 1000),
                    budget_ms=None if budget is None else float(budget),
                )
            )
        return ResultFile(
            suite=_str(raw["suite"], "suite", 200),
            created=_str(raw["created"], "created", 40),
            environment=env,
            results=tuple(results),
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise BenchForgeError(f"{path}: not a valid BenchForge result ({exc})") from None
