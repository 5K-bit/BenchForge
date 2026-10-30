"""Show BenchForge's model benchmarks without a real model: a stand-in Ollama server.

    python examples/model_demo.py --out docs/evidence

The stand-in answers with fixed, invented timings (the "candidate" is 25% slower per token), so
the transcript is reproducible byte for byte. It proves the plumbing, the statistics and the
reports; it says nothing about any real model. For real numbers run a suite against Ollama
(see examples/models/benchforge.toml and docs/evidence/real-run.txt for the command style).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PROMPTS = ["Summarise: backups you never restore are a hope.", "List three risks."]
BASE_NS_PER_TOKEN = 20_000_000  # 20 ms per token = 50 tokens/s


def make_server(slowdown: float) -> HTTPServer:
    counter = {"n": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def _json(self, doc: object) -> None:
            body = json.dumps(doc).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self._json({"models": [{"name": "stand-in:1b", "size": 2_147_483_648}]})

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            counter["n"] += 1
            jitter = 1 + 0.01 * (counter["n"] % 5)  # small, deterministic spread
            per_token = int(BASE_NS_PER_TOKEN * slowdown * jitter)
            self._json(
                {
                    "response": "stand-in text",
                    "eval_count": 100,
                    "eval_duration": per_token * 100,
                    "prompt_eval_count": 30,
                    "prompt_eval_duration": 150_000_000,
                    "load_duration": 10_000_000,
                }
            )

    return HTTPServer(("127.0.0.1", 0), Handler)


def toml_for(host: str) -> str:
    prompts = ", ".join(json.dumps(p) for p in PROMPTS)
    return (
        '[suite]\nname = "stand-in model"\n\n[[bench]]\nid = "stand-in"\n'
        f'model = "stand-in:1b"\nhost = "{host}"\nruns = 9\nnum_predict = 100\n'
        f"prompts = [{prompts}]\n"
    )


def cli(lines: list[str], cwd: Path, *args: str, hide: tuple[str, ...] = ()) -> int:
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "benchforge", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    lines.append("$ benchforge " + " ".join(args))
    for text in (proc.stdout, proc.stderr):
        for line in text.splitlines():
            if not any(line.startswith(h) for h in hide):
                lines.append(line)
    lines.append(f"[exit {proc.returncode}]")
    lines.append("")
    return proc.returncode


def record(slowdown: float, name: str, work: Path, lines: list[str]) -> None:
    server = make_server(slowdown)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (work / "benchforge.toml").write_text(
            toml_for(f"http://127.0.0.1:{server.server_port}"), encoding="utf-8"
        )
        hide = ("recorded", "  benchforge", "running", "wrote")
        cli(lines, work, "run", "--out", name, hide=hide)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    out = Path(parser.parse_args(argv).out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Stand-in server with invented timings. "
        "It exercises BenchForge; it measures no real model.",
        "",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        lines.append("== 1. Baseline pass ==")
        record(1.0, "baseline.json", work, lines)
        lines.append("== 2. Candidate pass (the stand-in is now 25% slower per token) ==")
        record(1.25, "candidate.json", work, lines)
        lines.append("== 3. Compare ==")
        code = cli(
            lines,
            work,
            "compare",
            "baseline.json",
            "candidate.json",
            "--fail-on-regression",
            hide=("baseline 20",),
        )
    text = "\n".join(lines) + "\n"
    (out / "model-transcript.txt").write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0 if code == 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
