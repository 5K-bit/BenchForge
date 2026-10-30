# ADR 0005: Benchmark local models through Ollama's HTTP API

**Status:** accepted

Comparing local models is a common reason to benchmark. Ollama serves them over a local HTTP API that reports its own durations (`eval_duration`, `prompt_eval_duration`, `load_duration`) and what is loaded (`/api/ps`). BenchForge calls it with the standard library, so there is still no runtime dependency.

- A sample is one pass over a fixed prompt list, in nanoseconds per generated token. That is a "lower is better" time like every other sample, so the ratio, rank test and bootstrap apply unchanged.
- Fixed seed and temperature 0 make passes comparable; a hash of the output flags when they were not.
- Durations are Ollama's, not wall-clock around the request, so network and JSON overhead stay out of the number.
- The host must be loopback unless the suite says `allow_remote = true`, because prompts may be private.

**Consequence:** speed only; no quality scoring. The client is tested against a fake server, and a real-Ollama run is still to be recorded.
