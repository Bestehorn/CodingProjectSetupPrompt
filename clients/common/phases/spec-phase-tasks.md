# Phase Fragment: TASKS (waves, test-first, file ownership)

Followed by `spec-conductor`, the orchestrator's FIX phase, and the `/spec-tasks` command.
Installed at `.claude/specs/_workflow/phases/spec-phase-tasks.md`. Tier S carries its
tasks inside `change.md` and skips this phase.

## Procedure

Invoke `spec-author` with `requirements.md`/`bugfix.md` + `design.md` and the tier's cap
(`tasks.md` ≤ 15,000 bytes M / ≤ 30,000 bytes L). It writes `tasks.md` in this shape:

```
## Wave 1 — <name>
- [ ] 1.1 TEST: <what the tests assert> — Files: test/... — Validates: AC-1.1, UB-1
- [ ] 1.2 TEST: ... — Files: test/... — Validates: AC-1.2
- [ ] 1.3 IMPL: <what is built> — Files: src/... — Validates: AC-1.1, AC-1.2
## Wave 2 — <name>
- [ ] 2.1 TEST: ... — Files: ... — Validates: ...
- [ ] 2.2 IMPL: ... — Files: ... — Validates: ...
## Final
- [ ] F.1 E2E: <the end-to-end script and the CI job that runs it> — Files: test/e2e/...
```

Rules the author follows and the tasks review checks:

- **Waves.** Tasks inside a wave own DISJOINT files and depend only on earlier waves, so
  the conductor can dispatch a whole wave concurrently (`parallel-by-default.md`). Fewer,
  larger waves beat many small ones; three to five waves is typical for M.
- **Test-first inside each wave.** Every TEST task precedes the IMPL task it pairs with;
  the conductor runs a wave's TEST tasks first (red), then its IMPL tasks (green).
- **Traceability.** Every task names its `Files:` and its `Validates:` criteria. Every
  acceptance criterion and every unchanged-behaviour clause appears in at least one TEST
  task's `Validates:`. A task that validates nothing is deleted.
- **Size.** A task is one implementer call: one to three files, one behaviour. Twenty to
  thirty tasks is the practical ceiling for M; beyond it, the ask is L or should be split.
- **The final wave** is the automated end-to-end check (`always-test-e2e.md`) — the script
  and the CI job that runs it post-deploy — or `Not applicable` for a change that alters
  no runtime behaviour.

After it returns, the conductor measures the cap and transitions to TASKS_REVIEW_LOOP
(`spec-phase-review.md`, light panel: `spec-review-agent` + `test-architect`).

## Regeneration / sync

When requirements or design change during a review loop, regenerate: keep `[x]` on tasks
whose meaning is unchanged, add tasks only for criteria that exist in the frozen
requirements, remove tasks whose criterion was removed (one `DL-NNN` if a completed task
is dropped). Never let `tasks.md` grow past its cap through regeneration.

## `/spec-tasks` standalone

Generate or regenerate `tasks.md`, run ONE light review pass, print the combined A+B and
the coverage table, stop.
