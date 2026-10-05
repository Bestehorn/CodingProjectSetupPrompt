"""The issue-filing gate (gate_filing): 0 = allow the command, 2 = block it.

A corpus-style suite in both directions over REAL body files written under `tmp_path`. The gate must read the
body-file argument as the shell passes it to the wrapper: a quoted path (every absolute path in a checkout whose
directory name holds a space needs quotes — measured as a block of a provenance-complete create call), a path
with a space, an `=`-joined value, the `-F` / `--description-file` spellings, a flag that the title merely
MENTIONS (measured as a fail-open of a provenance-free body), the LAST occurrence of a repeated flag (argparse
and pflag keep it), and only the first create call's own words when a later chained command — after `&&`, `;`,
`|` or an unquoted newline — passes a flag of its own. Standard library + pytest only; Python 3.9 compatible.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import gate_filing
import hooklib

HOOKS_DIR = Path(__file__).resolve().parent.parent
ALLOW = 0
BLOCK = 2

GOOD = "good.md"
BAD = "bad.md"
SPAWNED = "spawned.md"
MISSING = "missing.md"
#: Provenance-free body files whose names hold a character `shlex` treats specially by default: `#` starts a
#: comment and `+` is no word character. Bash passes each name whole, and so does the wrapper's parser.
HASH_NAMED = "notes#1.md"
PLUS_NAMED = "bad+1.md"
#: A directory whose name carries a space, as a real checkout path does; its files are named absolute and quoted.
SPACED_DIR = "Code Workspace"

PROVENANCE_COMPLETE = (
    "A body that carries every required provenance line.\n"
    "Origin: human-request\n"
    "Subject: process\n"
    "Filing-rationale: HUMAN-REQUEST — test\n"
)
PROVENANCE_FREE = "A plain issue body with no provenance lines at all.\n"
SPAWNED_WITHOUT_FROM = "Origin: spawned-discovery\nSubject: process\nFiling-rationale: OUT-OF-SCOPE — test\n"

BLOCK_MARKER = "BLOCKED by issue-filing-gate"
NOT_READABLE_MARKER = "is not readable from here"
INDIRECT_MARKER = "assembled from a source this hook cannot read"
NOT_READABLE_VALUE_RE = re.compile(r"--body-file '(?P<value>[^']*)' is not readable from here")

CREATE = 'python scripts/github_wrapper.py create-issue --title "t"'
TITLE_MENTION = 'python scripts/github_wrapper.py create-issue --title "fix --body-file parsing"'
COMMENT = "python scripts/github_wrapper.py comment-issue 5"
INLINE_PROVENANCE = '--body "Origin: human-request\nSubject: process\nFiling-rationale: HUMAN-REQUEST — test"'
#: The trailing comment's apostrophe is an unclosed single quote, so `shlex` raises on the whole command.
APOSTROPHE_COMMENT = "  # don't"


def decide(command: str, tmp_path: Path) -> hooklib.Decision:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    ctx = hooklib.Context(
        hooklib.Payload.parse(json.dumps(payload)), environ={}, hooks_dir=Path(HOOKS_DIR), cwd=Path(tmp_path)
    )
    return gate_filing.run(ctx)


def _write(path: Path, text: str) -> None:
    """UTF-8 with LF line ends, written as bytes so the platform cannot rewrite them."""
    path.write_bytes(text.encode("utf-8"))


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """The project directory (`tmp_path`, the gate's process cwd) holding every readable body file, relative
    names at its top and quoted absolute names inside a subdirectory whose name carries a space. `missing.md`
    is deliberately never written."""
    spaced = tmp_path / SPACED_DIR
    spaced.mkdir()
    for directory in (tmp_path, spaced):
        _write(directory / GOOD, PROVENANCE_COMPLETE)
        _write(directory / BAD, PROVENANCE_FREE)
    _write(tmp_path / SPAWNED, SPAWNED_WITHOUT_FROM)
    _write(tmp_path / HASH_NAMED, PROVENANCE_FREE)
    _write(tmp_path / PLUS_NAMED, PROVENANCE_FREE)
    return tmp_path


def render(template: str, project: Path) -> str:
    """Fill `{good}`, `{bad}` and `{missing}` with the POSIX absolute paths inside the spaced subdirectory."""
    spaced = project / SPACED_DIR
    return template.format(
        good=(spaced / GOOD).as_posix(), bad=(spaced / BAD).as_posix(), missing=(spaced / MISSING).as_posix()
    )


def assert_verified_allow(decision: hooklib.Decision, command: str) -> None:
    """An allow that VERIFIED the provenance: exit 0 and neither fail-open note."""
    assert decision.exit_code == ALLOW, f"wrongly refused: {command!r}\n{decision.stderr}"
    assert NOT_READABLE_MARKER not in decision.stderr, decision.stderr
    assert INDIRECT_MARKER not in decision.stderr, decision.stderr


def assert_block(decision: hooklib.Decision, command: str) -> None:
    assert decision.exit_code == BLOCK, f"not blocked: {command!r}\n{decision.stderr}"
    assert BLOCK_MARKER in decision.stderr, decision.stderr


# ---------------------------------------------------------------------------------------------------------
# the ALLOW direction: a provenance-complete body file in every spelling the shell accepts
# ---------------------------------------------------------------------------------------------------------

ALLOW_TEMPLATES = (
    ("double-quoted-absolute-path-with-space", CREATE + ' --body-file "{good}"'),
    ("single-quoted-absolute-path-with-space", CREATE + " --body-file '{good}'"),
    ("equals-joined-double-quoted", CREATE + ' --body-file="{good}"'),
    ("equals-joined-unquoted-relative", CREATE + " --body-file=" + GOOD),
    ("unquoted-relative", CREATE + " --body-file " + GOOD),
    ("gh-dash-F-double-quoted", 'gh issue create --title "t" -F "{good}"'),
    ("gh-dash-F-unquoted-relative", "gh issue create -t t -F " + GOOD),
    ("glab-description-file-double-quoted", 'glab issue create --title "t" --description-file "{good}"'),
    # a REAL backslash then a REAL newline: bash's unquoted line continuation, removed before the words are split
    (
        "backslash-newline-continuation",
        "python scripts/github_wrapper.py create-issue --title t \\\n--body-file " + GOOD,
    ),
    ("backslash-crlf-continuation", CREATE + " --body-file \\\r\n" + GOOD),
    ("issue-create-split-by-continuation", "gh issue \\\ncreate --title t -F " + GOOD),
    ("repeated-flag-last-provenance-complete", CREATE + ' --body-file "{bad}" --body-file "{good}"'),
    (
        "then-and-chained-comment-call-provenance-free",
        CREATE + " --body-file " + GOOD + " && " + COMMENT + " --body-file " + BAD,
    ),
    (
        "then-semicolon-chained-git-commit-dash-F-provenance-free",
        CREATE + " --body-file " + GOOD + "; git commit -F " + BAD,
    ),
    (
        "then-or-chained-comment-provenance-free",
        CREATE + " --body-file " + GOOD + " || " + COMMENT + " --body-file " + BAD,
    ),
    ("then-piped-to-tee-dash-F-provenance-free", CREATE + " --body-file " + GOOD + " | tee -F " + BAD),
    # a REAL newline with no backslash before it: a command separator, not a continuation
    (
        "then-newline-separated-comment-provenance-free",
        CREATE + " --body-file " + GOOD + "\n" + COMMENT + " --body-file " + BAD,
    ),
    ("redirect-2-to-1-then-flag", CREATE + " 2>&1 --body-file " + GOOD),
    (
        "gh-chained-gh-comment-provenance-free",
        'gh issue create --title "t" -F ' + GOOD + " && gh issue comment 5 -F " + BAD,
    ),
    ("create-issue-inside-a-longer-word-reads-all-words", "python my-create-issue-tool.py --body-file " + GOOD),
    (
        "create-after-a-pipe",
        "python render.py | python scripts/github_wrapper.py create-issue -t t --body-file " + GOOD,
    ),
    ("inline-provenance-in-body", CREATE + " " + INLINE_PROVENANCE),
    ("inline-provenance-and-a-provenance-free-file", CREATE + " " + INLINE_PROVENANCE + " --body-file " + BAD),
)


@pytest.mark.parametrize("template", [t for _, t in ALLOW_TEMPLATES], ids=[i for i, _ in ALLOW_TEMPLATES])
def test_a_provenance_complete_body_is_allowed_in_every_spelling(project: Path, template: str) -> None:
    command = render(template, project)
    assert_verified_allow(decide(command, project), command)


@pytest.mark.parametrize(
    "command",
    [
        "python scripts/github_wrapper.py get-issue 569",
        "python scripts/github_wrapper.py comment-issue 5 --body-file " + BAD,
        'grep -n "create-issue --body-file" scripts/github_wrapper.py',
        'echo "gh issue create -F body.md"',
        "git grep -n 'issue create' -- .claude",
        "",
    ],
    ids=["non-create-wrapper-call", "comment-call-with-provenance-free-file", "grep", "echo", "git-grep", "empty"],
)
def test_a_command_that_creates_nothing_is_allowed_without_a_note(project: Path, command: str) -> None:
    decision = decide(command, project)
    assert decision.exit_code == ALLOW, decision.stderr
    assert decision.stderr == ""


def test_a_non_string_command_reads_as_empty_and_is_allowed(project: Path) -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": ["gh", "issue", "create"]}}
    ctx = hooklib.Context(hooklib.Payload.parse(json.dumps(payload)), environ={}, hooks_dir=HOOKS_DIR, cwd=project)
    assert gate_filing.run(ctx).exit_code == ALLOW


# ---------------------------------------------------------------------------------------------------------
# the ALLOW direction, fail-open: a body this gate cannot read is allowed WITH the note that says so
# ---------------------------------------------------------------------------------------------------------


def test_a_quoted_missing_file_fails_open_and_names_the_value_without_its_quotes(project: Path) -> None:
    command = render(CREATE + ' --body-file "{missing}"', project)
    decision = decide(command, project)
    assert decision.exit_code == ALLOW, decision.stderr
    named = NOT_READABLE_VALUE_RE.search(decision.stderr)
    assert named is not None, decision.stderr
    assert named.group("value") == (project / SPACED_DIR / MISSING).as_posix()
    assert '"' not in named.group("value")


def test_an_unquoted_missing_file_fails_open(project: Path) -> None:
    decision = decide(CREATE + " --body-file " + MISSING, project)
    assert decision.exit_code == ALLOW, decision.stderr
    assert f"--body-file '{MISSING}' {NOT_READABLE_MARKER}" in decision.stderr


@pytest.mark.parametrize(
    "command",
    [
        CREATE + ' --body "$(cat notes.md)"',
        CREATE + ' --body "$BODY"',
        CREATE + " --body \"$(cat <<'EOF'\nplain\nEOF\n)\"",
    ],
    ids=["command-substitution", "variable", "heredoc"],
)
def test_an_indirectly_assembled_body_fails_open_with_the_indirect_note(project: Path, command: str) -> None:
    decision = decide(command, project)
    assert decision.exit_code == ALLOW, decision.stderr
    assert INDIRECT_MARKER in decision.stderr


@pytest.mark.parametrize(
    "template",
    [
        CREATE + ' --body-file "{good}',
        'python scripts/github_wrapper.py create-issue --title "unterminated --body-file',
        CREATE + " --body-file <(python render.py)",
    ],
    ids=[
        "unclosed-double-quote-around-the-value",
        "standalone-flag-at-the-end-of-an-unclosed-quote",
        "process-substitution-is-read-as-a-file-name",
    ],
)
def test_a_body_file_value_this_gate_cannot_resolve_fails_open(project: Path, template: str) -> None:
    """an unsplittable command's quoted or absent value, or a value that names no file, is the not-readable note"""
    decision = decide(render(template, project), project)
    assert decision.exit_code == ALLOW, decision.stderr
    assert NOT_READABLE_MARKER in decision.stderr


# ---------------------------------------------------------------------------------------------------------
# the BLOCK direction: a provenance-free body the gate CAN read, however the flag is spelled or placed
# ---------------------------------------------------------------------------------------------------------

BLOCK_TEMPLATES = (
    ("double-quoted-absolute-path-with-space", CREATE + ' --body-file "{bad}"'),
    ("single-quoted-absolute-path-with-space", CREATE + " --body-file '{bad}'"),
    ("equals-joined-double-quoted", CREATE + ' --body-file="{bad}"'),
    ("equals-joined-unquoted-relative", CREATE + " --body-file=" + BAD),
    ("unquoted-relative", CREATE + " --body-file " + BAD),
    ("gh-dash-F-unquoted", "gh issue create --title t -F " + BAD),
    ("glab-description-file-quoted", 'glab issue create --title "t" --description-file "{bad}"'),
    ("issue-create-split-by-continuation", "gh issue \\\ncreate --title t -F " + BAD),
    ("repeated-flag-last-provenance-free", CREATE + ' --body-file "{good}" --body-file "{bad}"'),
    (
        "then-and-chained-comment-provenance-complete",
        CREATE + ' --body-file "{bad}" && ' + COMMENT + ' --body-file "{good}"',
    ),
    (
        "then-and-chained-second-create-provenance-complete",
        CREATE + ' --body-file "{bad}" && ' + CREATE + ' --body-file "{good}"',
    ),
    (
        "then-newline-separated-comment-provenance-complete",
        CREATE + " --body-file " + BAD + "\n" + COMMENT + ' --body-file "{good}"',
    ),
    (
        "then-piped-comment-provenance-complete",
        CREATE + " --body-file " + BAD + " | " + COMMENT + " --body-file " + GOOD,
    ),
    ("good-then-redirect-2-to-1-then-last-flag-bad", CREATE + ' --body-file "{good}" 2>&1 --body-file ' + BAD),
    ("name-with-hash", CREATE + " --body-file " + HASH_NAMED),
    ("name-with-plus", CREATE + " --body-file " + PLUS_NAMED),
    ("title-mentions-the-flag-real-body-provenance-free", TITLE_MENTION + " --body-file " + BAD),
    ("title-mentions-the-flag-no-body-file", TITLE_MENTION + ' --body "plain text"'),
    ("inline-body-without-provenance", CREATE + ' --body "plain text"'),
    ("no-body-at-all", "gh issue create --title t"),
    ("flag-as-the-last-word", CREATE + " --body-file"),
    (
        "repeated-flag-last-as-last-word-after-provenance-complete-file",
        CREATE + " --body-file " + GOOD + " --body-file",
    ),
    ("create-after-a-pipe", "python render.py | python scripts/github_wrapper.py create-issue -t t --body-file " + BAD),
    ("second-line-starts-with-a-text-tool", CREATE + " --body-file " + BAD + "\ngrep -n x y"),
    # the fallback for a command shlex cannot split: the last unquoted value, a flag only as a standalone token
    ("unsplittable-provenance-free-file", CREATE + " --body-file " + BAD + APOSTROPHE_COMMENT),
    (
        "unsplittable-repeated-flag-last-provenance-free",
        CREATE + " --body-file " + GOOD + " --body-file " + BAD + APOSTROPHE_COMMENT,
    ),
    ("unsplittable-dash-F-inside-a-label-is-no-flag", CREATE + " --label wip-F " + GOOD + APOSTROPHE_COMMENT),
    (
        "unsplittable-body-file-inside-a-label-is-no-flag",
        CREATE + " --label wip--body-file --body plain" + APOSTROPHE_COMMENT,
    ),
)


@pytest.mark.parametrize("template", [t for _, t in BLOCK_TEMPLATES], ids=[i for i, _ in BLOCK_TEMPLATES])
def test_a_readable_provenance_free_body_is_blocked(project: Path, template: str) -> None:
    command = render(template, project)
    assert_block(decide(command, project), command)


def test_a_spawned_origin_without_spawned_from_is_blocked_naming_the_line(project: Path) -> None:
    decision = decide(CREATE + " --body-file " + SPAWNED, project)
    assert_block(decision, SPAWNED)
    assert "missing required provenance line(s): Spawned-from:" in decision.stderr


def test_the_refusal_names_every_missing_line_and_the_rule(project: Path) -> None:
    decision = decide(CREATE + ' --body "plain text"', project)
    assert_block(decision, "plain")
    assert "Origin: Subject: Filing-rationale:" in decision.stderr
    assert "issue-filing-discipline.md" in decision.stderr
    assert "issue-intake agent" in decision.stderr, "the refusal names the delegate that emits the lines"


def test_a_crlf_payload_is_read_like_an_lf_one(project: Path) -> None:
    assert_block(decide(CREATE + " --body-file " + BAD + "\r\necho done\r\n", project), BAD)
    good = CREATE + " --body-file " + GOOD + "\r\n" + COMMENT + " --body-file " + BAD + "\r\n"
    assert_verified_allow(decide(good, project), good)


# ---------------------------------------------------------------------------------------------------------
# the body-file reader on its own: which words decide
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command, expected",
    [
        (CREATE + ' --body-file "a b/c.md"', (True, "a b/c.md")),
        (CREATE + " --body-file=a.md", (True, "a.md")),
        (CREATE + " -F a.md -F b.md", (True, "b.md")),
        (CREATE + " -F a.md && x -F b.md", (True, "a.md")),
        (CREATE + " -F a.md\nx -F b.md", (True, "a.md")),
        (CREATE + " 2>&1 -F a.md", (True, "a.md")),
        (CREATE + " &>log -F a.md", (True, "a.md")),
        (CREATE + " --body-file", (False, "")),
        (CREATE + " --body x", (False, "")),
        ("x -F a.md", (True, "a.md")),
        (TITLE_MENTION + " --body x", (False, "")),
        (CREATE + " -F a.md  # don't", (True, "a.md")),
        (CREATE + ' -F "a.md', (True, "")),
        ('python scripts/github_wrapper.py create-issue --title "unterminated --body-file', (True, "")),
        (CREATE + " --label wip-F a.md  # don't", (False, "")),
    ],
    ids=[
        "quoted-with-space",
        "equals-joined",
        "last-of-two",
        "chained-command-flag-ignored",
        "newline-separated-flag-ignored",
        "redirection-ampersand-separates-nothing",
        "ampersand-redirect-separates-nothing",
        "trailing-flag-has-no-value",
        "no-flag",
        "no-create-word-reads-all-words",
        "title-mention-is-no-flag",
        "fallback-last-unquoted-value",
        "fallback-quoted-value-is-present-but-unknown",
        "fallback-standalone-flag-without-value-is-present-but-unknown",
        "fallback-flag-inside-a-label-is-no-flag",
    ],
)
def test_bodyfile_argument_reads_the_words_the_shell_passes(command: str, expected: "tuple[bool, str]") -> None:
    assert gate_filing._bodyfile_argument(command) == expected
