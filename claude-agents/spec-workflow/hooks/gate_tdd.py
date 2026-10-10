"""spec-tdd-gate — PreToolUse(Bash) gate for the spec/TDD workflow.

Blocks (exit 2) when the command bypasses verification, or is a `git push` while a task marked complete in the
active spec has no capture or the newest capture is red or riddled with skips, or is a `git push` under CI-OUTAGE
MODE with no green full-suite capture. Everything else is allowed. The gate is on PUSH, not commit: commits are
cheap and frequent; the push is where evidence is owed.

THE BYPASS CLASSIFIER READS TOKENS, NOT TEXT. The command is split into shell words (`shlex`, POSIX rules, with
`;`, `&&`, `||`, `|` and the newline as separators) and each simple command is parsed the way git parses it: the
`git` word (any path, `git.exe` included), git's own global options (`-C <dir>`, `-c <key>=<value>`, `--git-dir`
and the rest), the subcommand, then its arguments up to `--`. A bypass is:
  * for `commit`: `--no-verify` or any unique abbreviation git accepts (`--no-veri`, `--no-verif`; `--no-ver` is
    ambiguous with `--no-verbose` and git refuses it), or `-n` on its own or inside a short-option cluster —
    `-an`, `-qn`, `-na` — but NOT after a letter that takes a value (`-mn` is `-m "n"`, a message);
  * for `push`: `--no-verify` and its unique abbreviations (`-n` on push is `--dry-run`, harmless);
  * for commit and push alike: `-c core.hooksPath=<anything>`, which points git at hooks that are not the
    tracked ones; and `git config core.hooksPath ...` (set or unset; `--get`/`--list` are reads), which does the
    same for every later command in the clone.
Not a bypass: anything after `--` (pathspecs: `git commit -m x -- -n`), anything inside a quoted word (`-m "use -n
carefully"`), and `git stash push`. A command `shlex` cannot split (an unbalanced quote) falls back to the
quote-stripped regular expressions in `hooklib`. Measured before this: a text classifier let 37 of 79 bypass
spellings through and refused `-- -n`.

Failure direction: everything up to the push judgement runs without touching state, so a defect in the state
code can only ever refuse a PUSH — never an ordinary shell command.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

import hooklib as lib

HOOK = "spec-tdd-gate"
EVENT = "pre-tool-use"  # the dispatcher runs this gate on this event
ORDER = 20  # framework gates 10..90; a project gate takes >100 (or <10 to run first)
SHELL_TOOLS = {"Bash", "shell", "execute_bash", "execute_cmd", "executeBash"}
TOOLS = SHELL_TOOLS  # PreToolUse only: the tool names this gate judges

BYPASS_COMMIT_RE = re.compile(r"(--no-verify|\s-n(\s|$))")  # the fallback, on quote-stripped text
OPERATOR_CHARS = ";&|\n"
CONTINUATION_RE = re.compile(r"\\\r?\n")  # bash removes an unquoted backslash-newline pair; shlex does not
GIT_NAMES = {"git", "git.exe"}
# git's own options that take their value as the NEXT word (the `--opt=value` spelling is one word).
GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
# `git commit` short options that take a value: in a cluster, the letters after one of these are its value; when
# the cluster ENDS with one, the next word is its value (`-m --no-verify` is the message "--no-verify").
COMMIT_VALUE_SHORT = set("mFCctS")
PUSH_VALUE_SHORT = set("o")
# Long options that take their value as the next word when written without `=` (`--message --no-verify`).
COMMIT_LONG_WITH_VALUE = {
    "--message",
    "--file",
    "--author",
    "--date",
    "--reuse-message",
    "--reedit-message",
    "--fixup",
    "--squash",
    "--cleanup",
    "--trailer",
    "--template",
    "--pathspec-from-file",
}
PUSH_LONG_WITH_VALUE = {"--repo", "--push-option", "--receive-pack", "--exec"}
NO_VERIFY = "--no-verify"
NO_VERIFY_MIN_PREFIX = "--no-veri"  # the shortest abbreviation that is unique against --no-verbose
HOOKS_PATH_RE = re.compile(r"^core\.hookspath(=|$)", re.IGNORECASE)
CONFIG_READ_FLAGS = {"--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin", "--show-scope"}


@dataclass
class Classification:
    is_commit: bool = False
    is_push: bool = False
    bypass: str = ""  # the forbidden form found, or ""


def _words(command: str) -> Optional[List[str]]:
    lexer = shlex.shlex(CONTINUATION_RE.sub("", command), posix=True, punctuation_chars=OPERATOR_CHARS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return None


def _is_operator(words: List[str], index: int) -> bool:
    word = words[index]
    if not word or not all(ch in OPERATOR_CHARS for ch in word):
        return False
    # shlex splits a redirection's `&` into a word of its own (`2>&1` -> `2>`, `&`, `1`); that `&` separates nothing.
    previous = words[index - 1] if index > 0 else ""
    following = words[index + 1] if index + 1 < len(words) else ""
    return not (word == "&" and (previous.endswith((">", "<")) or following.startswith(">")))


def _simple_commands(words: List[str]) -> Iterator[List[str]]:
    current: List[str] = []
    for index, word in enumerate(words):
        if _is_operator(words, index):
            if current:
                yield current
            current = []
        else:
            current.append(word)
    if current:
        yield current


def _is_no_verify(word: str) -> bool:
    name = word.split("=", 1)[0]
    return len(name) >= len(NO_VERIFY_MIN_PREFIX) and NO_VERIFY.startswith(name)


def _classify_simple(words: List[str]) -> Classification:  # noqa: C901 — git's own option grammar, in one place
    found = Classification()
    start = next((i for i, w in enumerate(words) if w.replace("\\", "/").rsplit("/", 1)[-1].lower() in GIT_NAMES), None)
    if start is None:
        return found
    hooks_path_override = False
    i = start + 1
    while i < len(words) and words[i].startswith("-"):
        word = words[i]
        if word in GIT_GLOBAL_WITH_VALUE:
            value = words[i + 1] if i + 1 < len(words) else ""
            if word == "-c" and HOOKS_PATH_RE.match(value):
                hooks_path_override = True
            i += 2
            continue
        if word.startswith("-c") and not word.startswith("--") and HOOKS_PATH_RE.match(word[2:]):
            hooks_path_override = True
        i += 1
    if i >= len(words):
        return found
    subcommand = words[i].lower()
    args = words[i + 1 :]
    if subcommand == "config":
        touches_hooks_path = any(HOOKS_PATH_RE.match(a) for a in args)
        if touches_hooks_path and not any(a in CONFIG_READ_FLAGS for a in args):
            found.bypass = "git config core.hooksPath"
        return found
    if subcommand == "commit":
        found.is_commit = True
    elif subcommand == "push":
        found.is_push = True
    else:
        return found
    if hooks_path_override:
        found.bypass = "-c core.hooksPath=…"
        return found
    value_short = COMMIT_VALUE_SHORT if found.is_commit else PUSH_VALUE_SHORT
    long_with_value = COMMIT_LONG_WITH_VALUE if found.is_commit else PUSH_LONG_WITH_VALUE
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False  # the previous option's value, whatever it looks like
            continue
        if arg == "--":
            break
        if arg.startswith("--"):
            if _is_no_verify(arg):
                found.bypass = NO_VERIFY
                break
            skip_next = "=" not in arg and arg in long_with_value
            continue
        if re.fullmatch(r"-[A-Za-z]+", arg):
            for position, letter in enumerate(arg[1:], start=1):
                if found.is_commit and letter == "n":
                    found.bypass = "-n"
                    break
                if letter in value_short:
                    skip_next = position == len(arg) - 1  # a value letter at the END takes the next word
                    break  # otherwise the rest of the cluster is this option's value
            if found.bypass:
                break
    return found


def classify(command: str) -> Classification:
    """The command's git classification across every simple command it contains."""
    words = _words(command)
    total = Classification()
    if words is None:
        stripped = lib.strip_quoted(command)
        total.is_commit = lib.is_git_commit(stripped)
        total.is_push = lib.is_git_push(stripped)
        if total.is_commit and BYPASS_COMMIT_RE.search(stripped):
            total.bypass = "-n/--no-verify"
        elif total.is_push and NO_VERIFY in stripped:
            total.bypass = NO_VERIFY
        return total
    for simple in _simple_commands(words):
        part = _classify_simple(simple)
        total.is_commit = total.is_commit or part.is_commit
        total.is_push = total.is_push or part.is_push
        if part.bypass and not total.bypass:
            total.bypass = part.bypass
    return total


