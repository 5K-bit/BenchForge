## Summary

## Testing
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `mypy` passes
- [ ] `python -m pytest --cov` passes
- [ ] Changes to suite or result parsing have a test with a hostile or damaged input
- [ ] No network calls (BenchForge runs what the suite names and writes a report)
- [ ] Golden files and `docs/evidence` regenerated and reviewed (if output changed)
