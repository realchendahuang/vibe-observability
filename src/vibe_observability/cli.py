"""Unified `vibe-obs` entrypoint dispatching to the single-source skill scripts.

Subcommands:
  vibe-obs audit  [path] [...]   -> Static codebase observability audit (OBS-001..016)
  vibe-obs verify <url>  [...]   -> Post-deploy live smoke check (LIVE-001..006)
  vibe-obs pull          [...]   -> Read-only Sentry/PostHog/Clarity/Prometheus/Job brief
  vibe-obs version               -> Print CLI version
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional, Tuple

from vibe_observability import __version__

SCRIPT_MAP: Dict[str, Tuple[str, str]] = {
    "audit": ("audit_observability.py", "skills/vibe-observability/scripts/audit_observability.py"),
    "verify": ("verify_live.py", "skills/vibe-observability/scripts/verify_live.py"),
    "pull": ("pull_signals.py", "skills/vibe-observability-loop/scripts/pull_signals.py"),
}


def _resolve_script(command: str) -> Path:
    filename, repo_rel = SCRIPT_MAP[command]
    pkg_dir = Path(__file__).resolve().parent

    # 1. Wheel / uvx installed location (force-included single source of truth)
    bundled = pkg_dir / "_scripts" / filename
    if bundled.is_file():
        return bundled

    # 2. Editable / source-checkout location
    repo_root = pkg_dir.parents[1]
    dev_path = repo_root / repo_rel
    if dev_path.is_file():
        return dev_path

    raise FileNotFoundError(f"Could not locate script for command '{command}': checked {bundled} and {dev_path}")


def _load_module(command: str) -> ModuleType:
    script_path = _resolve_script(command)
    mod_name = f"vibe_observability._loaded_{command}"
    spec = importlib.util.spec_from_file_location(mod_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def _print_help() -> None:
    print(
        f"""vibe-obs {__version__} — Zero-dependency observability toolkit for Vibe Coding & modern stacks

Usage:
  vibe-obs audit  [path] [--json] [--strict] [--ignore RULES]
  vibe-obs verify <url>  [--json] [--strict] [--health-path PATH]
  vibe-obs pull          [--days 7] [--job-history FILE] [--json]
  vibe-obs version

Run `vibe-obs <subcommand> --help` for full subcommand options.
Project & Agent Skills: https://github.com/realchendahuang/vibe-observability"""
    )


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return 0

    cmd, rest = args[0], args[1:]
    if cmd in {"version", "--version", "-V"}:
        print(f"vibe-obs {__version__}")
        return 0

    if cmd not in SCRIPT_MAP:
        print(f"Error: unknown subcommand '{cmd}'. Expected one of: audit, verify, pull, version.", file=sys.stderr)
        return 2

    mod = _load_module(cmd)
    return int(mod.main(rest))


if __name__ == "__main__":
    raise SystemExit(main())
