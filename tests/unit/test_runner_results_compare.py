from __future__ import annotations

import json
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benchforge import resultfile
from benchforge.compare import compare
from benchforge.errors import BenchForgeError
from benchforge.model import Bench, parse_suite
from benchforge.resultfile import BenchResult, ResultFile, read_result, to_json, write_result
from benchforge.runner import (
    load_callable,
    measure_callable,
    run_bench,
    run_command,
    run_suite,
)


def bench(extra: str = "", head: str = 'cmd = ["x"]') -> Bench:
    d = tomllib.loads(f'[suite]\nname = "S"\n[[bench]]\nid = "a"\n{head}\n{extra}\n')
    return parse_suite(d).benches[0]


class Clock:
    """A fake timer that advances by a fixed step on every call."""

    def __init__(self, step: int) -> None:
        self.now, self.step = 0, step

    def __call__(self) -> int:
        self.now += self.step
        return self.now


def test_measure_callable_calibrates_loops_with_fake_clock() -> None:
    now = [0]

    def work() -> None:
        now[0] += 100_000  # each call "takes" 0.1 ms

    b = bench("min_sample_ms = 1", 'python = "m:f"')
    loops, samples = measure_callable(work, b, runs=3, warmup=1, timer=lambda: now[0])
    assert loops == 16  # first power of two whose total reaches 1 ms
    assert samples == [100_000, 100_000, 100_000]


def test_run_bench_command_with_injected_executor() -> None:
    seen: list[str] = []
    res = run_bench(
        bench(),
        Path("."),
        runs=3,
        warmup=2,
        timer=Clock(1000),
        executor=lambda b, r: seen.append(b.id),
    )
    assert res.error is None and len(res.samples) == 3 and len(seen) == 5
    assert res.samples == (1000, 1000, 1000)


def test_run_bench_records_errors() -> None:
    def boom(b: Bench, r: Path) -> None:
        raise BenchForgeError("nope")

    assert run_bench(bench(), Path("."), executor=boom).error == "nope"

    def weird(b: Bench, r: Path) -> None:
        raise RuntimeError("odd")

    assert run_bench(bench(), Path("."), executor=weird).error == "RuntimeError: odd"


def test_run_command_real_processes(tmp_path: Path) -> None:
    ok = bench(head=f'cmd = [{json.dumps(sys.executable)}, "-c", "pass"]')
    run_command(ok, tmp_path)
    bad = bench(head=f'cmd = [{json.dumps(sys.executable)}, "-c", "import sys; sys.exit(3)"]')
    with pytest.raises(BenchForgeError, match="status 3"):
        run_command(bad, tmp_path)
    slow = bench(
        "timeout_s = 0.2",
        f'cmd = [{json.dumps(sys.executable)}, "-c", "import time; time.sleep(5)"]',
    )
    with pytest.raises(BenchForgeError, match="timed out"):
        run_command(slow, tmp_path)
    with pytest.raises(BenchForgeError, match="could not start"):
        run_command(bench(head='cmd = ["/no/such/program-xyz"]'), tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_cwd_through_a_symlink_cannot_leave_the_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "link").symlink_to(tmp_path)
    b = bench('cwd = "link"', f'cmd = [{json.dumps(sys.executable)}, "-c", "pass"]')
    with pytest.raises(BenchForgeError, match="outside"):
        run_command(b, project)


