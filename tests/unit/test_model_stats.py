from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from benchforge.errors import BenchForgeError
from benchforge.model import load_suite, parse_suite, safe_relpath
from benchforge.stats import (
    bootstrap_ratio_ci,
    mann_whitney_p,
    percentile,
    quartiles,
    summarize,
)


def suite(extra: str = "") -> dict:
    return tomllib.loads(
        f'[suite]\nname = "S"\n[[bench]]\nid = "a"\ncmd = ["python", "-c", "pass"]\n{extra}\n'
    )


def test_valid_suite() -> None:
    s = parse_suite(
        suite('runs = 5\nwarmup = 0\ntimeout_s = 2\nbudget_ms = 1.5\nenv = {A = "b"}\ncwd = "sub"')
    )
    b = s.benches[0]
    assert (b.kind, b.runs, b.warmup, b.budget_ms, b.env, b.cwd) == (
        "command",
        5,
        0,
        1.5,
        (("A", "b"),),
        "sub",
    )
    py = parse_suite(
        tomllib.loads(
            '[suite]\nname = "S"\n[[bench]]\nid = "p"\npython = "m.n:f"\npythonpath = ["src"]\n'
        )
    )
    assert py.benches[0].kind == "callable" and py.benches[0].pythonpath == ("src",)


@pytest.mark.parametrize("bad", ["", "/x", "a\\b", "C:/x", "../x", "a//b", "a\x00", "x" * 300])
def test_unsafe_paths(bad: str) -> None:
    with pytest.raises(BenchForgeError):
        safe_relpath(bad, "p")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(x=1),
        lambda d: d.pop("suite"),
        lambda d: d["suite"].update(extra=1),
        lambda d: d["suite"].update(name=""),
        lambda d: d.update(bench={"id": "a"}),
        lambda d: d["bench"].append(dict(d["bench"][0])),
        lambda d: d["bench"].__setitem__(0, "x"),
        lambda d: d["bench"][0].update(id="Bad Id"),
        lambda d: d["bench"][0].update(wat=1),
        lambda d: d["bench"][0].update(python="m:f"),  # both cmd and python
        lambda d: d["bench"][0].pop("cmd"),  # neither
        lambda d: d["bench"][0].update(cmd="python -c pass"),
        lambda d: d["bench"][0].update(cmd=[]),
        lambda d: d["bench"][0].update(runs=0),
        lambda d: d["bench"][0].update(runs=True),
        lambda d: d["bench"][0].update(warmup=1000),
        lambda d: d["bench"][0].update(timeout_s=0),
        lambda d: d["bench"][0].update(budget_ms=-1),
        lambda d: d["bench"][0].update(pythonpath="src"),
        lambda d: d["bench"][0].update(pythonpath=["../x"]),
        lambda d: d["bench"][0].update(env={"bad key": "x"}),
        lambda d: d["bench"][0].update(env={"A": 1}),
        lambda d: d["bench"][0].update(env="x"),
        lambda d: d["bench"][0].update(title=""),
        lambda d: d["bench"][0].update(cwd="../up"),
    ],
)
def test_invalid_suites(mutate) -> None:
    data = suite()
    mutate(data)
    with pytest.raises(BenchForgeError):
        parse_suite(data)


def test_bad_python_target() -> None:
    d = tomllib.loads('[suite]\nname = "S"\n[[bench]]\nid = "p"\npython = "not a target"\n')
    with pytest.raises(BenchForgeError, match="module:function"):
        parse_suite(d)


def test_load_suite_errors(tmp_path: Path) -> None:
    with pytest.raises(BenchForgeError, match="not found"):
        load_suite(tmp_path / "none.toml")
    bad = tmp_path / "b.toml"
    bad.write_text("[suite\n", encoding="utf-8")
    with pytest.raises(BenchForgeError, match="not valid TOML"):
        load_suite(bad)
    bad.write_bytes(b"\xff\xfe")
    with pytest.raises(BenchForgeError, match="not valid TOML"):
        load_suite(bad)
    bad.write_text("#" * (2 << 20), encoding="utf-8")
    with pytest.raises(BenchForgeError, match="larger"):
        load_suite(bad)
    with pytest.raises(BenchForgeError):  # below a file: not-a-directory or not-found by platform
        load_suite(bad / "x")


def test_summarize_odd_even_and_outliers() -> None:
    s = summarize([1, 2, 3, 4, 5, 6, 7, 8, 100])
    assert (s.n, s.minimum, s.median, s.outliers) == (9, 1, 5, 1)
    assert s.mean == pytest.approx(136 / 9) and s.mad == 2 and s.p95 == 100
    assert summarize([1, 2, 3, 4, 100]).outliers == 0  # 100 is inside the fence for n=5
    e = summarize([10, 20])
    assert e.median == 15 and e.stdev > 0
    one = summarize([7])
    assert one.stdev == 0 and one.median == 7 and one.outliers == 0
    with pytest.raises(ValueError):
        summarize([])


def test_percentile_and_quartiles() -> None:
    assert percentile([1, 2, 3, 4], 50) == 2 and percentile([1, 2, 3, 4], 100) == 4
    assert percentile([5], 1) == 5
    assert quartiles([1, 2, 3, 4, 5, 6, 7, 8]) == (2.5, 6.5)
    assert quartiles([1, 2, 3]) == (1.0, 3.0)
    assert quartiles([4]) == (4.0, 4.0)


def test_mann_whitney_known_values() -> None:
    assert mann_whitney_p([1, 2, 3, 4, 5], [6, 7, 8, 9, 10]) == pytest.approx(0.0122, abs=5e-4)
    assert mann_whitney_p([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) > 0.9
    assert mann_whitney_p([5, 5, 5], [5, 5, 5]) == 1.0  # all tied: no variance
    a, b = [1.0, 3, 5, 7, 9, 11], [2.0, 4, 6, 8, 10, 12]
    assert mann_whitney_p(a, b) == pytest.approx(mann_whitney_p(b, a))


def test_bootstrap_is_deterministic_and_sensible() -> None:
    base = [100.0 + i for i in range(20)]
    same = bootstrap_ratio_ci(base, base)
    assert same == bootstrap_ratio_ci(base, base)
    assert same[0] <= 1 <= same[1]
    slower = bootstrap_ratio_ci(base, [v * 2 for v in base])
    assert slower[0] > 1.8
    assert all(x != x for x in bootstrap_ratio_ci([0.0] * 5, [1.0] * 5))  # NaN: no usable ratio