def run(ctx: lib.Context) -> lib.Decision:
    found = classify(ctx.payload.command)
    if found.bypass == "git config core.hooksPath" or found.bypass.startswith("-c core.hooksPath"):
        return lib.block(
            f"{HOOK}: `{found.bypass}` points git at hooks other than the tracked ones under .githooks/ — every "
            "verification this project runs at commit and push time is bypassed by it. Fix the reported issue "
            "instead; the tracked hooks are the project's, not an obstacle."
        )
    if not found.is_commit and not found.is_push:
        return lib.allow()
    if found.is_commit and found.bypass:
        return lib.block(
            f"{HOOK}: 'git commit --no-verify'/-n is forbidden. The pre-commit hook is lint + security only and "
            "takes about a second — there is nothing to save by skipping it, and a bypass is how a secret or a "
            "lint regression reaches the remote. Fix the reported issue instead."
        )
    if found.is_push and found.bypass:
        return lib.block(
            f"{HOOK}: 'git push --no-verify' is forbidden. The pre-push hook is the type check, plus the full "
            "suite when CI-OUTAGE MODE is declared — and in that state it is the ONLY thing verifying this push. "
            "Fix the cause instead of bypassing the hook."
        )
    if not found.is_push:
        return lib.allow()  # commits carry no evidence requirement

    # From here on the command IS a push, so failing closed refuses only that push. The library self-test is
    # called HERE and not above: a truncated hooklib.py must refuse a push and nothing else.
    try:
        if not lib.selftest():
            raise RuntimeError("hooklib self-test failed")
        return _judge_push(ctx)
    except Exception as exc:  # noqa: BLE001 — any abort refuses the PUSH rather than allowing it unverified
        return lib.block(
            f"{HOOK}: ABORTED ({exc.__class__.__name__}: {exc}) before reaching a decision — "
            "refusing the PUSH rather than allowing it unverified. Fix the hook or its library, then push."
        )


