"""red_for_right_reason.py — verify a captured RED test run failed for the RIGHT reason.

Usage:  python red_for_right_reason.py <path-to-evidence/red/<task>.txt>
Exit 0: red for the right reason (a genuine assertion or property falsification, no load error dominating).
Exit 1: NOT red for the right reason (import/collection/syntax/fixture error, or no failure signal at all).

A helper for the conductor's TEST step and the adversarial verifier's red audit, not a hook. It reads the whole
capture, never truncates, and is pytest/Hypothesis-aware with generic fallbacks.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ANY_FAILURE_RE = re.compile(
    r"failed|FAILED|error|Falsifying example|AssertionError", re.IGNORECASE
)
WRONG_REASON_RE = re.compile(
    r"ModuleNotFoundError|ImportError|cannot import name|SyntaxError|IndentationError|errors during collection|"
    r"ERROR collecting|fixture .* not found|NameError|no tests ran",
    re.IGNORECASE,
)
COLLECTION_RE = re.compile(r"errors during collection|ERROR collecting", re.IGNORECASE)
RIGHT_REASON_RE = re.compile(
    r"AssertionError|assert |Falsifying example|FAILED .*::|hypothesis\.errors|self\.assert",
    re.IGNORECASE,
)


def judge(content: str) -> "tuple[bool, str]":
    if not ANY_FAILURE_RE.search(content):
        return False, (
            "red-for-right-reason: no failure detected — the test did not fail (it must be RED before "
            "implementing)."
        )
    if WRONG_REASON_RE.search(content) and COLLECTION_RE.search(content):
        return False, (
            "red-for-right-reason: collection/import error dominates — test failed because it could not "
            "load, not on an assertion. Make the symbols importable (stub the signature) so the test fails "
            "on its assertion instead."
        )
    if RIGHT_REASON_RE.search(content):
        return (
            True,
            "red-for-right-reason: OK — failure is a genuine assertion/property falsification.",
        )
    return False, (
        "red-for-right-reason: a failure was reported but no assertion/property-falsification signal was "
        "found; cannot confirm the test is red for the right reason."
    )


def main(argv: "list[str]") -> int:
    if len(argv) < 2 or not Path(argv[1]).is_file():
        sys.stderr.write(
            f"red-for-right-reason: capture file not found: '{argv[1] if len(argv) > 1 else ''}'\n"
        )
        return 1
    ok, message = judge(Path(argv[1]).read_text(encoding="utf-8", errors="replace"))
    (sys.stdout if ok else sys.stderr).write(message + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
