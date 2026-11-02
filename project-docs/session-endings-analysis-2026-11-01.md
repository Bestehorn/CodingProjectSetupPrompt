# Half-done sessions and long endings in chess — analysis and options (2026-11-01)

Scope: the 16 chess sessions active since the framework update (chess PR #1409, 2026-10-29), read from their
transcripts, plus the tracker and Actions state of the issues and PRs they handed off (read-only, through chess's
wrapper). Chess ran contract `2026.10.26-delivery-5`; it switched to `merge: steward` + `verification: watcher` on
2026-10-30 20:22 (#1408). No fix is proposed for implementation here; this document decides what to fix.

## What happens, in numbers

**1. Every hand-off is still open, and none is on track to close by itself.** Ten issues were handed off since
the switch. On 2026-11-01:

| Outcome | Issues | Why |
|---|---|---|
| landed, then returned `verification-failed` + `needs-rework` | #1435, #1445, #1486, #1488 | every Deploy dev since 10-31 13:11 (run 612, the last green) fails on an unrelated ChessEngine-Dev subnet export (#566/#1538); the watcher blames every issue the red deploy contains |
| PR queued for hours, green trains not landed | #1462, #1466, #1470, #1507 | the steward has not ticked since 13:56 UTC; trains built at 13:29 went green and wait for a tick |
| PR returned `queue-conflict` | #1480 | a real conflict; the session cleared it and re-queued once |
| blocked behind another issue | #1130 | the same red deploy (#566) |

**2. The queue only moves when someone pushes it.** 39 steward runs since 10-30: 31 `workflow_dispatch` (enqueues
and hand-pushed runs), 8 `schedule`, **0 `workflow_run`**. Every train CI run is started by `github-actions[bot]`,
and GitHub starts no new workflow from an event the `GITHUB_TOKEN` caused — so the template's "a train's CI
completed → tick" trigger can never fire. The 30-minute safety-net schedule delivered 8 runs in about 43 hours
(GitHub delays and drops scheduled runs). Sessions noticed and asked the operator to dispatch the steward by hand.

**3. One hand-off left real work undone.** #1507 was handed off at 2/5 ("3 live-proof items open: no MCP host").
The contract allows only `(post-deploy)` items to be open at a hand-off, but nothing checks it: the issue-loop brake
releases `Phase: HANDED_OFF` on any single-issue run. You caught it ("2/5 is not even remotely finished").

**4. The close-out report is gone.** 10 `/close-session` turns since the update: 0 printed the `CLOSE:` verdict or
the table; 9 archived the session, with the verdict only in the archive call's reason field, which you never see;
one printed no text at all. Before the update: 36 of 95 printed the verdict — and in all 56 turns that archived,
before or after, the verdict was never printed. Making the archive automatic removed the last reports.

**5. The work-issue ending does not answer "can I close this?"** Since the switch the Completion Block does
appear, but reads `ISSUE WORK FINISHED — 0 closed · 1 handed off`, with `9/10`, `2/5`, `State: Status IN_PROGRESS /
Phase HANDED_OFF` and `Backlog: 58 workable issue(s) remain`: "finished" next to "in progress" and "0 closed".
One block is followed by four prose bullets. Before the switch, the 10-29 sessions ended in 2.5–3.0 KB prose
summaries (400–470 words, 7–14 bullets) and no block at all. Your follow-up questions ("Did the deploy work?",
"Why only 9/10?") were answered in 1.4–1.7 KB of prose.

**6. Two instruction sources compete at the end of a turn.** The desktop app asks every turn for a `wrap_up`
recap (2–3 sentences, shown in the next-step box) and then a free-text "closing message … your answer in full".
The framework asks for "the Completion Block and nothing else". Sessions satisfy the app: a prose recap, a prose
closing message, and the app's own "Archive this session now?" button on a handed-off issue.

**7. The run watchdog adds noise and cost to idle sessions.** It fires every 30 minutes while a session is idle and
is deleted only at close-out: one handed-off session (#1130) answered `idle` 29 times — 29 full context re-reads —
and ends on the word `idle`. That session also kept its own "add `reverify` when #566 lands" check, and told you
closing it would stop that check.

## Causes, by owner

| # | Cause | Owner |
|---|---|---|
| C1 | `workflow_run` cannot fire after a `GITHUB_TOKEN`-started train; the schedule is not a safety net on GitHub | framework (steward template) |
| C2 | a red deploy returns EVERY covered issue as `needs-rework`, even when the same failure predates the landing | framework (verdict attribution) |
| C3 | `HANDED_OFF` releases without checking that only `(post-deploy)` items are open | framework (brake) |
| C4 | the Completion Block's grammar counts a hand-off as "finished" and mixes run-state and backlog lines into it | framework (contract text) |
| C5 | auto-archive in the same turn as the report: the report is skipped | framework (close-session), behaviour of the model |
| C6 | the app's wrap_up / closing message invite prose that the framework never maps onto its fixed form | app + framework (no mapping rule) |
| C7 | the watchdog stays armed after a hand-off; sessions keep monitors alive | framework (watchdog scope) |
| C8 | Deploy dev red since 10-31 for an unrelated, tracked cause (#566/#1538) | chess |

C1 and C8 alone guarantee that no hand-off completes today; C2–C7 make it impossible to SEE that from the
session's ending.

## Options

### A. Who owns the issue until it is done?

- **A1 — The session owns it to the end (done = closed).** The session waits, bounded, for the landing and the
  post-deploy verdict and ends only CLOSED or BLOCKED-with-reason. *For:* one glance, no trust in a pipeline
  needed. *Against:* gives back most of the measured waiting (the post-merge phase was 49% of the build span),
  and with chess's deploy red for a day a session would sit, then end BLOCKED anyway.
- **A2 — Hybrid: the session owns it until it LANDS; only the post-deploy check is handed off.** The session waits
  for its train to land (one CI duration when the queue ticks) and ends with "landed as `<sha>`; the deploy check
  is the watcher's". *For:* the merge outcome — conflicts, red trains — is known before the session ends; only an
  environment-level verdict is left. *Against:* about one CI duration of waiting per issue comes back; still needs
  C1 fixed or the wait never ends.
- **A3 — Keep the hand-off as it is, but make it trustworthy and visible (B–D below).** *For:* keeps the waiting
  gain. *Against:* the operator closes sessions on a promise; it is only as good as the pipeline and the report.

### B. Make the pipeline finish what it is handed (required for A2 or A3)

- **B1 — A tick that cannot be lost** (C1): the tick waits for its own trains (a long, bounded job on a
  self-hosted/CodeBuild runner, where minutes are not billed), or the train CI's last job dispatches the steward
  with a token that is not `GITHUB_TOKEN` (a GitHub App or the PAT), or trains are pushed and dispatched with that
  token so `workflow_run` fires. Plus a staleness alarm: a green train older than N minutes is reported.
- **B2 — Fair verdicts** (C2): an issue is a suspect only if the failing deploy job passed on a deploy that did not
  contain its landing; a failure that predates it keeps the issue `awaiting-verification` with "blocked by #1538"
  instead of `needs-rework`, so the backlog loop does not rework good changes.
- **B3 — No premature hand-off** (C3): the brake releases `HANDED_OFF` only when every open checklist item is a
  `(post-deploy)` item (read through the wrapper, as the claim gate already does); anything else is BLOCKED with a
  reason, or finished.

### C. One glance at the end of a session

- **C1 — A fixed SESSION VERDICT as the last thing, mechanically checked.** E.g.

  ```
  SESSION: CAN CLOSE — 2 of 2 issues delivered, 0 need you
  | Issue | Now | Tasks | Next owner |
  | #1486 | landed, awaiting deploy check | 4/4 | verdict watcher |
  | #1517 | filed | — | backlog |
  ```

  The first word answers your question (`CAN CLOSE` / `NEEDS YOU: <one line>` / `NOT DONE: <one line>`); "handed
  off" is never "finished"; no state lines, no backlog count, nothing after the table. A Stop gate refuses a
  registered run's final turn whose last text does not start with that line. *For:* enforced, not requested.
  *Against:* one more gate; the wording must be designed carefully so the gate never wedges a turn.
- **C2 — The desktop app's fields carry the verdict.** A rule: the wrap_up recap is the verdict line; the closing
  message is the verdict table and nothing else. *For:* the next-step box becomes the one-glance view. *Against:*
  only text, no enforcement unless combined with C1.
- **C3 — Close-out reports before it archives.** Either archive only in the turn AFTER the report, or never
  automatically: the verdict line plus a button. A PreToolUse gate on `archive_session` can refuse an archive whose
  turn has not printed `CLOSE:`. *For:* you see the table before the session disappears. *Against:* gives back the
  "Archive?" wait the auto-archive removed, unless the report-then-archive order is kept in one turn and enforced.

### D. Tell the operator later what the pipeline did

- **D1 — One delivery digest** instead of per-session follow-up: the verdict watcher and the steward maintain one
  pinned issue (or a daily comment) listing handed off → landed → verified/closed, bounced (with reason), and
  stuck (queue age, train age). You close sessions at once and read one page when you choose.
- **D2 — `/supervise` (or a new `/delivery-status`) prints that digest on demand** from the tracker, with the
  same columns. Cheaper than D1, nothing runs unattended.

### E. Housekeeping that removes noise

- **E1 — Disarm the watchdog at a hand-off** (nothing is left to resume), and forbid session-held monitors: a
  `reverify` the session wants is posted on the issue, not kept alive in a cron.

## Recommendation

**A2 + B1 + B2 + B3 + C1 + C3 + E1**, with D2 as the cheap follow-up. A2 makes "the session is done" mean "the
change is on the trunk", which you can see; B1–B3 make the queue and the verdict honest; C1 and C3 give you the
one-glance answer and keep it from being archived away; E1 removes the `idle` noise. If the waiting time A2 gives
back is unacceptable, A3 with the same B, C and E items is the alternative — but then D1 or D2 is not optional,
because nothing else would tell you that a handed-off issue never closed.

Independently of the framework, chess's Deploy dev (red since 10-31 13:11, #566/#1538) blocks every verification:
until it is green, every option ends with issues waiting on it.
