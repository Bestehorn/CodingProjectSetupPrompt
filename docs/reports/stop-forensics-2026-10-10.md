# Why sessions stop and have to be continued by hand — forensics, 2026-10-10

Question asked by the operator: many sessions stop working and print a summary; `/continue-work` is
needed to get them going again, and most of those stops have no visible reason. What causes them, and
how are they eradicated?

Method. The Claude Code transcripts of the three projects on this machine (chess, AWSBedrockGateway,
Insights Analyzer; 241 transcripts touched in the window) were read record by record for the last 30
days (2026-09-10 to 2026-10-10), together with the projects' Stop-gate decision logs. Three readings:
(A) what preceded every `/continue-work` the operator typed; (B) what followed every Stop-gate
refusal; (C) what followed every background-task notification; and (D) how the operator reacted to
every turn end, by the hooks' verdict. Scripts: `tmp/velocity-analysis/stop_forensics2.py` (not
tracked). Two earlier passes undercounted because the transcript's top-level `type` key follows the
large `message` object in assistant records; the final pass parses every candidate line in full.

## Findings

**1. The Stop gates work.** 1,227 refusals in 30 days; after every one of them the model continued.
Not one refusal was followed by an operator prompt or by nothing. The 1,012 blocks a week the decision
logs show are real brakes, not noise.

**2. Since the Python hooks landed (2026-10-03), no restart followed a model that simply decided to
stop.** Every "the hooks allowed a summary and the operator had to continue" case dates from before
the rewrite (2026-09-12 to 09-18), when the bash hooks were inert. Those idle periods were the long
ones: median 220 to 290 minutes, about 48 hours in total.

**3. What the 49 `/continue-work` prompts of the window followed:**

| What preceded the restart | Count | Idle before the restart |
|---|---|---|
| a background task reported `stopped`; the harness answered with the synthetic "No response requested." and never invoked the model | 15 | median 8 min, 8.8 h total |
| an API error ended the turn (`401 Unauthorized` in clusters at 10-05 19:48, 10-08 05:24, 10-09 14:30; one `Prompt is too long`) | 10 | median 2 min, 4.5 h total |
| no Stop-hook record (bash era) and a summary or progress report | 10 | median 220 to 290 min, 48 h total |
| the hooks allowed a summary or progress report (bash era: exit 1 recorded as a summary, no refusal) | 5 | median 39 min, 17.5 h total |
| the model ended its turn to wait for CI or a background run ("its exit line will notify me"); the notification never woke it | 3 | median 1 min |
| a completed notification answered synthetically; no model turn | 3 | 0 min |
| other | 3 | |

**4. Why a background task does not wake the session.** Of 82 `stopped` notifications, 0 were followed
by a model turn; 68 were followed by an operator prompt, 12 by another notification. The reason text is
uniform: "didn't finish before the previous session ended" (25 shell commands, 15 resumed agents, more
of the same). These are client restarts and updates: the previous process died, its tasks were orphaned,
and on resume the harness reports them without invoking the model. Of 48 `failed` notifications, 12 were
also answered synthetically. Completed notifications do wake the model (3,236 of them; 3 exceptions).

**5. Compaction plays no role.** One restart of 49 sat after a compaction.

**6. The operator's own reaction, all turn ends.** Of 243 human prompts that followed a model's final
text, 30 were continue-like (`/continue-work`, "go on", "proceed"); 20 of those followed a stop the hooks
had allowed, 10 a stop with no hook record. In the Python-hooks era the continue-like reactions after an
allowed stop are the "ended its turn to wait" cases of finding 3.

## What follows

- **Restarts after a client update or restart are the one unavoidable case.** The harness does not
  invoke the model for an orphaned task, so the operator's `/continue-work` is the correct and only
  path. What the framework can do is make the resumed session re-dispatch its waits at once: the
  `continuous-work-reinject` gate's `source=resume` text should say that every background task of the
  previous process is gone and the waits must be re-issued.
- **Ending the turn to wait is the fixable case.** A wait on CI or a local suite that is run in the
  background requires a notification to wake the session, and a stopped or failed task produces none.
  A wait run in the FOREGROUND with a bounded timeout (the Bash tool allows 10 minutes; `pipeline wait
  --timeout 540`, re-issued until the state is terminal) keeps the turn alive and costs nothing: the
  model is idle during a tool call either way, and the host runs one process. The `no-foreground-sleep`
  gate refuses `sleep` and poll loops, not a wrapper wait; the rule text that sends the wait to the
  background (`parallel-by-default.md`, `native-tools-over-shell.md`, REVISION_NOTICE items 6 and 8)
  should be inverted for waits whose result the session needs. A Stop gate that reads the final
  assistant text from the transcript the Stop payload names, and refuses a turn end whose last lines
  say "waiting … will notify me", closes the case mechanically for sessions with and without claimed
  work.
- **API errors are infrastructure.** The 401 clusters are credential expiry of the desktop app at
  specific times; re-authentication plus `/continue-work` is the path. "Prompt is too long" (one case)
  is a context overflow the harness's own compaction did not prevent; the context budgets of the
  2026-09-30 revision are the framework's lever there.
- **Nothing to do about the bash era.** Its stops were the long idle periods of this window and they
  ended with the Python rewrite.

Numbers that change what to do: 1,227 refusals honoured; 82 stopped tasks, 0 model turns; 30 continue-like
reactions in 243 turn ends. Everything else above is detail.
