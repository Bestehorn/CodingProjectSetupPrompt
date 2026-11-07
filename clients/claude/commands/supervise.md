---
description: Host supervisor — find the runs whose last turn an API error ended (recorded by the stop-failure-recorder gate) and that their own run watchdog has not brought back, and resume each through the harness's cross-session messaging, with a bounded backoff. Reads run state; never touches another run's worktree, branch or issue.
argument-hint: "[nothing — optionally a run id to look at only that run]"
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash(python .claude/hooks/supervisor.py:*), ListAgents, SendMessage
---

Bring back the sessions an API error stopped. A provider 400 or 5xx, an expired credential or a
rate limit ends a turn without any Stop hook, and nothing runs again until someone notices
(measured 2026-10-25: 17 such turns idled a median 7.5 hours each). Every registered run arms its
own watchdog (`continuous-work.md`), so this command is the BACKSTOP: for a session started before
the watchdog existed, one whose watchdog expired, or one whose process came back without it.

Run it by hand, or unattended every 15 minutes: a Desktop scheduled task (one per project), or
`/loop 15m /supervise` in a session kept for the purpose (that session holds no claim and does no
other work).

**1. Scan.** `python .claude/hooks/supervisor.py scan --json` judges every resume request the
`stop-failure-recorder` gate left (`.claude/agent-state/issue-work-orchestrator/.resume-requests/`):

| Verdict | Means | You |
|---|---|---|
| `finished` | the run has released since (terminal, handed off, idle, a recorded `AWAITING_USER`) | nothing — the scan already archived it |
| `recovered` | the session replied after the failure | nothing — archived |
| `waiting` | still stalled, the backoff has not passed (the watchdog gets the first five minutes) | nothing this time |
| `due` | still stalled, attempts left, backoff passed | step 2 |
| `exhausted` | six resumes did not bring it back | step 3 |

A request whose error class cannot be resumed (billing, an account hold, an organisation not
allowed, a model not found) is never written; a person has to act on those.

**2. Resume each `due` run.** `ListAgents` lists the local sessions you can message. Match the
request's `session_id` (and its `cwd`) to exactly ONE row — on any doubt, do not guess: `python
.claude/hooks/supervisor.py note <run-id> unreachable` and go on. With a match, send the text
`python .claude/hooks/supervisor.py message <run-id>` prints, VERBATIM, with `SendMessage` to that
row's name, then `note <run-id> resumed`. The message tells the session to resume per
`/continue-work` and states that it approves nothing: it carries no decision, no answer to an open
question and no permission — a run waiting on its operator stays waiting. A session that refuses
inbound messages (its user settings do not accept cross-session messages) is `unreachable`.

**3. Report.** One line per run you acted on, then the `exhausted` and `unreachable` ones, each
with its run id, issue, phase, error class and time since the failure — those need a person (open
the session and type `/continue-work`). Nothing else: no narration, no advice.

Never send anything to a session whose run is not in a `due` request, never message a session
twice in one scan, never edit another run's state files, locks, worktree, branch or issue, and
never retry an `exhausted` run. No AI attribution anywhere (`no-ai-attribution.md`).
