#!/usr/bin/env python
"""wait_for.py — the ONE sanctioned bounded wait for something LOCAL: a file, a line in a file, a process.

    python .claude/hooks/wait_for.py --file <path> [--line <regex>] [--pid <pid>] --timeout-seconds 540

Exit codes, the same family as the wrappers' `wait-run` / `pipeline wait`:
    0   the condition holds (the file exists; with --line, a line matches; with only --pid, the process ended)
    10  the condition can no longer hold: --pid ended and the file / the line never appeared
    11  the timeout passed first — re-issue the same command (the Bash tool's ceiling is 600 s, so 540 fits)
    2   usage

The portable form is a LOG with an exit line: start the background command as
`<command> > <log> 2>&1; echo "exit=$?" >> <log>` and wait with `--file <log> --line '^exit='`. `--pid` takes an
OPERATING-SYSTEM process id: under Git Bash on Windows `$!` is an MSYS id, not a Windows one, so there use the log
form (or the Windows id from `/proc/<msys-id>/winpid`).

Why it exists. Measured on two projects (project-docs/wait-time-analysis-2026-10-25.md): agents hand-rolled
`until grep ...; do sleep 20; done`, `tail -f | grep -m1`, `Wait-Process` and per-run `wait_for_line.py` scripts
to collect a background suite — 17 h of waits whose target nobody could read afterwards, and the loops the
no-foreground-sleep gate refuses. This polls internally (the sleep is inside a Python process, not a shell
loop), prints what it found or why it gave up, and never exceeds its timeout. Standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

EXIT_FOUND = 0
EXIT_GONE = 10
EXIT_TIMEOUT = 11
POLL_SECONDS = 2.0
MAX_TIMEOUT_SECONDS = 590


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def matching_line(path: Path, pattern: "re.Pattern[str]") -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if pattern.search(line):
            return line
    return None


def satisfied(path: Optional[Path], pattern: "Optional[re.Pattern[str]]") -> Optional[str]:
    """The evidence when the file condition holds, else None. No file condition -> None (pid-only mode)."""
    if path is None:
        return None
    if pattern is None:
        return f"{path} exists" if path.exists() else None
    line = matching_line(path, pattern)
    return f"{path}: {line}" if line is not None else None


def main(argv: Optional[list] = None) -> int:  # noqa: C901 — argument checks plus one wait loop, read top to bottom
    parser = argparse.ArgumentParser(prog="wait_for.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--file", help="a file that must appear (or contain --line)")
    parser.add_argument("--line", help="a regular expression one line of --file must match")
    parser.add_argument(
        "--pid",
        type=int,
        help="an OS process id (not Git Bash's $! on Windows): alone, wait for it to end; with --file, give up "
        "when it ends",
    )
    parser.add_argument("--timeout-seconds", type=float, required=True)
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass  # a replaced stream (a test's capture) keeps its own encoding
    if not args.file and not args.pid:
        parser.error("give --file and/or --pid")
    if args.line and not args.file:
        parser.error("--line needs --file")
    if args.timeout_seconds <= 0 or args.timeout_seconds > MAX_TIMEOUT_SECONDS:
        parser.error(f"--timeout-seconds must be in (0, {MAX_TIMEOUT_SECONDS}] — the Bash tool's ceiling is 600 s")
    path = Path(args.file) if args.file else None
    pattern = re.compile(args.line) if args.line else None
    deadline = time.monotonic() + args.timeout_seconds
    while True:
        evidence = satisfied(path, pattern)
        if evidence is not None:
            print(f"wait_for: FOUND — {evidence}", flush=True)
            return EXIT_FOUND
        if args.pid:
            if not pid_alive(args.pid):
                evidence = satisfied(path, pattern)  # it may have written its last line on the way out
                if evidence is not None:
                    print(f"wait_for: FOUND — {evidence}", flush=True)
                    return EXIT_FOUND
                if path is None:
                    print(f"wait_for: process {args.pid} has ended", flush=True)
                    return EXIT_FOUND
                print(f"wait_for: GONE — process {args.pid} ended and {path} never satisfied the wait", flush=True)
                return EXIT_GONE
        if time.monotonic() >= deadline:
            print(
                f"wait_for: TIMEOUT after {args.timeout_seconds:g}s — re-issue the same command to keep waiting",
                flush=True,
            )
            return EXIT_TIMEOUT
        time.sleep(min(POLL_SECONDS, max(0.0, deadline - time.monotonic())))


if __name__ == "__main__":
    sys.exit(main())
