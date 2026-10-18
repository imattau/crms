"""Run CRMS's standalone experiment diagnostics with isolated working state.

Examples:
    python3 run_experiments.py --match 241
    python3 run_experiments.py --match 210 --match 240
    python3 run_experiments.py

Each diagnostic runs in a fresh temporary working directory, so default CRMS
state files in the project directory are not read or overwritten by the runner.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


PROJECT = Path(__file__).resolve().parent
EXPERIMENTS = PROJECT / "experiments"


def discover(*, include_legacy: bool) -> list[Path]:
    scripts = sorted(EXPERIMENTS.glob("v1_*.py"))
    if not include_legacy:
        scripts = [path for path in scripts
                   if path.stem.removeprefix("v1_").split("_", 1)[0].isdigit()]
    return scripts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--match", action="append", default=[], metavar="TEXT",
        help="run files whose name contains TEXT; can be supplied more than once")
    parser.add_argument("--list", action="store_true",
                        help="list selected diagnostics without running them")
    parser.add_argument("--timeout", type=float, default=180.0,
                        help="per-diagnostic timeout in seconds (default: 180)")
    parser.add_argument("--stop-on-failure", action="store_true",
                        help="stop after the first failed diagnostic")
    parser.add_argument("--include-legacy", action="store_true",
                        help="also run experiments/v1_crms.py, the earlier prototype")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    scripts = discover(include_legacy=args.include_legacy)
    if args.match:
        scripts = [path for path in scripts
                   if any(part.casefold() in path.name.casefold()
                          for part in args.match)]
    if args.list:
        for script in scripts:
            print(script.relative_to(PROJECT))
        print(f"Selected {len(scripts)} diagnostic(s).")
        return 0
    if not scripts:
        parser.error("no diagnostics matched the selection")

    environment = os.environ.copy()
    previous_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(PROJECT) if not previous_pythonpath
        else os.pathsep.join((str(PROJECT), previous_pythonpath)))
    results: list[tuple[Path, str, float, str]] = []
    print(f"Running {len(scripts)} CRMS diagnostic(s); each gets isolated cwd state.")
    for script in scripts:
        started = time.perf_counter()
        detail = ""
        status = "PASS"
        try:
            with tempfile.TemporaryDirectory(prefix="crms-experiment-") as cwd:
                completed = subprocess.run(
                    [sys.executable, str(script)], cwd=cwd, env=environment,
                    capture_output=True, text=True, timeout=args.timeout,
                    check=False)
            if completed.returncode != 0:
                status = f"FAIL({completed.returncode})"
                detail = completed.stdout + completed.stderr
        except subprocess.TimeoutExpired as error:
            status = "TIMEOUT"
            stdout = error.stdout or ""
            stderr = error.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            detail = stdout + "\n" + stderr
        except OSError as error:
            status = "ERROR"
            detail = str(error)
        elapsed = time.perf_counter() - started
        results.append((script, status, elapsed, detail))
        print(f"{status:12} {elapsed:8.2f}s  {script.name}")
        if status != "PASS" and args.stop_on_failure:
            break

    failures = [row for row in results if row[1] != "PASS"]
    if failures:
        print("\nFailure output:")
        for script, status, _elapsed, detail in failures:
            print(f"\n--- {script.name} [{status}] ---")
            detail = detail.strip()
            print(detail[-12000:] if detail else "(no diagnostic output)")
    total = sum(row[2] for row in results)
    passed = sum(row[1] == "PASS" for row in results)
    print(f"\nResult: {passed}/{len(results)} passed in {total:.2f}s.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
