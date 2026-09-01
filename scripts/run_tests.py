#!/usr/bin/env python
"""Run this project's tests. The ONE definition of how tests are invoked.

WHY THIS EXISTS
    Two measured failure modes, both caused by the test command being written out by hand
    at every call site:

    1. RESOURCE EXHAUSTION. `pytest -n auto` takes one worker per vCPU. That is correct on
       a CI runner and wrong on a developer machine, and catastrophically wrong when
       several per-issue git worktrees run suites at the same time: the host becomes
       unusable and the agent process is killed mid-run. Local runs therefore get a
       BOUNDED worker count, derived once, here.
    2. FAIL-FAST HIDING FAILURES. `-x` / `--maxfail` stop at the first failure, so one run
       reports one problem. A worker then fixes it, re-runs, finds the next, and burns a
       whole cycle per failure. This script REFUSES those flags (see NO_FAILFAST_FLAGS) so
       the prohibition is mechanical rather than a request, and adds
       `--continue-on-collection-errors` so a broken import in one module cannot suppress
       the rest of the suite.

    Because every caller — the pre-push hook, the CI test job, the agent fleet, the
    `.pre-commit-config.yaml` manual-stage hook — goes through this script, the local run
    and the CI run cannot drift apart.

WHERE TESTS RUN (the project's contract; see docs/ and the CI-owns-the-test-suite rule)
    pre-commit hook : lint + security only. NEVER tests.
    pre-push hook   : type-check; the full suite ONLY while a CI-outage marker is declared.
    CI              : the authoritative full run, every check, no fail-fast.
    here, locally   : the AFFECTED tests, while you work.

USAGE
    python scripts/run_tests.py                          # whole suite, bounded workers
    python scripts/run_tests.py test/test_thing.py       # the affected tests only
    python scripts/run_tests.py -k "invoke_grant"        # ditto, by expression
    python scripts/run_tests.py --workers auto           # CI only: one worker per vCPU
    python scripts/run_tests.py --workers 1              # sequential (flaky shared state)
    python scripts/run_tests.py --coverage               # add the coverage gate
    python scripts/run_tests.py --junit reports/junit.xml
    python scripts/run_tests.py --print-command          # show the argv, run nothing

ADAPTED FOR THIS REPOSITORY (the prompt/agent authoring repo). Two deviations from
templates/run_tests.py.template, both because this repo has no `src/` package:

  * The suite lives under `cli-agents/cv/` with its own `pytest.ini`, so the run happens
    with that directory as cwd (SUITE_DIR below).
  * `--coverage` is accepted but there is no single coverage source to point `--cov` at,
    so it targets the shared scripts the tests actually exercise.

This repository has no CI pipeline, so its suite really is run on demand rather than by
CI. The bounded-worker and no-fail-fast contract is unchanged, which is the part worth
dogfooding.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Local parallelism ceiling. A quarter of the cores leaves the machine usable, and capping
# at MAX_LOCAL_WORKERS keeps a 64-core host from spawning 16 pytest processes per worktree.
MAX_LOCAL_WORKERS = 4
CORES_PER_WORKER = 4

# Flags that would stop the run early. Rejected outright — the whole point of a run is the
# COMPLETE failure list, and a partial list costs another full cycle to discover the rest.
NO_FAILFAST_FLAGS: tuple[str, ...] = (
    "-x",
    "--exitfirst",
    "--maxfail",
    "--stepwise",
    "--sw",
)

# Reporting flags applied to every run. `-ra` lists every non-passing outcome in a summary
# block at the end, which is what makes "fix them all in one pass" possible.
REPORT_ARGS: tuple[str, ...] = (
    "-ra",
    "--tb=short",
    "--continue-on-collection-errors",
)

# The only test suite in this repo, with its own pytest.ini.
SUITE_DIR = Path(__file__).resolve().parent.parent / "cli-agents" / "cv"

COVERAGE_SOURCE = "shared/scripts"
COVERAGE_THRESHOLD = 0  # no threshold gate in this repo


def local_workers(cpu_count: int | None = None) -> int:
    """The bounded local worker count: min(MAX, cores // CORES_PER_WORKER), floor 1."""
    cores = cpu_count if cpu_count is not None else (os.cpu_count() or 1)
    return max(1, min(MAX_LOCAL_WORKERS, cores // CORES_PER_WORKER))


def reject_failfast(extra: list[str]) -> None:
    """Refuse a caller-supplied fail-fast flag, naming the cost of it."""
    for arg in extra:
        head = arg.split("=", 1)[0]
        if head in NO_FAILFAST_FLAGS:
            sys.exit(
                f"run_tests: '{arg}' is refused. A test run must report EVERY failure in "
                f"one pass - stopping at the first one means another full cycle to find "
                f"the next. Remove it and fix all reported failures together."
            )


def require_pytest() -> None:
    """Fail with an actionable message when the runner itself is missing.

    Worth its own check: a bare `No module named pytest` reaching a caller like the
    pre-push hook reads as "the suite is red", which sends someone hunting for a test
    failure that does not exist. The real cause is an unbuilt or wrong venv.
    """
    try:
        import pytest  # noqa: F401  (probe only)
    except ImportError:
        sys.exit(
            "run_tests: pytest is not installed in this environment "
            f"({sys.executable}).\n"
            "This is an environment problem, NOT a failing test. Fix the venv:\n"
            "  python -m venv venv && pip install -e '.[dev]'\n"
            "and re-run from inside it."
        )


def has_xdist() -> bool:
    """True when pytest-xdist is importable, so -n is a valid flag."""
    try:
        import xdist  # noqa: F401  (probe only)
    except ImportError:
        return False
    return True


def build_command(
    *,
    workers: str,
    coverage: bool,
    junit: str | None,
    extra: list[str],
) -> list[str]:
    """Assemble the pytest argv. Named parameters per the project's coding standards."""
    cmd = [sys.executable, "-m", "pytest", *REPORT_ARGS]

    if workers == "auto":
        resolved = "auto"
    else:
        resolved = str(local_workers()) if workers == "local" else workers
    if resolved not in ("1", "0") and has_xdist():
        cmd += ["-n", resolved]

    if coverage:
        cmd += [
            f"--cov={COVERAGE_SOURCE}",
            "--cov-report=term-missing",
            f"--cov-fail-under={COVERAGE_THRESHOLD}",
        ]
    if junit:
        Path(junit).parent.mkdir(parents=True, exist_ok=True)
        cmd += [f"--junitxml={junit}"]

    return cmd + extra


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the project's tests with bounded parallelism and no fail-fast.",
        epilog="Unrecognized arguments are passed to pytest (paths, -k, -m, ...).",
    )
    parser.add_argument(
        "--workers",
        default="local",
        help=f"'local' (default: min({MAX_LOCAL_WORKERS}, cores//{CORES_PER_WORKER}), "
        "floor 1), 'auto' (CI only: one per vCPU), or an integer. 1 disables xdist.",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help=f"add --cov={COVERAGE_SOURCE} and the "
        f"--cov-fail-under={COVERAGE_THRESHOLD} gate",
    )
    parser.add_argument(
        "--junit",
        default=None,
        metavar="PATH",
        help="also write a JUnit XML report (CI reads this to list every "
        "failing test, not just the first)",
    )
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="print the argv that would run, then exit 0",
    )
    args, extra = parser.parse_known_args(argv)

    reject_failfast(extra)
    if not args.print_command:
        require_pytest()

    cmd = build_command(
        workers=args.workers,
        coverage=args.coverage,
        junit=args.junit,
        extra=extra,
    )

    if args.print_command:
        print(" ".join(cmd))
        return 0

    print(f"run_tests: {' '.join(cmd)}  (cwd={SUITE_DIR})", flush=True)
    if not SUITE_DIR.is_dir():
        sys.exit(f"run_tests: suite directory {SUITE_DIR} not found")
    return subprocess.call(cmd, cwd=SUITE_DIR)


if __name__ == "__main__":
    sys.exit(main())
