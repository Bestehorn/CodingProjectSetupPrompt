"""merge-steward — PreToolUse(Bash) gate: where the merge steward lands the trunk, no agent writes it directly.

Active only when the project's `config/delivery.json` says `"merge": "steward"` (.claude/docs/delivery.md). Then
the steward — a CI job running `scripts/merge_steward.py tick` — is the ONLY writer of the trunk: it builds
`main` + the queued PRs on train branches, lands the longest green train by fast-forward and drops the culprit,
so nothing reaches the trunk that CI did not test on the exact merged state. A direct merge bypasses that test,
and on a host plan that cannot enforce branch protection this gate is the enforcement.

Refused (exit 2): the wrapper's `merge-pr` / `mr merge`; `gh pr merge`, `glab mr merge`; a REST call to a PR or
MR merge endpoint; a `git push` whose destination is the trunk (`main`, `HEAD:main`, `x:refs/heads/main`,
`+main`, `--all`, `--mirror`, a `--delete` of it), and a bare `git push`/`git push <remote> HEAD` while the
current branch IS the trunk; and an agent running the steward's CI-only subcommands (`tick`, `verdict`), whose
trust boundary is the default branch's copy in CI. Allowed: everything else, including pushing an issue branch
and `enqueue-pr` / `dequeue-pr` / `queue-status`.

Fail-open, each deliberate: no or unreadable delivery config (the defaults are today's direct-merge path); a
command that does not parse. Commands are read by TOKENS on the quote-masked text: a quoted commit message or PR
body that MENTIONS a merge is one token of data, never a command — while a quoted script PATH (`python
"scripts/merge_steward.py" tick`) is restored and read like an unquoted one, and options before the subcommand
(`--config x`, `--token-file f`, `--verbose`) are skipped, so neither hides a `tick` or a `merge-pr`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import hooklib as lib

HOOK = "merge-steward"
EVENT = "pre-tool-use"  # the dispatcher runs this gate on this event
ORDER = 35  # framework gates 10..90: after claim-before-worktree (30), before issue-filing (40)
SHELL_TOOLS = {"Bash", "shell", "execute_bash", "execute_cmd", "executeBash"}
TOOLS = SHELL_TOOLS  # PreToolUse only: the tool names this gate judges

# The scripts whose subcommands this gate judges, by their file name (`test_github_wrapper.py` is not one), and the
# options of theirs (or of a wrapped command) that take the NEXT token as their value; `--x=y` is one token.
SCRIPT_KINDS = {"github_wrapper.py": "wrapper", "gitlab_wrapper.py": "wrapper", "merge_steward.py": "steward"}
SCRIPT_VALUE_OPTIONS = {"--config", "--token-file", "-o", "--push-option", "--repo", "--receive-pack", "--exec"}
STEWARD_CI_COMMANDS = {"tick", "verdict"}
PYTHON_RE = re.compile(r"^(?:python[\d.]*|py)(?:\.exe)?$", re.IGNORECASE)
CLI_MERGE_RE = re.compile(r"(?:^|[;&|\s(])(?:gh\s+pr\s+merge|glab\s+mr\s+merge)\b")
API_MERGE_RE = re.compile(r"/pulls/\d+/merge\b|/merge_requests/\d+/merge\b")
SEGMENT_RE = re.compile(r"\|\||&&|[;|&\n]")
QUOTED_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'')
# git options that take a VALUE in the next token (between `git` and its subcommand, or after `push`). NOT
# `--signed`: its value is optional and only ever attached (`--signed=yes`), so it never swallows the refspec.
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
PUSH_VALUE_OPTIONS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
PUSH_EVERYTHING = {"--all", "--mirror", "--branches"}


def mask_quotes(command: str) -> Tuple[str, Dict[str, str]]:
    """The command with every quoted string replaced by a placeholder word, and the placeholders' contents.

    Splitting into commands and tokens happens on the MASKED text, so a separator or a `git push` inside a quoted
    commit message is data, never a command; a quoted `-C "<path with spaces>"` value is restored when it is read."""
    contents: Dict[str, str] = {}

    def replace(match: "re.Match[str]") -> str:
        key = f"QUOTED{len(contents)}Q"
        contents[key] = match.group(1) if match.group(1) is not None else (match.group(2) or "")
        return f" {key} "

    return QUOTED_RE.sub(replace, command), contents


def _tokens(segment: str) -> List[str]:
    return segment.split()


def _basename(token: str) -> str:
    return token.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()


def _positionals(args: List[str]) -> List[str]:
    """The non-option arguments, in order: an option is skipped, and a value option takes the next token too."""
    found: List[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg.startswith("-") and len(arg) > 1:
            skip = "=" not in arg and arg in SCRIPT_VALUE_OPTIONS
            continue
        found.append(arg)
    return found


def script_call(segment: str, quoted: Dict[str, str]) -> Optional[str]:
    """The offending text when this (masked) command segment runs the wrapper's merge or the steward's CI-only
    subcommand. A QUOTED token is a script only when it is a path (no whitespace) or follows an interpreter in
    the same segment — so a quoted path with spaces after `python` counts, and a commit message does not."""
    masked = _tokens(segment)
    tokens = [quoted.get(token, token) if token.startswith("QUOTED") else token for token in masked]
    for index, token in enumerate(tokens):
        kind = SCRIPT_KINDS.get(_basename(token))
        if kind is None:
            continue
        if masked[index].startswith("QUOTED") and any(ch.isspace() for ch in token):
            if not any(PYTHON_RE.match(_basename(earlier)) for earlier in tokens[:index]):
                continue
        rest = _positionals(tokens[index + 1 :])
        called = f"{_basename(token)} {' '.join(tokens[index + 1 :])}".strip()
        if kind == "steward" and rest[:1] and rest[0] in STEWARD_CI_COMMANDS:
            return called
        if kind == "wrapper" and (rest[:1] == ["merge-pr"] or rest[:2] == ["mr", "merge"]):
            return called
    return None


def _current_branch(directory: Path) -> str:
    out = lib._git(["rev-parse", "--abbrev-ref", "HEAD"], directory)  # noqa: SLF001 — library helper
    return (out or "").strip()


def trunk_push(  # noqa: C901 — one token walk, in order
    segment: str, trunk: str, cwd: Path, quoted: Optional[Dict[str, str]] = None
) -> Optional[str]:
    """The offending text when this (masked) command segment pushes to the trunk, else None."""
    quoted = quoted or {}
    tokens = [quoted.get(token, token) if token.startswith("QUOTED") else token for token in _tokens(segment)]
    for start, token in enumerate(tokens):
        if Path(token).name.lower() not in ("git", "git.exe"):
            continue
        directory = cwd
        index = start + 1
        while index < len(tokens) and tokens[index].startswith("-"):
            if tokens[index] in GIT_VALUE_OPTIONS and index + 1 < len(tokens):
                if tokens[index] == "-C":
                    candidate = Path(tokens[index + 1])
                    directory = candidate if candidate.is_absolute() else cwd / candidate
                index += 2
            else:
                index += 1
        if index >= len(tokens) or tokens[index] != "push":
            continue
        positional: List[str] = []
        flags: List[str] = []
        rest = tokens[index + 1 :]
        skip = False
        for position, arg in enumerate(rest):
            if skip:
                skip = False
                continue
            if arg.startswith("-"):
                flags.append(arg)
                if arg in PUSH_VALUE_OPTIONS and "=" not in arg and position + 1 < len(rest):
                    skip = True
                continue
            positional.append(arg)
        if any(flag in PUSH_EVERYTHING for flag in flags):
            return f"git push {' '.join(rest)}"
        refspecs = positional[1:]
        if not refspecs:
            if _current_branch(directory) == trunk:
                return f"git push {' '.join(rest)}".strip() + f"   (the current branch is {trunk})"
            continue
        for refspec in refspecs:
            spec = refspec.lstrip("+")
            destination = spec.split(":", 1)[1] if ":" in spec else spec
            destination = re.sub(r"^refs/heads/", "", destination)
            if destination == trunk:
                return f"git push {' '.join(rest)}"
            if destination == "HEAD" and _current_branch(directory) == trunk:
                return f"git push {' '.join(rest)}   (HEAD is {trunk})"
    return None


def run(ctx: lib.Context) -> lib.Decision:
    command = ctx.payload.command
    if not command:
        return lib.allow()
    settings = lib.delivery_settings(ctx.project_dir)
    if settings["merge"] != "steward":
        return lib.allow()
    trunk = settings["trunk"]
    active = lib.strip_quoted(command)
    offending = None
    match = CLI_MERGE_RE.search(active)
    if match:
        offending = match.group(0).strip()
    if offending is None and API_MERGE_RE.search(command) and re.search(r"\b(curl|wget|Invoke-RestMethod)\b", active):
        offending = API_MERGE_RE.search(command).group(0)  # type: ignore[union-attr]
    if offending is None:
        masked, quoted = mask_quotes(command)
        for segment in SEGMENT_RE.split(masked):
            found = script_call(segment, quoted) or trunk_push(segment, trunk, ctx.project_dir, quoted)
            if found:
                offending = found
                break
    if offending is None:
        return lib.allow()
    ctx.log(HOOK, "BLOCK", f"trunk={trunk} command={offending[:160]!r}")
    return lib.block(
        f"{HOOK}: REFUSED — this project lands changes through the merge steward (config/delivery.json: merge =\n"
        f"steward), and `{offending}` would write the trunk `{trunk}` (or run the steward) outside it. Nothing\n"
        f"reaches `{trunk}` that the steward did not test on the exact merged state, so do this instead:\n"
        "  1. Push YOUR branch once (`git -C <worktree> push -u origin <branch>`), open the PR, and get the PR's own\n"
        "     CI green — every failure fixed in one pass.\n"
        "  2. `python scripts/<wrapper>.py enqueue-pr <n>`, then hand the issue off (.claude/docs/delivery.md). The\n"
        "     queue lands it; a conflict, a red train or a red deploy comes back to the issue as `needs-rework`.\n"
        "The steward's `tick` and `verdict` run only in CI, from the default branch's copy of the script.\n"
    )
