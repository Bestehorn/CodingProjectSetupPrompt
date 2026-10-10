Valid-until: 2026-11-15
## FRAMEWORK REVISION 2026-09-30 IS IN FORCE (amended 2026-10-03, item 8; 2026-10-10, item 9) — it supersedes the phase text in your agent definition and command body

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
   as a background task. Never ask the operator to sign in, copy or observe anything: a human
   step is a residual, and the end-to-end check runs in the pipeline after the merge.
7. Issue notes only at phase transitions; DL entries only for decisions; a question is five
   lines with the recommended option first; reversible decisions are decided, not asked.
8. (2026-10-03) A shell call is the expensive tool: read, search and write files with Read,
   Grep, Glob, Write and Edit — never `cat`, `grep`, `ls`, `sed` or a heredoc — and chain a
   shell step into ONE call. The `no-foreground-sleep` gate refuses a foreground wait of 10 s
   or more and any sleep in a loop: run the wait with `run_in_background: true`, or the
   wrapper's `wait`. Local suites go through `scripts/run_tests.py`, which holds a host-wide
   suite slot; a synth, `npm test` or a harness runs under
   `python scripts/suite_semaphore.py run -- <command>` (`.claude/rules/native-tools-over-shell.md`).
9. (2026-10-10) At close-out, run `python scripts/reap_agent_temp.py --scoped-temp tmp/os-temp
   --apply` with `run_in_background: true` and run it AGAIN while it exits 3 (its budget ran
   out; the rest is quarantined) — never a foreground call without `--budget-minutes 9`. An
   oversize ledger row is compacted by `python scripts/memory_compile.py reconcile --apply`,
   not rewritten by hand. After adding a gate on another tool, re-run
   `python .claude/hooks/hooks.py registration`: the matcher is derived from the gates present.
