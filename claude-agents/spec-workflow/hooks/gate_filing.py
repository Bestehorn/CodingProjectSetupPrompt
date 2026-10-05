"""issue-filing-gate — PreToolUse(Bash) gate for issue CREATION.

Enforces issue-filing-discipline at the one moment that matters: the attempt to create a tracker issue. It
recognises a CREATE call only (`create-issue`, `issue create`) and blocks when a required provenance line is
provably absent from the command text plus any readable `--body-file`:
    Origin:            human-request | spawned-discovery | spawned-residual | agent-sweep
    Subject:           product | process
    Spawned-from:      #<N>   (only when Origin is spawned-*)
    Filing-rationale:  RESEARCH | DESIGN-OPTIONS | OUT-OF-SCOPE | HUMAN-REQUEST
The body-file argument is read as the shell passes it to the wrapper (a quoted path, a path with a space, an
`=`-joined value, the `-F` / `--description-file` spellings), the LAST occurrence of a repeated flag decides as
argparse and pflag keep it, and only the first create call's own words are read, so a flag that a later chained
command passes never decides.
Fail-open: not a create call; a body this gate cannot read (heredoc, substitution, variable, unreadable file); a
command that cannot be split into shell words whose body-file value is quoted or absent.
Declared residuals: bodies assembled indirectly, create calls through an interpreter or wrapper shell, API calls
via curl, and untruthful lines are RULE-only by design.
"""

from __future__ import annotations

import re
import shlex
from typing import List, Tuple

import hooklib as lib

HOOK = "issue-filing-gate"
# DELIBERATE DIFFERENCES from the bash predecessor, so a reader does not take them for porting slips:
#   * the text-tool exemption matches the FIRST line only (`re.match`), where the bash `grep -E '^...'` matched
#     any line — a multi-line command whose second line starts with `grep` is still a create call;
#   * a backslash-newline continuation is removed before the create words are looked for and before the words
#     are split, so `gh issue \` + newline + `create ...` is recognised as a create call and the body-file
#     scoping still finds the `issue` `create` word pair; `\s+` also spans a bare line break;
#   * CRLF in the command is normalised by `Payload.command`, so a carriage return cannot flip a decision;
#   * a non-string `command` reads as empty and is allowed: fail open on an unknown payload shape;
#   * the body file is found by splitting the command into shell words (`shlex`), not by a textual match of the
#     flag: a quoted value is read, a `--body-file` mentioned inside a title is not the flag, and a name holding
#     `#` or `+` is read whole; the bash regex read the first unquoted match anywhere in the command;
#   * among the first create call's own words — from its create word up to the next `;`, `&&`, `||`, `|` or
#     unquoted newline — the LAST body-file flag decides, as the wrapper's argparse and gh/glab's pflag keep the
#     last occurrence; a `&` that belongs to a redirection (`2>&1`) separates nothing. The bash predecessor read
#     the first match, wherever it stood, so a later chained command's flag decided for the create call.
EVENT = "pre-tool-use"  # the dispatcher runs this gate on this event
ORDER = 40  # framework gates 10..90; a project gate takes >100 (or <10 to run first)
SHELL_TOOLS = {"Bash", "shell", "execute_bash", "execute_cmd", "executeBash"}
TOOLS = SHELL_TOOLS  # PreToolUse only: the tool names this gate judges
TEXT_TOOL_RE = re.compile(
    r"^\s*(grep|rg|ag|echo|printf|cat|sed|awk|less|more|head|tail|Select-String|Get-Content|"
    r"Write-Output|git\s+grep)\s"
)
CREATE_RE = re.compile(r"(create-issue|issue\s+create)")
BODYFILE_FLAGS = ("--body-file", "--description-file", "-F")
# bash removes an unquoted backslash-newline pair (a line continuation); shlex does not.
CONTINUATION_RE = re.compile(r"\\\r?\n")
# the shell's command separators and pipe, an unquoted newline among them; shlex emits a run of them (`;`, `&&`,
# `||`, `|`, a newline) as one word. The lexer's whitespace drops the newline, so a quoted one stays in its word.
OPERATOR_CHARS = ";&|\n"
LEXER_WHITESPACE = " \t\r"
# shlex splits a redirection's `&` into a word of its own: `2>&1` -> `2>`, `&`, `1`; `&>log` -> `&`, `>log`.
AMPERSAND = "&"
REDIRECTION_BEFORE_AMPERSAND = (">", "<")
REDIRECTION_AFTER_AMPERSAND = ">"
# the fallback for a command shlex cannot split: a standalone flag and its unquoted value, or the bare flag.
BODYFILE_RE = re.compile(r"(?:^|\s)(?:--body-file|--description-file|-F)(?:\s+|=)([^\s\"']+)")
BODYFILE_FLAG_RE = re.compile(r"(?:^|\s)(?:--body-file|--description-file|-F)(?=[\s=]|$)")
INDIRECT_RE = re.compile(r"\$\(|`|<<|\$[A-Za-z_{]")
ORIGIN_RE = re.compile(
    r"Origin:\s*(human-request|spawned-discovery|spawned-residual|agent-sweep)",
    re.IGNORECASE,
)
SUBJECT_RE = re.compile(r"Subject:\s*(product|process)", re.IGNORECASE)
RATIONALE_RE = re.compile(
    r"Filing-rationale:\s*(RESEARCH|DESIGN-OPTIONS|OUT-OF-SCOPE|HUMAN-REQUEST)",
    re.IGNORECASE,
)
SPAWNED_RE = re.compile(r"Origin:\s*spawned-(discovery|residual)", re.IGNORECASE)
SPAWNED_FROM_RE = re.compile(r"Spawned-from:\s*#?[0-9]+", re.IGNORECASE)


