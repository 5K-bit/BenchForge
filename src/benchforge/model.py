"""The suite file: what to measure and how."""

from __future__ import annotations

import re
import tomllib
import urllib.parse
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
    "model",
    "host",
    "prompts",
    "num_predict",
    "seed",
    "temperature",
    "allow_remote",
}
MODEL_ONLY = {"host", "prompts", "num_predict", "seed", "temperature", "allow_remote"}
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
DEFAULT_HOST = "http://127.0.0.1:11434"
MAX_PROMPTS = 32
MAX_PROMPT_CHARS = 8000


LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def check_host(host: str, allow_remote: bool, where: str) -> str:
    """A plain http(s) origin. Loopback only, unless the suite says allow_remote = true."""
    try:
        parts = urllib.parse.urlsplit(host)
        port = parts.port
    except ValueError:
        raise BenchForgeError(f"{where}.host: not a valid URL") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BenchForgeError(f"{where}.host: must look like http://127.0.0.1:11434")
    if (
        parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    ):
        raise BenchForgeError(f"{where}.host: must be just a scheme, host and optional port")
    if parts.hostname not in LOOPBACK and not allow_remote:
        raise BenchForgeError(
            f"{where}.host: {parts.hostname!r} is not this machine; set allow_remote = true to "
            "benchmark a model on another host (prompts are sent there)"
        )
    shown = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"{parts.scheme}://{shown}" + (f":{port}" if port else "")


@dataclass(frozen=True)
class Bench:
    id: str
    title: str
    kind: str  # "command", "callable" or "model"
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
    model: str = ""
    host: str = ""
    prompts: tuple[str, ...] = ()
    num_predict: int = 0
    seed: int = 0
    temperature: float = 0.0


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
        if sum(key in table for key in ("cmd", "python", "model")) != 1:
            raise BenchForgeError(f"{where}: give exactly one of 'cmd', 'python' or 'model'")
        if "model" not in table:
            stray = sorted(MODEL_ONLY & set(table))
            if stray:
                raise BenchForgeError(
                    f"{where}: {', '.join(stray)} only apply to a 'model' benchmark"
                )
        model_name = ""
        host = ""
        prompts: tuple[str, ...] = ()
        if "model" in table:
            model_name = table["model"]
            if not isinstance(model_name, str) or not MODEL_RE.match(model_name):
                raise BenchForgeError(f"{where}.model: must look like 'llama3.2:3b'")
            allow = table.get("allow_remote", False)
            if not isinstance(allow, bool):
                raise BenchForgeError(f"{where}.allow_remote: must be true or false")
            host = check_host(table.get("host", DEFAULT_HOST), allow, where)
            raw_prompts = table.get("prompts")
            if (
                not isinstance(raw_prompts, list)
                or not 1 <= len(raw_prompts) <= MAX_PROMPTS
                or not all(
                    isinstance(p, str)
                    and p.strip()
                    and len(p) <= MAX_PROMPT_CHARS
                    and "\x00" not in p
                    for p in raw_prompts
                )
            ):
                raise BenchForgeError(
                    f"{where}.prompts: give 1 to {MAX_PROMPTS} non-empty strings "
                    f"of at most {MAX_PROMPT_CHARS} characters (the fixed task)"
                )
            prompts = tuple(raw_prompts)
        argv: tuple[str, ...] = ()
        target = ""
        if "model" in table:
            pass
        elif "cmd" in table:
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
                kind="model" if model_name else "command" if argv else "callable",
                argv=argv,
                target=target,
                pythonpath=tuple(safe_relpath(p, f"{where}.pythonpath") for p in paths_raw),
                cwd=safe_relpath(table.get("cwd", "."), f"{where}.cwd")
                if table.get("cwd")
                else ".",
                runs=int(
                    _number(
                        table.get("runs", 5 if model_name else 20),
                        f"{where}.runs",
                        1,
                        10000,
                        integer=True,
                    )
                ),
                warmup=int(
                    _number(
                        table.get("warmup", 1 if model_name else 2),
                        f"{where}.warmup",
                        0,
                        100,
                        integer=True,
                    )
                ),
                timeout_s=float(
                    _number(
                        table.get("timeout_s", 300 if model_name else 60),
                        f"{where}.timeout_s",
                        0.1,
                        3600,
                    )
                ),
                min_sample_ms=float(
                    _number(table.get("min_sample_ms", 10), f"{where}.min_sample_ms", 0.001, 10000)
                ),
                budget_ms=None
                if budget is None
                else float(_number(budget, f"{where}.budget_ms", 0.000001, 1e9)),
                env=tuple(sorted(env_raw.items())),
                model=model_name,
                host=host,
                prompts=prompts,
                num_predict=int(
                    _number(
                        table.get("num_predict", 128), f"{where}.num_predict", 1, 4096, integer=True
                    )
                ),
                seed=int(
                    _number(table.get("seed", 0), f"{where}.seed", 0, 2**31 - 1, integer=True)
                ),
                temperature=float(
                    _number(table.get("temperature", 0), f"{where}.temperature", 0, 2)
                ),
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
