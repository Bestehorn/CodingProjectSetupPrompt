"""no-foreground-sleep — PreToolUse(Bash) gate enforcing the never-sleep-poll rule.

Blocks (exit 2) a FOREGROUND shell command that waits with `sleep N` (N at or above 10 s), PowerShell
`Start-Sleep`, or cmd.exe `timeout /t N`, or that sleeps inside a `while`/`until`/`for` loop whatever the
interval. A command the agent runs as a BACKGROUND task (`run_in_background: true` in the tool input) is never
blocked: its completion re-invokes the agent, which is the sanctioned shape of a wait (`parallel-by-default.md`,
`ci-owns-the-test-suite.md`).

WHY A GATE AND NOT ONLY A RULE. Measured 2026-10-01 on an 8-vCPU Windows host at 100 percent CPU, 70 to 75
percent of it kernel time: every Bash tool call costs a login shell of about 21 processes before the command
runs, and 257 of the 2,420 Bash calls in six hours — one in ten — were `sleep 240` to `sleep 580` polls of a
pipeline that the wrapper's blocking `wait` would have awaited in ONE background call. The rule had said
"never sleep-poll" for a month; the gate makes the cheap path the only foreground path.

Fail-open decisions, each deliberate: a sleep under MAX_FOREGROUND_SLEEP_SECONDS settles a just-started
process and is not polling; quoted text and heredoc bodies are stripped first, so writing a script that
CONTAINS a sleep is not blocked; an interval the gate cannot read (`sleep $N`) is blocked only inside a loop,
because a bare variable sleep is rare and an over-blocking gate is the one that gets deleted.
"""

from __future__ import annotations

import re
from typing import Iterator, Optional, Tuple

import hooklib as lib

HOOK = "no-foreground-sleep"
EVENT = "pre-tool-use"  # the dispatcher runs this gate on this event
ORDER = 15  # framework gates 10..90: after no-env-vars (10), before the push gate (20)
SHELL_TOOLS = {"Bash", "shell", "execute_bash", "execute_cmd", "executeBash"}
TOOLS = SHELL_TOOLS  # PreToolUse only: the tool names this gate judges

MAX_FOREGROUND_SLEEP_SECONDS = 10.0

# A heredoc body is data, not a command: `cat > tmp/poll.sh <<'EOF' ... sleep 30 ... EOF` writes a file.
HEREDOC_RE = re.compile(r"<<-?[ \t]*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.DOTALL)
# A wait in command position. GNU `timeout 30 cmd` is a bound, not a wait; only cmd.exe's `timeout /t` sleeps.
SLEEP_RE = re.compile(r"(?:^|[;&|(){}\s])sleep[ \t]+([^\s;&|)]+)")
START_SLEEP_RE = re.compile(r"(?:^|[;&|(){}\s])Start-Sleep\b([^;&|\n)]*)", re.IGNORECASE)
TIMEOUT_T_RE = re.compile(r"(?:^|[;&|(){}\s])timeout(?:\.exe)?[ \t]+/t[ \t]+(\d+)", re.IGNORECASE)
# `while cond; do`, `until cond; do`, `for x in ...; do`, and PowerShell `while (...) {`.
LOOP_RE = re.compile(r"(?:^|[;&|(){}\s])(?:while|until|for)\b.*?(?:\bdo\b|\{)", re.DOTALL)
DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)([smhd]?)$")
UNIT_SECONDS = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def _seconds(token: str) -> Optional[float]:
    match = DURATION_RE.match(token.strip())
    if not match:
        return None
    return float(match.group(1)) * UNIT_SECONDS[match.group(2)]


def _start_sleep_seconds(args: str) -> Optional[float]:
    milli = re.search(r"-m(?:illi)?s(?:econds)?[ \t:]+(\d+(?:\.\d+)?)", args, re.IGNORECASE)
    if milli:
        return float(milli.group(1)) / 1000.0
    secs = re.search(r"-s(?:econds)?[ \t:]+(\d+(?:\.\d+)?)", args, re.IGNORECASE)
    if secs:
        return float(secs.group(1))
    positional = re.match(r"[ \t]*(\d+(?:\.\d+)?)", args)
    return float(positional.group(1)) if positional else None


def waits(active: str) -> Iterator[Tuple[str, Optional[float]]]:
    """Every wait in the ACTIVE command text, as (the text as written, its seconds or None when unreadable)."""
    for match in SLEEP_RE.finditer(active):
        yield f"sleep {match.group(1)}", _seconds(match.group(1))
    for match in START_SLEEP_RE.finditer(active):
        yield f"Start-Sleep{match.group(1).rstrip()}", _start_sleep_seconds(match.group(1))
    for match in TIMEOUT_T_RE.finditer(active):
        yield f"timeout /t {match.group(1)}", float(match.group(1))


def active_text(command: str) -> str:
    """The command with heredoc bodies and quoted strings removed: what the shell would RUN, not echo or write."""
    return lib.strip_quoted(HEREDOC_RE.sub(" ", command))


def run(ctx: lib.Context) -> lib.Decision:
    command = ctx.payload.command
    if not command:
        return lib.allow()
    tool_input = ctx.payload.data.get("tool_input")
    if isinstance(tool_input, dict) and tool_input.get("run_in_background") is True:
        return lib.allow()  # a background wait is the sanctioned shape; its completion re-invokes the agent
    active = active_text(command)
    found = list(waits(active))
    if not found:
        return lib.allow()
    in_loop = bool(LOOP_RE.search(active))
    offending = [
        text for text, seconds in found if in_loop or (seconds is not None and seconds >= MAX_FOREGROUND_SLEEP_SECONDS)
    ]
    if not offending:
        return lib.allow()
    shape = "a sleep inside a loop" if in_loop else f"a wait of {MAX_FOREGROUND_SLEEP_SECONDS:g}s or more"
    rules = ctx.host.rules_dir
    return lib.block(
        f"{HOOK}: `{offending[0]}` in a FOREGROUND command is refused — {shape} is the sleep-poll that\n"
        f"{rules}/parallel-by-default.md and {rules}/ci-owns-the-test-suite.md forbid. Every Bash tool call\n"
        "costs a login shell of about 20 processes before your command runs, and a repeated sleep holds the turn\n"
        "open for nothing. Wait the sanctioned way and do unblocked work meanwhile:\n"
        "  - a pipeline, run or merge: the wrapper's blocking wait (`pipeline wait <id>` on GitLab, `wait-run <id>`\n"
        "    on GitHub) as a BACKGROUND task; its completion re-invokes you.\n"
        "  - anything else (a local process, a file that must appear): run THIS command with\n"
        "    `run_in_background: true` — one call, one process tree, and its completion re-invokes you.\n"
        f"A sleep under {MAX_FOREGROUND_SLEEP_SECONDS:g}s that lets a process settle passes; a loop around a sleep "
        "never does.\n"
    )
