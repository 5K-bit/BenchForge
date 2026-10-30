from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from benchforge.cli import main

from ..conftest import DEMO, ROOT


def run(*argv: str) -> int:
    return main(list(argv))


@pytest.fixture
def project(tmp_path: Path) -> Path:
    shutil.copytree(DEMO, tmp_path / "p")
    p = tmp_path / "p"
    (p / "benchforge.toml").write_text(
        '[suite]\nname = "T"\n[[bench]]\nid = "fast"\npython = "workload:hash_blob"\n'
        'pythonpath = ["."]\nruns = 3\nwarmup = 0\nmin_sample_ms = 0.01\n'
        f'[[bench]]\nid = "spawn"\ncmd = ["{Path(sys.executable).as_posix()}", "-c", "pass"]\n'
        "runs = 2\nwarmup = 0\n",
        encoding="utf-8",
    )
    return p


def test_init_refuses_to_overwrite(tmp_path: Path) -> None:
    assert run("init", "-C", str(tmp_path)) == 0
    assert run("init", "-C", str(tmp_path)) == 1
    assert run("init", "-C", str(tmp_path), "--force") == 0


def test_run_show_compare_end_to_end(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = project / "a.json"
    assert run("run", "-C", str(project), "--out", str(out)) == 0
    text = capsys.readouterr().out
    assert "fast: median" in text and "spawn: median" in text
    assert run("run", "-C", str(project), "--out", str(project / "b.json"), "--only", "fast") == 0
    capsys.readouterr()
    assert run("show", str(out)) == 0 and "BenchForge: T" in capsys.readouterr().out
    assert run("show", str(out), "--format", "json") == 0
    assert json.loads(capsys.readouterr().out)["format"] == 1
    assert run("compare", str(out), str(project / "b.json")) == 0


def test_run_exit_codes(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = project / "benchforge.toml"
    cfg.write_text(
        '[suite]\nname = "T"\n[[bench]]\nid = "slow"\npython = "workload:hash_blob"\n'
        'pythonpath = ["."]\nruns = 3\nwarmup = 0\nbudget_ms = 0.000001\n',
        encoding="utf-8",
    )
    assert run("run", "-C", str(project)) == 2  # over budget
    assert "OVER" in capsys.readouterr().out
    cfg.write_text(
        f'[suite]\nname = "T"\n[[bench]]\nid = "x"\n'
        f'cmd = ["{Path(sys.executable).as_posix()}", "-c", "raise SystemExit(4)"]\n'
        "runs = 1\nwarmup = 0\n",
        encoding="utf-8",
    )
    assert run("run", "-C", str(project)) == 1  # a failing benchmark is an error
    assert "FAILED" in capsys.readouterr().out


def test_cli_errors_exit_1(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("run", "-C", str(tmp_path / "nope")) == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run("run", "-C", str(empty)) == 1
    assert run("run", "-C", str(project), "--runs", "0") == 1
    assert run("run", "-C", str(project), "--warmup", "-1") == 1
    assert run("run", "-C", str(project), "--only", "zzz") == 1
    assert run("compare", str(project / "x.json"), str(project / "y.json")) == 1
    assert (
        run("compare", str(DEMO / "baseline.json"), str(DEMO / "candidate.json"), "--alpha", "2")
        == 1
    )
    assert run("show", str(project / "x.json")) == 1
    assert (
        run(
            "compare",
            str(DEMO / "baseline.json"),
            str(DEMO / "candidate.json"),
            "--out",
            str(project / "no" / "x"),
        )
        == 1
    )
    assert "benchforge:" in capsys.readouterr().err


def test_compare_formats_and_gate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base, cand = str(DEMO / "baseline.json"), str(DEMO / "candidate.json")
    assert run("compare", base, cand) == 0
    assert run("compare", base, cand, "--fail-on-regression") == 2
    assert run("compare", base, base, "--fail-on-regression") == 0
    assert run("compare", base, cand, "--threshold", "0.5", "--fail-on-regression") == 0
    for fmt, marker in (("md", "# BenchForge"), ("html", "<!doctype html>"), ("json", '"rows"')):
        capsys.readouterr()
        assert run("compare", base, cand, "--format", fmt) == 0
        assert marker in capsys.readouterr().out
    out = tmp_path / "c.md"
    assert run("compare", base, cand, "--format", "md", "--out", str(out)) == 0
    assert out.read_text(encoding="utf-8").startswith("# BenchForge")


def test_python_dash_m_and_version() -> None:
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "benchforge", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0 and proc.stdout.startswith("benchforge 0.1.0")


def test_synthetic_files_match_their_generator(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "examples"))
    try:
        import make_synthetic
    finally:
        sys.path.remove(str(ROOT / "examples"))
    base, cand = make_synthetic.build()
    assert (DEMO / "baseline.json").read_text(encoding="utf-8") == base
    assert (DEMO / "candidate.json").read_text(encoding="utf-8") == cand


def test_acceptance_reproduces_recorded_evidence(tmp_path: Path) -> None:
    subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "examples" / "acceptance.py"), "--out", str(tmp_path)],
        check=False,
        capture_output=True,
    )
    recorded = ROOT / "docs" / "evidence"
    for name in ("acceptance-transcript.txt", "compare.md", "compare.html", "compare.json"):
        assert (tmp_path / name).read_text(encoding="utf-8") == (recorded / name).read_text(
            encoding="utf-8"
        ), name


def test_model_demo_transcript_is_reproducible(tmp_path: Path) -> None:
    script = ROOT / "examples" / "model_demo.py"
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(script), "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    recorded = (ROOT / "docs" / "evidence" / "model-transcript.txt").read_text(encoding="utf-8")
    fresh = (tmp_path / "model-transcript.txt").read_text(encoding="utf-8")
    assert fresh.replace("\r\n", "\n") == recorded.replace("\r\n", "\n")
    assert "regression   stand-in" in fresh
