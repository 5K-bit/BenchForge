from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from benchforge import render
from benchforge.errors import BenchForgeError
from benchforge.model import Bench, parse_suite
from benchforge.ollama import OllamaBackend, measure_model
from benchforge.resultfile import BenchResult, ResultFile, read_result, to_json, write_result
from benchforge.runner import run_suite


def suite_with(**extra: Any) -> dict[str, Any]:
    table: dict[str, Any] = {"id": "m", "model": "llama3.2:3b", "prompts": ["Say hi."]}
    table.update(extra)
    return {"suite": {"name": "s"}, "bench": [table]}


def bench(**extra: Any) -> Bench:
    return parse_suite(suite_with(**extra)).benches[0]


# ---- suite validation --------------------------------------------------------------------------


def test_defaults_for_a_model_bench() -> None:
    b = bench()
    assert (b.kind, b.host, b.runs, b.warmup, b.timeout_s) == (
        "model",
        "http://127.0.0.1:11434",
        5,
        1,
        300.0,
    )
    assert (b.num_predict, b.seed, b.temperature, b.prompts) == (128, 0, 0.0, ("Say hi.",))


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"host": "http://example.com:11434"}, "not this machine"),
        ({"host": "http://user:pw@127.0.0.1:11434"}, "just a scheme"),
        ({"host": "http://127.0.0.1:11434/api"}, "just a scheme"),
        ({"host": "ftp://127.0.0.1"}, "must look like"),
        ({"host": "http://127.0.0.1:99999"}, "not a valid URL"),
        ({"model": "bad name; rm"}, "must look like"),
        ({"model": 3}, "must look like"),
        ({"prompts": []}, "prompts"),
        ({"prompts": ["ok", ""]}, "prompts"),
        ({"prompts": ["x" * 8001]}, "prompts"),
        ({"prompts": "just one"}, "prompts"),
        ({"allow_remote": "yes"}, "true or false"),
        ({"num_predict": 0}, "num_predict"),
        ({"temperature": 5}, "temperature"),
        ({"seed": -1}, "seed"),
    ],
)
def test_bad_model_benches(extra: dict[str, Any], message: str) -> None:
    with pytest.raises(BenchForgeError, match=message):
        parse_suite(suite_with(**extra))


def test_remote_host_needs_an_explicit_opt_in() -> None:
    assert bench(host="http://gpu-box:11434", allow_remote=True).host == "http://gpu-box:11434"
    assert bench(host="http://[::1]:11434").host == "http://[::1]:11434"
    assert bench(host="http://localhost/").host == "http://localhost"


def test_exactly_one_kind_and_model_only_keys() -> None:
    both = suite_with(cmd=["python", "-c", "pass"])
    with pytest.raises(BenchForgeError, match="exactly one"):
        parse_suite(both)
    cmd_with_prompts = {
        "suite": {"name": "s"},
        "bench": [{"id": "c", "cmd": ["python", "-c", "pass"], "prompts": ["x"]}],
    }
    with pytest.raises(BenchForgeError, match="only apply to a 'model'"):
        parse_suite(cmd_with_prompts)


# ---- measurement, with a fake backend ---------------------------------------------------------


class FakeBackend:
    def __init__(self, docs: list[dict[str, Any]], ps: dict[str, Any] | None = None) -> None:
        self.docs = docs
        self.ps = ps if ps is not None else {"models": []}
        self.calls = 0

    def generate(self, bench: Bench, prompt: str) -> dict[str, Any]:
        doc = self.docs[self.calls % len(self.docs)]
        self.calls += 1
        return doc

    def loaded(self, bench: Bench) -> dict[str, Any]:
        return self.ps


def reply(tokens: int = 100, ms: int = 1000, text: str = "hello") -> dict[str, Any]:
    return {
        "response": text,
        "eval_count": tokens,
        "eval_duration": ms * 1_000_000,
        "prompt_eval_count": 20,
        "prompt_eval_duration": 200_000_000,
        "load_duration": 50_000_000,
    }


def test_samples_are_nanoseconds_per_generated_token() -> None:
    fake = FakeBackend(
        [reply(100, 1000)],
        {"models": [{"name": "llama3.2:3b", "size": 4_000_000_000, "size_vram": 3_000_000_000}]},
    )
    samples, metrics = measure_model(bench(runs=3), fake, 3, 1)
    assert samples == [10_000_000] * 3
    assert fake.calls == 4  # one warm-up, three measured
    assert metrics["tokens_per_s_median"] == 100.0
    assert metrics["first_token_ms_median"] == 250.0
    assert metrics["prompt_tokens_per_s_median"] == 100.0
    assert metrics["generated_tokens_per_pass"] == 100
    assert metrics["output_stable"] == "yes"
    assert metrics["model_memory_bytes"] == 4_000_000_000
    assert metrics["model_vram_bytes"] == 3_000_000_000


def test_memory_matches_an_untagged_name_and_ignores_junk() -> None:
    ps = {
        "models": ["junk", {"name": "other:1b", "size": 1}, {"name": "llama3.2:latest", "size": 7}]
    }
    _, metrics = measure_model(bench(model="llama3.2"), FakeBackend([reply()], ps), 1, 0)
    assert metrics["model_memory_bytes"] == 7
    _, none = measure_model(bench(), FakeBackend([reply()], {"models": "x"}), 1, 0)
    assert "model_memory_bytes" not in none


