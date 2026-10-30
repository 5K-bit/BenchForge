"""The suite file: what to measure and how."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import BenchForgeError

MAX_CONFIG_BYTES = 1 << 20
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
TARGET_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")
ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
KEYS = {
    "id",
    "title",
    "cmd",
    "python",
    "pythonpath",
    "cwd",
    "runs",
    "warmup",
    "timeout_s",
    "min_sample_ms",
    "budget_ms",
    "env",
}


@dataclass(frozen=True)
class Bench:
    id: str
    title: str
    kind: str  # "command" or "callable"
    argv: tuple[str, ...]
    target: str
    pythonpath: tuple[str, ...]
    cwd: str
    runs: int
    warmup: int
    timeout_s: float
    min_sample_ms: float
    budget_ms: float | None
    env: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Suite:
    name: str
    benches: tuple[Bench, ...]


def safe_relpath(path: str, where: str) -> str:
    """A plain relative path with forward slashes that stays inside the project."""
    if not isinstance(path, str) or not path or len(path) > 240 or "\x00" in path:
        raise BenchForgeError(f"{where}: must be a non-empty relative path")
    if path.startswith("/") or "\\" in path or re.match(r"^[A-Za-z]:", path):
        raise BenchForgeError(f"{where}: {path!r} must be relative and use forward slashes")
    if any(part in ("", "..") for part in path.split("/")):
        raise BenchForgeError(f"{where}: {path!r} must not contain empty or '..' parts")
    return path


def _number(
    value: Any, where: str, low: float, high: float, *, integer: bool = False
) -> int | float:
    ok = isinstance(value, int) if integer else isinstance(value, int | float)
    if isinstance(value, bool) or not ok or not low <= value <= high:
        kind = "whole number" if integer else "number"
        raise BenchForgeError(f"{where}: must be a {kind} from {low:g} to {high:g}")
    return int(value) if integer else float(value)


def parse_suite(raw: dict[str, Any]) -> Suite:
    unknown = sorted(set(raw) - {"suite", "bench"})
    if unknown:
        raise BenchForgeError(f"file: unknown key(s) {', '.join(unknown)}")
    head = raw.get("suite")
    if not isinstance(head, dict) or set(head) - {"name"}:
        raise BenchForgeError("file: a [suite] table with only 'name' is required")
    name = head.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise BenchForgeError("[suite].name: must be a non-empty string")
    items = raw.get("bench", [])
    if not isinstance(items, list):
        raise BenchForgeError("file: benchmarks must be written as [[bench]] tables")
    out: list[Bench] = []
    seen: set[str] = set()
    for index, table in enumerate(items, start=1):
        where = f"bench #{index}"
        if not isinstance(table, dict):
            raise BenchForgeError(f"{where}: must be a table")
        extra = sorted(set(table) - KEYS)
        if extra:
            raise BenchForgeError(f"{where}: unknown key(s) {', '.join(extra)}")
        bid = table.get("id")
        if not isinstance(bid, str) or not ID_RE.match(bid):
            raise BenchForgeError(f"{where}.id: lowercase letters, digits and dashes required")
        if bid in seen:
            raise BenchForgeError(f"{where}.id: duplicate id {bid!r}")
        seen.add(bid)
        where = f"bench {bid}"
        if ("cmd" in table) == ("python" in table):
            raise BenchForgeError(f"{where}: give exactly one of 'cmd' or 'python'")
        argv: tuple[str, ...] = ()
        target = ""
        if "cmd" in table:
            cmd = table["cmd"]
            if (
                not isinstance(cmd, list)
                or not cmd
                or not all(isinstance(a, str) and a and "\x00" not in a for a in cmd)
            ):
                raise BenchForgeError(f"{where}.cmd: must be a list of strings (no shell)")
            argv = tuple(cmd)
        else:
            target = table["python"]
            if not isinstance(target, str) or not TARGET_RE.match(target):
                raise BenchForgeError(f"{where}.python: must look like 'module:function'")
        paths_raw = table.get("pythonpath", [])
        if not isinstance(paths_raw, list):
            raise BenchForgeError(f"{where}.pythonpath: must be a list of relative paths")
        env_raw = table.get("env", {})
        if not isinstance(env_raw, dict) or len(env_raw) > 32:
            raise BenchForgeError(f"{where}.env: must be a table of up to 32 strings")
        for key, val in env_raw.items():
            if not ENV_RE.match(key) or not isinstance(val, str) or "\x00" in val:
                raise BenchForgeError(f"{where}.env: bad entry {key!r}")
        budget = table.get("budget_ms")
        title = table.get("title", bid)
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise BenchForgeError(f"{where}.title: must be a non-empty string")
        out.append(
            Bench(
                id=bid,
                title=title,
                kind="command" if argv else "callable",
                argv=argv,
                target=target,
                pythonpath=tuple(safe_relpath(p, f"{where}.pythonpath") for p in paths_raw),
                cwd=safe_relpath(table.get("cwd", "."), f"{where}.cwd")
                if table.get("cwd")
                else ".",
                runs=int(_number(table.get("runs", 20), f"{where}.runs", 1, 10000, integer=True)),
                warmup=int(
                    _number(table.get("warmup", 2), f"{where}.warmup", 0, 100, integer=True)
                ),
                timeout_s=float(
                    _number(table.get("timeout_s", 60), f"{where}.timeout_s", 0.1, 3600)
                ),
                min_sample_ms=float(
                    _number(table.get("min_sample_ms", 10), f"{where}.min_sample_ms", 0.001, 10000)
                ),
                budget_ms=None
                if budget is None
                else float(_number(budget, f"{where}.budget_ms", 0.000001, 1e9)),
                env=tuple(sorted(env_raw.items())),
            )
        )
    return Suite(name=name, benches=tuple(out))


def load_suite(path: Path) -> Suite:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        raise BenchForgeError(
            f"suite file not found: {path} (create one with 'benchforge init')"
        ) from None
    except OSError as exc:
        raise BenchForgeError(f"cannot read {path}: {exc.strerror or exc}") from None
    if size > MAX_CONFIG_BYTES:
        raise BenchForgeError(f"{path}: larger than {MAX_CONFIG_BYTES >> 10} KiB")
    try:
        raw = tomllib.loads(path.read_bytes().decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise BenchForgeError(f"{path}: not valid TOML: {exc}") from None
    return parse_suite(raw)
