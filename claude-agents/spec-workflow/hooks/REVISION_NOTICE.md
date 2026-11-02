Valid-until: 2026-12-15
## FRAMEWORK REVISION 2026-09-30 IS IN FORCE (amended through 2026-11-02: items 8–12) — it supersedes the phase text in your agent definition and command body

The rules, phase fragments, agents and hooks of this project were replaced. Apply this to
the work in flight NOW, then continue:

1. Read `.claude/rules/proportionality.md`, `.claude/rules/parallel-by-default.md`,
   `.claude/docs/review-contract.md`, and the fragments under `.claude/specs/_workflow/phases/`.
2. Re-tier your issue from its ASK: S = a value, default, config, message or doc change, or a
   bounded local fix, however many files it touches; M = a feature across components with a
   design choice; L = a subsystem. Record `Tier:` in prompt.md and one DL entry.
3. Freeze scope: no new requirement, criterion, property, mechanism or protocol; anything outside
   the ask goes to `## Residuals`; a spec artefact over its tier cap is CUT, never grown.
4. Review loops: an open A/B names the criterion it protects or a failure class AND carries a
   proposed edit, else it is C; review only the delta; fix C/D in the same author pass; past the
   tier cap (S 2, M 4, L 6) approve as reviewed and record the open findings as residuals.
5. Implement in waves of disjoint files: a wave's TEST tasks together, then its IMPL tasks; one
   capture per wave with a `# tasks:` header; one commit per wave.
6. Never ask the operator to sign in, copy or observe anything: a human step is a residual, and
   the end-to-end check runs in the pipeline after the merge.
7. Issue notes only at phase transitions; DL entries only for decisions; a question is five lines
   with the recommended option first, asked at the START in one batch; reversible decisions are
   decided, not asked.
8. (2026-10-03) Files through Read, Grep, Glob, Write and Edit — never `cat`, `grep`, `ls`, `sed`
   or a heredoc; a shell step is ONE call; suites through `scripts/run_tests.py` (a host-wide
   slot), a synth or harness under `python scripts/suite_semaphore.py run -- <command>`.
9. (2026-10-10) Close-out runs the reaper in the FOREGROUND (Bash `timeout` 600000) in its header's
   bounded form — the framework's: `python scripts/reap_agent_temp.py --scoped-temp tmp/os-temp
   --apply --budget-minutes 9`, again while it exits 3. An oversize ledger row: `python
   scripts/memory_compile.py reconcile --apply`. After adding a gate, re-run `python
   .claude/hooks/hooks.py registration` (the matcher is derived from the gates).
10. (2026-10-10) NEVER END A TURN TO WAIT and never `sleep` in a tool call: a background task dies
    with the process and never wakes you. Do every unblocked piece of work first, then wait in the
    FOREGROUND, bounded — `python scripts/<wrapper>.py wait-run <id> --timeout-seconds 540`
    (GitLab: `pipeline wait <id> --timeout-seconds 540`), Bash `timeout` 600000, re-issued while it
    exits 11. After a resume every background task is gone: re-issue the waits.
11. (2026-10-26) DELIVERY: read `.claude/docs/delivery.md` at the PR phase. Before the push:
    `Refs #N` (never a closing keyword, in the PR or in a commit), the issue note, the ticks,
    `(post-deploy)` on items only a deploy can prove, the ledger rows. Under `merge: steward` only
    the steward lands the trunk — you never merge. Returned work (`needs-rework`) is selected before
    new work. Arm the run watchdog ONCE per process (the `CronCreate` the session-start context
    prints). Release only THIS run's lock, removing the directory with its owner record (never
    `rmdir`). On GitLab "PR #n" is the MR `!iid`.
12. (2026-11-02) YOUR SESSION OWNS ITS PR UNTIL IT LANDS, AND ENDS WITH ONE VERDICT. After
    `enqueue-pr`: `Phase: QUEUED`, then `python scripts/<wrapper>.py wait-landed <PR>
    --timeout-seconds 540` in the foreground, re-issued on 11; 10 = it came back: fix every cause
    in one pass, push once, re-enqueue. Landed: `Phase: HANDED_OFF` — only the post-deploy check is
    the watcher's; the brake first runs `check-handoff <issue>` (every PR landed, only
    `(post-deploy)` items open). A loop records `QUEUED_PRS` and waits for them before DONE. End
    every work run with `SESSION: CAN CLOSE | NEEDS YOU | NOT DONE — <one line>`, a blank line, the
    table, NOTHING after it (delivery.md §7; the `session-verdict` gate; the wrap_up recap repeats
    that line); `/close-session` prints it BEFORE it archives. `CronDelete` the watchdog at the
    hand-off; never keep a session alive to watch another issue or a deploy.