def _is_redirection_ampersand(*, word: str, previous: str, following: str) -> bool:
    """Whether a `&` word belongs to a redirection (`2>&1`, `>&2`, `<&3`, `&>log`) and so separates nothing.

    It does when the previous word ends with `>` or `<`, or the next word starts with `>`.
    """
    return word == AMPERSAND and (
        previous.endswith(REDIRECTION_BEFORE_AMPERSAND) or following.startswith(REDIRECTION_AFTER_AMPERSAND)
    )


def _is_operator(*, words: List[str], index: int) -> bool:
    """Whether the word at `index` is a control operator.

    It is when made only of `OPERATOR_CHARS` (`;`, `&&`, `||`, `|`, an unquoted newline, ...), unless it is a
    redirection's `&`.
    """
    word = words[index]
    if not word or not all(char in OPERATOR_CHARS for char in word):
        return False
    previous = words[index - 1] if index > 0 else ""
    following = words[index + 1] if index + 1 < len(words) else ""
    return not _is_redirection_ampersand(word=word, previous=previous, following=following)


def _create_call_words(words: List[str]) -> List[str]:
    """The first create call's own words: after its `create-issue` (or `issue create`) up to the next operator.

    All words when the command holds no create word. A redirection's `&` (`2>&1`) is no operator.
    """
    for index, word in enumerate(words):
        if word == "create-issue":
            start = index + 1
        elif word == "issue" and index + 1 < len(words) and words[index + 1] == "create":
            start = index + 2
        else:
            continue
        end = start
        while end < len(words) and not _is_operator(words=words, index=end):
            end += 1
        return words[start:end]
    return words


def _bodyfile_argument(command: str) -> Tuple[bool, str]:
    """Whether the command passes a body file, and the flag's argument as the shell passes it ("" if unknown).

    The first create call's own words decide, from its `create-issue` (or `issue create`) word up to the next
    `;`, `&&`, `||`, `|` or unquoted-newline word (all words when there is no create word; a redirection's `&`,
    as in `2>&1`, separates nothing), so a later chained command's flag never does. Among them the last flag word
    decides, as argparse and pflag keep the last occurrence of a repeated flag: a word equal to a flag takes the
    next word (none when it is the create call's last word); a `<flag>=` word takes its remainder. A command
    `shlex` cannot split falls back to the last unquoted value after a flag, and a flag with no such value counts
    as a body file whose argument is unknown.
    """
    lexer = shlex.shlex(CONTINUATION_RE.sub("", command), posix=True, punctuation_chars=OPERATOR_CHARS)
    lexer.whitespace = LEXER_WHITESPACE
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        all_words = list(lexer)
    except ValueError:
        values = BODYFILE_RE.findall(command)
        if values:
            return True, values[-1]
        return BODYFILE_FLAG_RE.search(command) is not None, ""
    words = _create_call_words(all_words)
    result: Tuple[bool, str] = (False, "")
    for index, word in enumerate(words):
        flag, separator, value = word.partition("=")
        if flag not in BODYFILE_FLAGS:
            continue
        if separator:
            result = (True, value)
        elif index + 1 < len(words):
            result = (True, words[index + 1])
        else:
            result = (False, "")
    return result


