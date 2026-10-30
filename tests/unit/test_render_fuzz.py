from __future__ import annotations

import json
import os
import random
from pathlib import Path

import pytest

from benchforge import render
from benchforge.compare import compare
from benchforge.errors import BenchForgeError
from benchforge.resultfile import BenchResult, ResultFile, read_result

from ..conftest import DEMO

GOLDEN = Path(__file__).resolve().parent.parent / "fixtures"


def demo_comparison():  # type: ignore[no-untyped-def]
    return compare(read_result(DEMO / "baseline.json"), read_result(DEMO / "candidate.json"))


@pytest.mark.parametrize(
    ("name", "make"),
    [
        ("demo.compare.txt", render.compare_text),
        ("demo.compare.md", render.compare_markdown),
        ("demo.compare.html", render.compare_html),
        ("demo.compare.json", render.compare_json),
    ],
)
def test_golden(name: str, make) -> None:  # type: ignore[no-untyped-def]
    got = make(demo_comparison())
    path = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(got, encoding="utf-8", newline="\n")
    assert got == path.read_text(encoding="utf-8")


def test_show_text_and_json() -> None:
    r = read_result(DEMO / "candidate.json")
    text = render.show_text(r)
    assert "compile-rules: median 6.96 ms" in text and "n=30" in text
    assert json.loads(render.show_json(r))["suite"] == "Orchard Sync (synthetic)"


def test_show_text_failures_and_budgets() -> None:
    r = ResultFile(
        "S",
        "t",
        {},
        (
            BenchResult("bad", "bad", "command", 1, (), "boom"),
            BenchResult("none", "none", "command", 1, ()),
            BenchResult("over", "over", "command", 1, (3_000_000,) * 5, budget_ms=2),
            BenchResult("fine", "fine", "command", 1, (1_000_000,) * 5, budget_ms=2),
        ),
    )
    text = render.show_text(r)
    assert "bad: FAILED: boom" in text and "none: no samples" in text
    assert "budget 2 ms: OVER" in text and "budget 2 ms: ok" in text
    assert render.over_budget(r.results[2]) and not render.over_budget(r.results[3])
    assert not render.over_budget(r.results[1]) and not render.over_budget(r.results[0])


def test_fmt_ns() -> None:
    assert [render.fmt_ns(v) for v in (5, 1500, 2_500_000, 3_200_000_000)] == [
        "5 ns",
        "1.50 us",
        "2.50 ms",
        "3.20 s",
    ]


HOSTILE = "<script>alert(1)</script> [x](javascript:alert(1)) | **b** `c` & <img src=x onerror=1>"


def test_hostile_titles_are_inert() -> None:
    def mk(s: tuple[int, ...]) -> ResultFile:
        return ResultFile(
            HOSTILE, "t", {"k": HOSTILE}, (BenchResult("a", HOSTILE, "command", 1, s),)
        )

    cmp = compare(mk((10, 11, 12, 13, 14, 15)), mk((10, 11, 12, 13, 14, 15)))
    page = render.compare_html(cmp)
    body = render.compare_markdown(cmp)
    assert "<script>" not in page and "<img" not in page
    assert "<script" not in body and "<img" not in body and "](javascript" not in body
    assert render.md("a\nb|c") == "a b\\|c"
    assert json.loads(render.compare_json(cmp))["suite"] == HOSTILE


def test_fuzzed_result_files_never_crash(tmp_path: Path) -> None:
    rng = random.Random(11)
    seed = (DEMO / "candidate.json").read_bytes()
    base = read_result(DEMO / "baseline.json")
    for _ in range(300):
        data = bytearray(seed)
        for _ in range(rng.randint(1, 6)):
            data[rng.randrange(len(data))] = rng.randrange(256)
        f = tmp_path / "f.json"
        f.write_bytes(bytes(data))
        try:
            cand = read_result(f)
        except BenchForgeError:
            continue
        cmp = compare(base, cand)
        for make in (
            render.compare_text,
            render.compare_markdown,
            render.compare_html,
            render.compare_json,
            lambda c: render.show_text(c.cand),
        ):
            assert make(cmp)