def test_command_receives_env_and_no_shell(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    code = f"import os; open({str(out)!r}, 'w').write(os.environ['BF_X'] + '|;echo hi')"
    b = bench(
        'env = {BF_X = "1"}', f'cmd = [{json.dumps(sys.executable)}, "-c", {json.dumps(code)}]'
    )
    run_command(b, tmp_path)
    assert out.read_text() == "1|;echo hi"


def test_load_callable(tmp_path: Path) -> None:
    (tmp_path / "wl.py").write_text("def f():\n    return 1\nnotfn = 3\n", encoding="utf-8")
    before = list(sys.path)
    func = load_callable(bench(head='python = "wl:f"'), tmp_path)
    assert func() == 1 and sys.path == before
    with pytest.raises(BenchForgeError, match="not callable"):
        load_callable(bench(head='python = "wl:notfn"'), tmp_path)
    with pytest.raises(BenchForgeError, match="cannot import"):
        load_callable(bench(head='python = "missing_mod_xyz:f"'), tmp_path)
    (tmp_path / "bad.py").write_text("raise ValueError('at import')\n", encoding="utf-8")
    with pytest.raises(BenchForgeError, match="at import"):
        load_callable(bench(head='python = "bad:f"'), tmp_path)
    sys.modules.pop("wl", None)
    sys.modules.pop("bad", None)


def test_run_suite_filters_and_stamps(tmp_path: Path) -> None:
    d = tomllib.loads(
        '[suite]\nname = "S"\n[[bench]]\nid = "a"\ncmd = ["x"]\n[[bench]]\nid = "b"\ncmd = ["x"]\n'
    )
    s = parse_suite(d)
    seen: list[str] = []
    res = run_suite(
        s,
        tmp_path,
        only=["b"],
        runs=2,
        warmup=0,
        timer=Clock(5),
        executor=lambda b, r: None,
        now=datetime(2026, 10, 29, 17, 0, 0, tzinfo=UTC),
        progress=seen.append,
    )
    assert [r.id for r in res.results] == ["b"] and seen == ["b"]
    assert res.created == "2026-10-29T17:00:00Z" and "python" in res.environment
    with pytest.raises(BenchForgeError, match="no such benchmark"):
        run_suite(s, tmp_path, only=["zzz"])


def result(samples: tuple[int, ...], rid: str = "a", **kw) -> ResultFile:
    return ResultFile(
        "S",
        "2026-10-29T17:00:00Z",
        {"python": "3.13", "benchforge": "0.1.0"},
        (BenchResult(rid, rid, "command", 1, samples, **kw),),
    )


def test_result_roundtrip_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    r = result((5, 6, 7), budget_ms=2.5)
    write_result(path, r)
    assert read_result(path) == r and not (tmp_path / "r.json.tmp").exists()
    doc = json.loads(to_json(r))

    def broken(mutate) -> None:
        d = json.loads(json.dumps(doc))
        mutate(d)
        path.write_text(json.dumps(d), encoding="utf-8")
        with pytest.raises(BenchForgeError):
            read_result(path)

    broken(lambda d: d.update(format=2))
    broken(lambda d: d.pop("suite"))
    broken(lambda d: d.update(environment=[]))
    broken(lambda d: d.update(benchmarks={}))
    broken(lambda d: d["benchmarks"][0].update(samples=[0]))
    broken(lambda d: d["benchmarks"][0].update(samples=[1.5]))
    broken(lambda d: d["benchmarks"][0].update(samples=[True]))
    broken(lambda d: d["benchmarks"][0].update(samples="x"))
    broken(lambda d: d["benchmarks"][0].update(loops=0))
    broken(lambda d: d["benchmarks"][0].update(budget_ms="x"))
    broken(lambda d: d["benchmarks"][0].update(error=5))
    broken(lambda d: d["benchmarks"].append(dict(d["benchmarks"][0])))
    broken(lambda d: d["environment"].update(x=1))
    path.write_text("nope", encoding="utf-8")
    with pytest.raises(BenchForgeError):
        read_result(path)
    with pytest.raises(BenchForgeError, match="not found"):
        read_result(tmp_path / "none.json")
    with pytest.raises(BenchForgeError):
        read_result(path / "x")


def test_result_size_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "r.json"
    path.write_text("{}" * 5, encoding="utf-8")
    monkeypatch.setattr(resultfile, "MAX_RESULT_BYTES", 3)
    with pytest.raises(BenchForgeError, match="larger"):
        read_result(path)


STEADY = tuple(1000 + (i % 7) * 10 for i in range(20))


def verdict(base: tuple[int, ...], cand: tuple[int, ...], **kw) -> str:
    return compare(result(base), result(cand), **kw).rows[0].verdict


def test_verdicts() -> None:
    assert verdict(STEADY, STEADY) == "unchanged"
    assert verdict(STEADY, tuple(int(v * 1.3) for v in STEADY)) == "regression"
    assert verdict(STEADY, tuple(int(v * 0.7) for v in STEADY)) == "improvement"
    # significant but below the threshold: reported as unchanged, with a different note
    row = compare(result(STEADY), result(tuple(int(v * 1.05) for v in STEADY))).rows[0]
    assert row.verdict == "unchanged" and "within the threshold" in row.note
    assert verdict(STEADY[:3], STEADY[:3]) == "inconclusive"


def test_errored_added_removed_and_environment() -> None:
    err = ResultFile(
        "S", "t", {"python": "3.11"}, (BenchResult("a", "a", "command", 1, (), "boom"),)
    )
    c = compare(err, result(STEADY))
    assert c.rows[0].verdict == "errored" and "baseline run failed" in c.rows[0].note
    assert c.environment_notes == ("python: baseline 3.11, candidate 3.13",)
    empty = ResultFile("S", "t", {}, (BenchResult("a", "a", "command", 1, ()),))
    assert compare(result(STEADY), empty).rows[0].note == "no samples"
    both = compare(result(STEADY, "old"), result(STEADY, "new"))
    assert sorted(r.verdict for r in both.rows) == ["added", "removed"]
    assert compare(result(STEADY), result(tuple(int(v * 2) for v in STEADY))).regressions
