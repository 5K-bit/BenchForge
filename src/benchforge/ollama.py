"""Time a local model through Ollama's HTTP API (standard library only).

A model benchmark runs a fixed list of prompts, one request each, with a fixed seed and
temperature 0. One *sample* is one pass over all prompts, expressed as nanoseconds per generated
token (lower is better, so ``compare`` works unchanged). The durations are the ones Ollama
reports for itself (``eval_duration``, ``prompt_eval_duration``, ``load_duration``), not wall
clock around the HTTP call. Memory is what Ollama says the loaded model occupies (``/api/ps``).
"""

from __future__ import annotations

import hashlib
import json
import statistics
import urllib.error
import urllib.request
from typing import Any, Protocol

from .errors import BenchForgeError
from .model import Bench

MAX_RESPONSE_BYTES = 8 << 20
Metrics = dict[str, float | int | str]


class Backend(Protocol):
    def generate(self, bench: Bench, prompt: str) -> dict[str, Any]: ...

    def loaded(self, bench: Bench) -> dict[str, Any]: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class OllamaBackend:
    """Talks to Ollama. Ignores proxy settings and refuses redirects."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _post(self, bench: Bench, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - scheme checked in check_host
            bench.host + path,
            data=data,
            method="GET" if data is None else "POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=bench.timeout_s) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise BenchForgeError(
                    f"model {bench.model!r} not found on {bench.host} "
                    f"(try: ollama pull {bench.model})"
                ) from None
            raise BenchForgeError(f"{bench.host}{path} answered HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise BenchForgeError(
                f"cannot reach Ollama at {bench.host}: {reason} (is 'ollama serve' running?)"
            ) from None
        if len(body) > MAX_RESPONSE_BYTES:
            raise BenchForgeError(f"{bench.host}{path}: response larger than 8 MiB")
        try:
            doc = json.loads(body)
        except ValueError:
            raise BenchForgeError(f"{bench.host}{path}: answer was not JSON") from None
        if not isinstance(doc, dict):
            raise BenchForgeError(f"{bench.host}{path}: unexpected answer")
        return doc

    def generate(self, bench: Bench, prompt: str) -> dict[str, Any]:
        return self._post(
            bench,
            "/api/generate",
            {
                "model": bench.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": bench.temperature,
                    "seed": bench.seed,
                    "num_predict": bench.num_predict,
                },
            },
        )

    def loaded(self, bench: Bench) -> dict[str, Any]:
        return self._post(bench, "/api/ps", None)


def _count(doc: dict[str, Any], key: str, bench: Bench) -> int:
    value = doc.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BenchForgeError(f"{bench.model}: Ollama reported a bad {key!r}")
    return value


def _memory(doc: dict[str, Any], bench: Bench) -> Metrics:
    models = doc.get("models")
    if not isinstance(models, list):
        return {}
    for entry in models:
        if not isinstance(entry, dict):
            continue
        names = {entry.get("name"), entry.get("model")}
        wanted = {bench.model, bench.model if ":" in bench.model else bench.model + ":latest"}
        if names & wanted:
            out: Metrics = {}
            for src, dst in (("size", "model_memory_bytes"), ("size_vram", "model_vram_bytes")):
                value = entry.get(src)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    out[dst] = value
            return out
    return {}


def measure_model(
    bench: Bench, backend: Backend, runs: int, warmup: int
) -> tuple[list[int], Metrics]:
    """Warm up, then take ``runs`` passes over the prompts. Returns samples and extra metrics."""
    for _ in range(warmup):
        for prompt in bench.prompts:
            backend.generate(bench, prompt)
    samples: list[int] = []
    first_token_ms: list[float] = []
    prompt_rate: list[float] = []
    digests: list[str] = []
    tokens_per_pass = 0
    for _ in range(runs):
        tokens = eval_ns = prompt_tokens = prompt_ns = load_ns = 0
        text = hashlib.sha256()
        for prompt in bench.prompts:
            doc = backend.generate(bench, prompt)
            tokens += _count(doc, "eval_count", bench)
            eval_ns += _count(doc, "eval_duration", bench)
            prompt_tokens += _count(doc, "prompt_eval_count", bench)
            prompt_ns += _count(doc, "prompt_eval_duration", bench)
            load_ns += _count(doc, "load_duration", bench)
            response = doc.get("response", "")
            text.update((response if isinstance(response, str) else "").encode("utf-8"))
            text.update(b"\x00")
        if tokens == 0 or eval_ns == 0:
            raise BenchForgeError(f"{bench.model}: Ollama reported no generated tokens")
        samples.append(max(1, eval_ns // tokens))
        count = len(bench.prompts)
        first_token_ms.append((prompt_ns + load_ns) / count / 1e6)
        if prompt_ns:
            prompt_rate.append(prompt_tokens / (prompt_ns / 1e9))
        digests.append(text.hexdigest())
        tokens_per_pass = tokens
    metrics: Metrics = {
        "tokens_per_s_median": round(1e9 / statistics.median(samples), 3),
        "first_token_ms_median": round(statistics.median(first_token_ms), 3),
        "generated_tokens_per_pass": tokens_per_pass,
        "prompts": len(bench.prompts),
        "output_sha256": digests[0],
        "output_stable": "yes" if len(set(digests)) == 1 else "no",
    }
    if prompt_rate:
        metrics["prompt_tokens_per_s_median"] = round(statistics.median(prompt_rate), 3)
    metrics.update(_memory(backend.loaded(bench), bench))
    return samples, metrics
