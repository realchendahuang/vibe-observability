# Contributing to `vibe-observability`

Contributions that raise the bar for real-world observability practices across
modern stacks are welcome!

## Principles

1. **Zero external runtime dependencies in `scripts/`**: Every bundled Python
   tool (`audit_observability.py`, `verify_live.py`, `pull_signals.py`) must run
   on Python 3.9+ stdlib only so any agent or developer can invoke it instantly.
2. **Self-contained skills**: Everything a skill references (docs, examples,
   scripts) must live inside `skills/<skill_name>/` so `--copy` and
   `npx skills add` installations never break links.
3. **Framework-neutral by default**: Put framework-specific guidance into
   progressive-disclosure `references/stack-*.md` files instead of bloating
   `SKILL.md`.
4. **Evidence over dogma**: New audit rules should catch real production bugs
   with low false-positive rates and include regression tests in `tests/`.

## Running Tests Locally

```bash
python3 -m unittest discover -s tests -v
bash ./install.sh --target all --dry-run
```
