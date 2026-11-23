# Reproducible Observability Benchmark (`evals/`)

Run the benchmark locally to compare common naive AI-generated setups against
the self-contained starter implementations bundled in `vibe-observability`:

```bash
python3 evals/run_benchmark.py
```

All naive fixtures are generated cleanly inside a temporary directory at
runtime (no fake secrets committed to Git history) and scored by the exact same
zero-dependency auditor (`skills/vibe-observability/scripts/audit_observability.py`).
