#!/usr/bin/env python
"""Declare, inspect, and clear CI-OUTAGE MODE — the only state in which the full test
suite runs locally.

WHY THIS EXISTS
    This project's tests run in CI, not on a developer machine (see the
    CI-owns-the-test-suite rule). There is exactly one sanctioned exception: CI cannot
    produce a run at all, proven structurally per the capacity ladder in
    remote-ci-must-pass.md. In that state the pipeline must still be executed before a
    merge — so it is executed LOCALLY, at PUSH time, and never at commit time.

    The `.githooks/pre-push` hook needs to know which state it is in without asking anyone.
    This script is how that state is recorded. With no marker the hook skips tests in about
    a fifth of a second; with a marker it runs the suite and says why.

WHERE THE MARKER LIVES, AND WHY THERE
    `<git-common-dir>/ci-outage-mode` — i.e. `.git/ci-outage-mode` in a normal checkout.
    Two properties come free from that location and neither is incidental:

      * It is inside `.git/`, so it can never be committed and needs no .gitignore entry.
        The outage is a property of this clone at this moment, not of the project.
      * `git rev-parse --git-common-dir` resolves to the SAME directory from every linked
        worktree, so one declaration covers every concurrent per-issue worktree in the
        clone. A per-worktree marker would leave sibling runs pushing untested code.

WHAT IT RECORDS, AND WHY THAT IS MANDATORY
    Rung 3 of the capacity ladder requires a disclosure comment on the merge naming the
    quoted refusal evidence and the tracking issue. Requiring those fields HERE means the
    disclosure material is captured at the moment the outage is declared, rather than
    reconstructed from memory at merge time. `declare` refuses without them.

USAGE
    python scripts/ci_outage_mode.py declare --evidence-run 17420631881 --issue 142 --rung 3
    python scripts/ci_outage_mode.py status          # exit 0 = active, 1 = not active
    python scripts/ci_outage_mode.py status --quiet   # exit code only
    python scripts/ci_outage_mode.py clear           # once a real CI run goes green

    Clearing is not optional housekeeping: while the marker is set, every push in every
    worktree of this clone pays for a full local suite.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MARKER_NAME = "ci-outage-mode"

# Fields the marker must carry. Keep the names stable — the pre-push hook greps them.
FIELD_DECLARED = "DECLARED"
FIELD_EVIDENCE_RUN = "EVIDENCE_RUN"
FIELD_ISSUE = "ISSUE"
FIELD_RUNG = "RUNG"


def git_common_dir() -> Path:
    """The directory shared by the main checkout and every linked worktree.

    `--git-common-dir` may answer with a RELATIVE path, and it is relative to the CURRENT
    directory — not to the top level of the working tree. Joining it against
    `--show-toplevel` instead is a silent, hard-to-spot bug: from two directories down it
    resolves to a plausible-looking path outside the repository entirely.
    """
    out = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        sys.exit(
            "ci_outage_mode: not inside a git repository "
            f"({out.stderr.strip() or 'git rev-parse failed'})"
        )
    common = Path(out.stdout.strip())
    if not common.is_absolute():
        common = Path.cwd() / common
    return common.resolve()


def marker_path() -> Path:
    return git_common_dir() / MARKER_NAME


def do_declare(*, evidence_run: str, issue: str, rung: int, note: str) -> int:
    path = marker_path()
    if path.exists():
        print(f"ci_outage_mode: already active - {path}")
        print(path.read_text(encoding="utf-8").rstrip())
        print(
            "Not overwriting. The FIRST declaration carries the original evidence; add "
            "a new-occurrence comment to the tracking issue instead."
        )
        return 0

    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    body = (
        f"{FIELD_DECLARED}: {now}\n"
        f"{FIELD_EVIDENCE_RUN}: {evidence_run}\n"
        f"{FIELD_ISSUE}: {issue}\n"
        f"{FIELD_RUNG}: {rung}\n"
    )
    if note:
        body += f"NOTE: {note}\n"
    path.write_text(body, encoding="utf-8")
    print(f"ci_outage_mode: DECLARED - {path}")
    print(body.rstrip())
    print(
        "Every push in every worktree of this clone now runs the full suite locally. "
        "Clear it as soon as a real CI run goes green."
    )
    return 0


def do_status(*, quiet: bool) -> int:
    path = marker_path()
    if not path.exists():
        if not quiet:
            print("ci_outage_mode: NOT ACTIVE - CI owns the test suite.")
        return 1
    if not quiet:
        print(f"ci_outage_mode: ACTIVE - {path}")
        print(path.read_text(encoding="utf-8").rstrip())
    return 0


def do_clear() -> int:
    path = marker_path()
    if not path.exists():
        print("ci_outage_mode: nothing to clear - not active.")
        return 0
    previous = path.read_text(encoding="utf-8").rstrip()
    path.unlink()
    print(f"ci_outage_mode: CLEARED - {path}")
    print("Was:")
    print(previous)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Declare/inspect/clear CI-OUTAGE MODE (the only state in which the "
        "full suite runs locally, and then only at push time).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    declare = sub.add_parser("declare", help="record a proven CI capacity outage")
    declare.add_argument(
        "--evidence-run",
        required=True,
        help="the run/pipeline id whose per-job listing proved the "
        "refusal (capacity ladder Rung 0)",
    )
    declare.add_argument(
        "--issue",
        required=True,
        help="the tracking issue for the CI fallback mechanism (Rung 2). "
        "Required: Rung 3 cannot be reached before Rung 2 exists.",
    )
    declare.add_argument(
        "--rung",
        type=int,
        required=True,
        choices=(2, 3),
        help="which rung of the ladder this declaration serves",
    )
    declare.add_argument("--note", default="", help="optional one-line context")

    status = sub.add_parser("status", help="exit 0 when active, 1 when not")
    status.add_argument(
        "--quiet", action="store_true", help="exit code only, no output"
    )

    sub.add_parser("clear", help="end CI-outage mode (do this as soon as CI is back)")

    args = parser.parse_args(argv)

    if args.command == "declare":
        return do_declare(
            evidence_run=args.evidence_run,
            issue=args.issue,
            rung=args.rung,
            note=args.note,
        )
    if args.command == "status":
        return do_status(quiet=args.quiet)
    return do_clear()


if __name__ == "__main__":
    sys.exit(main())
