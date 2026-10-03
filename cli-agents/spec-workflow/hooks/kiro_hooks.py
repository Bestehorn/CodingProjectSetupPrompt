#!/usr/bin/env python
"""kiro_hooks.py — the ONE entry point for every Kiro CLI hook of this framework: one interpreter per event.

Usage (wired in an agent's JSON `hooks` as a command string; `python` resolves on PATH, no bash involved):
    "agentSpawn": [ { "command": "python .kiro/hooks-bin/kiro_hooks.py agentSpawn" } ]
    "preToolUse": [ { "command": "python .kiro/hooks-bin/kiro_hooks.py preToolUse", "matcher": "execute_bash" } ]
    "stop":       [ { "command": "python .kiro/hooks-bin/kiro_hooks.py stop" } ]

The gates are the Claude Code gates (`hooklib.py`, `hooks.py`, `gate_*.py` — install them beside this file) run
with the Kiro host: state under `.kiro/agent-state/`, rules under `.kiro/steering/`, hooks under
`.kiro/hooks-bin/`. Only the block conventions differ, and they are applied here:
  * agentSpawn: stdout is added to the agent's context; exit 0.
  * preToolUse: exit 2 blocks, stderr is returned to the model (identical to Claude Code).
  * stop: a block is `{"decision":"block","reason":"..."}` on STDOUT with exit 0; Kiro feeds the reason back
    as a new user message. Exit 0 with no JSON lets the agent stop.
Kiro has no compaction hook, so the re-inject runs at every agentSpawn (launch and relaunch). Without the
library (missing or truncated beside this file) a stop still blocks and a push is still refused, as in hooks.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import hooks  # noqa: E402

EVENTS = {"agentSpawn": "session-start", "preToolUse": "pre-tool-use", "stop": "stop"}


def main(argv: "list[str]") -> int:
    if len(argv) < 2 or argv[1] not in EVENTS:
        sys.stderr.write(__doc__ or "")
        return 2
    event = EVENTS[argv[1]]
    payload_text = sys.stdin.read() if not sys.stdin.isatty() else ""
    if hooks.lib is None:
        code, message = hooks.degraded(event, payload_text)
        if event == "stop" and code == 2:
            sys.stdout.write(json.dumps({"decision": "block", "reason": message}) + "\n")
            return 0
        if message:
            sys.stderr.write(message)
        return code
    decision = hooks.dispatch(event, payload_text, host=hooks.lib.KIRO, hooks_dir=HERE)
    if event == "stop":
        if decision.blocked:
            sys.stdout.write(json.dumps({"decision": "block", "reason": decision.stderr}) + "\n")
            return 0
        if decision.stderr:
            sys.stderr.write(decision.stderr)
        return 0
    if decision.stdout:
        sys.stdout.write(decision.stdout)
    if decision.stderr:
        sys.stderr.write(decision.stderr)
    return decision.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
