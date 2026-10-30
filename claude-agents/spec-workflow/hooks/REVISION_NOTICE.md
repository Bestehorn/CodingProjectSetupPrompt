Valid-until: 2026-12-15
## FRAMEWORK REVISION 2026-09-30 IS IN FORCE (amended 2026-10-03, item 8; 2026-10-10, items 9 and 10; 2026-10-26, item 11; 2026-10-30, items 9 and 11) — it supersedes the phase text in your agent definition and command body

The rules, phase fragments, agents and hooks of this project were replaced. Apply this to
the work in flight NOW, then continue:

1. Read `.claude/rules/proportionality.md`, `.claude/rules/parallel-by-default.md`,
   `.claude/docs/review-contract.md`, and the fragments under `.claude/specs/_workflow/phases/`.
2. Re-tier your issue from its ASK: S = a value, default, config, message or doc change, or a
   bounded local fix, however many files it touches; M = a feature across components with a
   design choice; L = a subsystem. Record `Tier:` in prompt.md and one DL entry.
3. Freeze scope: from here on no new requirement, criterion, property, mechanism or protocol.
   Anything outside the ask goes to `## Residuals`. A spec artefact over its tier cap is CUT,
   never grown.
4. In a review loop: every open A/B must name the acceptance criterion it protects or a
   failure class AND carry a proposed edit, else it is C. Review only the delta from now on.
   Fix C/D in the same author pass without a new round. Past the tier cap (S 2, M 4, L 6):
   approve the spec as reviewed, record open findings as residuals, move to tasks.
5. Implementing: group the remaining tasks into waves of disjoint files; dispatch a wave's
   TEST tasks together, then its IMPL tasks together; one capture per wave with a
   `# tasks:` header; one commit per wave.
6. Never `sleep` in a tool call — wait on CI with the wrapper's `pipeline wait` / `wait-run`
   (item 10 says how). Never ask the operator to sign in, copy or observe anything: a human
   step is a residual, and the end-to-end check runs in the pipeline after the merge.
7. Issue notes only at phase transitions; DL entries only for decisions; a question is five
   lines with the recommended option first; reversible decisions are decided, not asked.
8. (2026-10-03) A shell call is the expensive tool: read, search and write files with Read,
   Grep, Glob, Write and Edit — never `cat`, `grep`, `ls`, `sed` or a heredoc — and chain a
   shell step into ONE call. The `no-foreground-sleep` gate refuses a foreground `sleep` of
   10 s or more and any sleep in a loop; a wait is the wrapper's `wait` (item 10). Local
   suites go through `scripts/run_tests.py`, which holds a host-wide suite slot; a synth,
   `npm test` or a harness runs under
   `python scripts/suite_semaphore.py run -- <command>` (`.claude/rules/native-tools-over-shell.md`).
9. (2026-10-10) At close-out, run the reaper in the FOREGROUND (Bash `timeout` 600000) in the
   bounded form its header documents — the framework's is `python scripts/reap_agent_temp.py
   --scoped-temp tmp/os-temp --apply --budget-minutes 9`; a project's own reaper keeps its own
   flags — and run it AGAIN while it says its budget ran out (the framework's: exit 3). An
   oversize ledger row is compacted by `python scripts/memory_compile.py reconcile --apply`,
   not rewritten by hand. After adding a gate on another tool, re-run
   `python .claude/hooks/hooks.py registration`: the matcher is derived from the gates present.
10. (2026-10-10) NEVER END A TURN TO WAIT. A background task dies with the session's process
    and a stopped task never wakes the model (measured over 30 days: 82 of 82); the operator
    then finds an idle session. Do every unblocked piece of work first; when nothing unblocked
    remains, wait in the FOREGROUND with a bounded timeout — `python scripts/<wrapper>.py
    wait-run <id> --timeout-seconds 540` (GitLab: `pipeline wait <id> --timeout-seconds 540`),
    Bash `timeout` 600000, re-issued while it exits 11 — then act on the verdict. A background
    task is for output you read LATER while you keep working in the same turn, never for a
    wait you need before continuing. The `no-idle-wait` Stop gate refuses a turn whose final
    text ends to wait ("waiting on it in the background", "its exit line will notify me").
    After a RESUME, every background task of the previous process is gone: re-issue the waits.
11. (2026-10-26) DELIVERY, READ `.claude/docs/delivery.md` AT THE PR PHASE. Where
    `config/delivery.json` says `merge: steward`, a PR whose own CI is green is ENQUEUED
    (`python scripts/<wrapper>.py enqueue-pr <n>`) and handed off: you never merge it and never
    wait for the queue, the trunk run or the deploy — the steward tests the exact merged state and
    lands it, the deploy's verdict job closes the issue by ancestry, and anything red comes back
    labelled `needs-rework`, which SELECT takes before new work. Before the push: `Refs #N` (never
    `Closes`), the issue note, the ticks, `(post-deploy)` on items only a deploy can prove, the
    ledger rows. A single-issue run then records `Phase: HANDED_OFF`; a loop records
    `Phase: LOAD_ISSUES` and goes on. Ask every open product question at CLASSIFY, in one batch,
    while independent work goes on. Overlap waits, never proofs: independent suites of one
    capture run together, and the next wave's TEST authors start while a green run is in flight.
    Arm the run watchdog ONCE per process (the `CronCreate` the session-start context prints);
    `/close-session` archives on `CLOSE: YES` without asking.
