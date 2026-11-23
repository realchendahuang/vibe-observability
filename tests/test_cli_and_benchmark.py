import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestCliAndBenchmark(unittest.TestCase):
    def _run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT / "src")
        return subprocess.run(
            [sys.executable, "-m", "vibe_observability.cli", *args],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_help_version_and_subcommands(self) -> None:
        self.assertEqual(self._run_cli("--help").returncode, 0)
        ver = self._run_cli("version")
        self.assertEqual(ver.returncode, 0)
        self.assertIn("vibe-obs 0.3.0", ver.stdout)

        audit = self._run_cli(
            "audit",
            str(REPO_ROOT / "skills" / "vibe-observability" / "examples" / "go-gin-caddy"),
            "--strict",
        )
        self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)
        self.assertIn("100/100", audit.stdout)

        self.assertEqual(self._run_cli("verify", "--help").returncode, 0)
        self.assertEqual(self._run_cli("pull", "--help").returncode, 0)
        self.assertEqual(self._run_cli("nonexistent").returncode, 2)

    def test_reproducible_benchmark_runs_cleanly(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "evals" / "run_benchmark.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Before (Naive)", proc.stdout)
        self.assertIn("Starter: `vite-tanstack-hono`", proc.stdout)
        self.assertIn("**100/100**", proc.stdout)


if __name__ == "__main__":
    unittest.main()