def _judge_push(ctx: lib.Context) -> lib.Decision:  # noqa: C901 — one check per push precondition
    state_file = ctx.owned_state_file()
    if state_file is None or not state_file.is_file():
        return lib.allow()  # no spec workflow this session owns; the bypass bans were enforced above

    phase = ctx.field(state_file, "Phase")
    spec_value = ctx.field(state_file, "CURRENT_SPEC")
    if not lib.is_implementation_phase(phase):
        return lib.allow()
    if not spec_value.strip():
        # An unrecorded CURRENT_SPEC is judged by the Stop gate at turn-end; blocking every push would over-block.
        return lib.allow()

    spec_dir = _resolve_spec_dir(ctx, state_file, spec_value)
    problems: List[str] = []
    tasks = spec_dir / "tasks.md"
    if tasks.is_file():
        ids, _unparseable = lib.checked_task_ids(tasks)
        for task_id in ids:
            if lib.is_heading_id(task_id, ids):
                continue
            if (
                lib.capture_for_task(spec_dir, "green", task_id) is None
                and lib.capture_for_task(spec_dir, "red", task_id) is None
            ):
                problems.append(
                    f"  - task {task_id} is marked complete but no capture covers it "
                    f"(evidence/green/{task_id}.txt, evidence/red/{task_id}.txt, or a wave capture "
                    f"whose '# tasks:' line names {task_id}).\n"
                )

    latest = lib.latest_capture(spec_dir, "green")
    if latest is not None:
        body = lib.capture_body(latest)
        if lib.has_failures(body):
            problems.append(f"  - newest green capture ({latest}) shows failures/errors.\n")
        if lib.has_skips(body):
            problems.append(
                f"  - newest green capture ({latest}) contains skipped/xfail tests — resolve them, "
                "do not push around them.\n"
            )

    # CI-OUTAGE MODE: the marker lives in the SHARED git dir, so one declaration covers every worktree.
    common = _git_common_dir(ctx)
    if common is not None and (common / "ci-outage-mode").is_file():
        regress = lib.latest_capture(spec_dir, "regress")
        if regress is None:
            problems.append(
                f"  - CI-OUTAGE MODE is declared, so no CI run will verify this push, and there is no "
                f"full-suite capture under {spec_dir / 'evidence' / 'regress'}. Run "
                "'python scripts/run_tests.py' and capture it.\n"
            )
        elif lib.has_failures(lib.capture_body(regress)):
            problems.append(f"  - CI-OUTAGE MODE is declared and the newest full-suite capture ({regress}) is red.\n")

    if problems:
        return lib.block(
            f"{HOOK}: not safe to push — the work is not yet proven:\n"
            + "".join(problems)
            + "Commits are free; a push asks CI and other people to take this seriously. Finish the "
            "batch, capture the evidence, then push once."
        )
    return lib.allow()


def _resolve_spec_dir(ctx: lib.Context, state_file: Path, spec_value: str) -> Path:
    # Same order as the Stop gate's resolver: project root, recorded worktree, the value as given.
    candidates = [ctx.project_dir / spec_value]
    worktree = ctx.field(state_file.parent / lib.RESUME_FILENAME, "WORKTREE")
    if worktree and not lib.is_placeholder(worktree):
        candidates.append(Path(worktree) / spec_value)
    candidates.append(Path(spec_value))
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return Path(spec_value)


def _git_common_dir(ctx: lib.Context) -> Optional[Path]:
    out = lib._git(["rev-parse", "--git-common-dir"], ctx.process_cwd)  # noqa: SLF001 — library helper
    if not out:
        return None
    common = Path(out.strip())
    # A relative --git-common-dir is relative to the CURRENT directory, not to the top level.
    return common if common.is_absolute() else ctx.process_cwd / common
