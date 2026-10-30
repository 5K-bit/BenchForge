# Threat model

BenchForge is a local command line tool. Its inputs are a suite file (which names code to run) and result files (which are only read).

## Assets

- The project folder and the machine that runs the suite.
- The meaning of a verdict: *this difference is, or is not, distinguishable from noise at the stated settings.*
- The reader of a report.

## Actors

- **The suite's author** (trusted: the suite file is code they chose to run).
- **A contributor** who changes a suite file in a pull request (a CI job running `benchforge run` runs their commands).
- **A hostile or damaged result file**, for example one attached to an issue.

## Threats and mitigations

| Threat | Mitigation | Test |
|---|---|---|
| Shell injection through a command | `cmd` is an argument list started without a shell; a `;` in an argument stays an argument | `test_command_receives_env_and_no_shell` |
| Benchmark hangs forever | Per-run timeout, reported as an error for that benchmark | `test_run_command_real_processes` |
| Working directory or import path escapes the project | Relative forward-slash paths only; symlinks that leave the folder are refused | `test_unsafe_paths`, `test_cwd_through_a_symlink_cannot_leave_the_project` |
| A broken benchmark hides the others | Each failure is recorded for that benchmark; the run continues and exits 1 | `test_run_bench_records_errors` |
| Damaged or huge result file | Strict type checks; 64 MiB and 100,000-sample caps; clean error | `test_result_roundtrip_and_validation`, `test_result_size_limits` |
| Markup in a title or environment value reaches a report | Markdown and HTML are escaped; JSON is serialised | `test_hostile_titles_are_inert` |
| Mutated result files crash a renderer | 300 mutated files end in a clean error or a report | `test_fuzzed_result_files_never_crash` |
| A model benchmark sends prompts to an unexpected host | `host` must be loopback unless `allow_remote = true`; no credentials, query or path in the URL | `test_bad_model_benches`, `test_remote_host_needs_an_explicit_opt_in` |
| A local server redirects or is hijacked by a proxy variable | Redirects are refused; `HTTP_PROXY` and friends are ignored for model calls | `test_server_misbehaviour_is_reported_not_raised`, `test_end_to_end_through_run_suite` |
| Oversized, non-JSON or malformed answers from the model server | 8 MiB cap, strict JSON and integer checks, clean error for that benchmark | `test_server_misbehaviour_is_reported_not_raised`, `test_no_tokens_and_bad_counts_are_errors` |
| `compare` or `show` executes something | They only read JSON; no code path imports or runs a benchmark | by construction (see `cli.py`) |

## Not covered

- **Running an untrusted suite.** `benchforge run` executes what the suite says. Review a suite like a build script, and do not run it with secrets in the environment unless you trust it. Environment variables are inherited by commands.
- **Measurement quality.** Wall-clock time on a busy or shared machine is noisy; frequency scaling, caches and other processes move results. BenchForge reports the spread but cannot remove it.
- **Statistical guarantees.** The p-value uses a normal approximation (good from about 10 samples per side); at the default alpha of 0.01 about one comparison in a hundred of identical code can be flagged.
- **Machine differences.** Two result files from different machines are compared if you ask, with a warning; the ratio then measures the machines too.
- **Privacy of result files.** They record the Python version, platform and CPU count. A model benchmark's result file records the model name and a SHA-256 of the output, not the prompts or the text.
- **What a remote Ollama sees.** With `allow_remote = true` your prompts go to that host over whatever transport you configured (plain `http` is unencrypted).