def run(ctx: lib.Context) -> lib.Decision:  # noqa: C901 — provenance checks, one per line, in order
    command = ctx.payload.command
    if not command:
        return lib.allow()
    if TEXT_TOOL_RE.match(command):
        return lib.allow()  # talking ABOUT issue creation, not doing it
    if not CREATE_RE.search(CONTINUATION_RE.sub("", command)):
        return lib.allow()
    rule = f"{ctx.host.rules_dir}/issue-filing-discipline.md"

    haystack = command
    bodyfile_unreadable = False
    present, bodyfile = _bodyfile_argument(command)
    if present:
        resolved = None
        if bodyfile:
            for candidate in (lib.Path(bodyfile), ctx.project_dir / bodyfile):
                if candidate.is_file():
                    resolved = candidate
                    break
        if resolved is not None:
            haystack = haystack + "\n" + lib.read_text(resolved)
        else:
            bodyfile_unreadable = True

    missing = []
    if not ORIGIN_RE.search(haystack):
        missing.append("Origin:")
    if not SUBJECT_RE.search(haystack):
        missing.append("Subject:")
    if not RATIONALE_RE.search(haystack):
        missing.append("Filing-rationale:")
    if SPAWNED_RE.search(haystack) and not SPAWNED_FROM_RE.search(haystack):
        missing.append("Spawned-from:")
    if not missing:
        return lib.allow()

    if bodyfile_unreadable:
        return lib.allow(
            stderr=(
                f"{HOOK}: --body-file '{bodyfile}' is not readable from here; provenance not verified. Allowing.\n"
                f"  The four Origin/Subject/Spawned-from/Filing-rationale lines are still required by {rule}.\n"
            )
        )
    if INDIRECT_RE.search(command):
        return lib.allow(
            stderr=(
                f"{HOOK}: the issue body is assembled from a source this hook cannot read (command substitution,\n"
                f"  heredoc, or a variable); provenance not verified. Allowing. The four provenance lines are still\n"
                f"  required by {rule}.\n"
            )
        )

    return lib.block(
        f"BLOCKED by {HOOK}: this issue body is missing required provenance line(s): {' '.join(missing)}\n\n"
        f"First re-run the fix-first evaluation ({rule}):\n"
        "  1. Blocking the current task?  -> fix it in the current change, do not file.\n"
        "  2. Small and clear (a few lines, no design choice, no new dependency)?\n"
        "     -> FIX IT NOW and do not file. This is the expected outcome for most\n"
        "        defects noticed in passing.\n"
        "  3. Needs extensive RESEARCH, an evaluation of DESIGN-OPTIONS, or is\n"
        "     OUT-OF-SCOPE for the current task (or a human asked: HUMAN-REQUEST)?\n"
        "     -> file it, and say which one.\n"
        "  4. None of the above? -> one line in docs/findings-ledger.md, then move on.\n"
        "     Filing nothing is a valid and expected outcome.\n\n"
        "If the evaluation still says FILE, put these lines in the issue body (prefer\n"
        "delegating the filing to the issue-intake agent, which emits them):\n"
        "  Origin: human-request|spawned-discovery|spawned-residual|agent-sweep\n"
        "  Subject: product|process\n"
        "  Spawned-from: #<N>            (only when Origin is spawned-*)\n"
        "  Filing-rationale: RESEARCH|DESIGN-OPTIONS|OUT-OF-SCOPE|HUMAN-REQUEST — <why>"
    )