def test_changing_output_is_flagged() -> None:
    fake = FakeBackend([reply(text="a"), reply(text="b")])
    _, metrics = measure_model(bench(), fake, 2, 0)
    assert metrics["output_stable"] == "no"


def test_no_tokens_and_bad_counts_are_errors() -> None:
    with pytest.raises(BenchForgeError, match="no generated tokens"):
        measure_model(bench(), FakeBackend([reply(0, 0)]), 1, 0)
    bad = reply()
    bad["eval_count"] = "many"
    with pytest.raises(BenchForgeError, match="bad 'eval_count'"):
        measure_model(bench(), FakeBackend([bad]), 1, 0)


# ---- a real HTTP round trip against a fake Ollama ---------------------------------------------


class Handler(BaseHTTPRequestHandler):
    seen: list[dict[str, Any]] = []
    mode = "ok"

    def log_message(self, *_: Any) -> None:  # keep test output quiet
        pass

    def _send(self, code: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send(200, json.dumps({"models": [{"name": "llama3.2:3b", "size": 123}]}).encode())

    def do_POST(self) -> None:
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Handler.seen.append(payload)
        if Handler.mode == "missing":
            self._send(404, b'{"error":"model not found"}')
        elif Handler.mode == "redirect":
            self._send(302, b"", {"Location": "http://example.invalid/"})
        elif Handler.mode == "html":
            self._send(200, b"<html>nope</html>")
        elif Handler.mode == "list":
            self._send(200, b"[1]")
        elif Handler.mode == "huge":
            self._send(200, b" " * ((8 << 20) + 5))
        elif Handler.mode == "error":
            self._send(500, b"boom")
        else:
            self._send(200, json.dumps(reply()).encode())


@pytest.fixture
def server() -> Iterator[str]:
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    Handler.seen = []
    Handler.mode = "ok"
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_end_to_end_through_run_suite(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")  # must be ignored for a local model
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    suite = parse_suite(suite_with(host=server, runs=2, num_predict=16, seed=7, temperature=0))
    result = run_suite(suite, tmp_path)
    (res,) = result.results
    assert res.error is None and res.kind == "model" and len(res.samples) == 2
    assert res.metrics["model_memory_bytes"] == 123
    sent = Handler.seen[0]
    assert sent["stream"] is False and sent["model"] == "llama3.2:3b"
    assert sent["options"] == {"temperature": 0.0, "seed": 7, "num_predict": 16}
    text = render.show_text(result)
    assert (
        "100.0 tokens/s" in text
        and "first token 250.0 ms" in text
        and "per generated token" in text
    )


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("missing", "ollama pull"),
        ("redirect", "HTTP 302"),
        ("html", "not JSON"),
        ("list", "unexpected answer"),
        ("huge", "larger than 8 MiB"),
        ("error", "HTTP 500"),
    ],
)
def test_server_misbehaviour_is_reported_not_raised(
    server: str, tmp_path: Path, mode: str, message: str
) -> None:
    Handler.mode = mode
    suite = parse_suite(suite_with(host=server, runs=1, warmup=0))
    (res,) = run_suite(suite, tmp_path).results
    assert res.error is not None and message in res.error and not res.samples


def test_nothing_listening(tmp_path: Path) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    suite = parse_suite(suite_with(host=f"http://127.0.0.1:{port}", runs=1, warmup=0))
    (res,) = run_suite(suite, tmp_path).results
    assert (
        res.error is not None and "cannot reach Ollama" in res.error and "ollama serve" in res.error
    )


def test_backend_can_be_replaced(tmp_path: Path) -> None:
    result = run_suite(parse_suite(suite_with(runs=2)), tmp_path, backend=FakeBackend([reply()]))
    assert result.results[0].samples == (10_000_000, 10_000_000)
    assert isinstance(OllamaBackend(), OllamaBackend)


# ---- result files ------------------------------------------------------------------------------


def test_metrics_round_trip_and_old_files_are_unchanged(tmp_path: Path) -> None:
    with_metrics = BenchResult(
        "m",
        "M",
        "model",
        1,
        (5, 6),
        None,
        None,
        {"tokens_per_s_median": 1.5, "output_stable": "yes"},
    )
    plain = BenchResult("p", "P", "command", 1, (5, 6))
    result = ResultFile("s", "2026-10-29T00:00:00Z", {"a": "b"}, (with_metrics, plain))
    path = tmp_path / "r.json"
    write_result(path, result)
    assert read_result(path) == result
    doc = json.loads(to_json(result))
    assert "metrics" in doc["benchmarks"][0] and "metrics" not in doc["benchmarks"][1]


@pytest.mark.parametrize(
    "bad", [[1], {"k": True}, {"k": [1]}, {"k": "x" * 201}, {f"k{i}": 1 for i in range(33)}]
)
def test_bad_metrics_are_rejected(tmp_path: Path, bad: Any) -> None:
    result = ResultFile("s", "t", {}, (BenchResult("m", "M", "model", 1, (5,)),))
    doc = json.loads(to_json(result))
    doc["benchmarks"][0]["metrics"] = bad
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(BenchForgeError, match="metric"):
        read_result(path)


def test_varied_output_shows_in_the_report() -> None:
    res = BenchResult("m", "M", "model", 1, (10_000_000,), None, None, {"output_stable": "no"})
    text = render.show_text(ResultFile("s", "t", {}, (res,)))
    assert "OUTPUT VARIED" in text
