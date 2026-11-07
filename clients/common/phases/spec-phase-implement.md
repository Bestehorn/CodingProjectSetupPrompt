# Phase Fragment: IMPLEMENT (waves) + VERIFY + EVIDENCE_REPORT

Followed by `spec-conductor`, the orchestrator's FIX phase, and `/spec-implement`.
Installed at `.claude/specs/_workflow/phases/spec-phase-implement.md`.

The non-negotiable rule of this phase: **the implementer never certifies its own work.**
`spec-implementer` writes tests and code; the CONDUCTOR runs the tests and captures the
evidence; `adversarial-verifier` grades it. No "passes" without captured output.

## Preconditions

- The spec passed its readiness gate (`spec-phase-review.md`); for tier S, `change.md`
  passed its combined review.
- The venv exists (per-worktree where the project requires it). The test command is
  `python scripts/run_tests.py <paths>` — bounded workers, no fail-fast, never
  `pytest -n auto` (`ci-owns-the-test-suite.md`).
- `spec-implementer` may not edit the spec artefacts (spec drift). If an implementer
  reports the spec is wrong, the conductor decides: a restatement is applied by the
  author; a scope change is a residual or a re-tier.

## IMPLEMENT — one wave at a time, everything inside a wave in parallel

For each wave in `tasks.md` order (tier S: the single wave in `change.md`):

1. **RED — all TEST tasks of the wave, ONE dispatch.** One `spec-implementer` per TEST
   task (or one for the whole wave when its tests touch one or two files), all in the same
   message, each told its task, its `Files:`, its `Validates:` criteria and the absolute
   worktree path. When they return, the conductor runs the wave's tests ONCE:
   `python scripts/run_tests.py <the wave's test files>` → `evidence/red/wave-N.txt`,
   first line `# tasks: <every TEST task id of the wave>`.
   Assert **red for the right reason** (`python .claude/hooks/red_for_right_reason.py` on the
   capture): assertion failures or Hypothesis falsifications, not import, collection,
   syntax or fixture errors. Wrong-red or green → re-dispatch only the offending tasks.
2. **GREEN — all IMPL tasks of the wave, ONE dispatch.** One `spec-implementer` per IMPL
   task, same message, each told its paired tests and `Files:`. When they return, run the
   wave's tests ONCE → `evidence/green/wave-N.txt`, first line `# tasks: <every task id of
   the wave, TEST and IMPL>`. Must be green with no skip or xfail. Not green → re-dispatch
   the failing tasks with the failure output; loop; escalate only after three attempts.
3. **Commit the wave** (one commit; the pre-commit hook is lint + security). Mark every
   task of the wave `[x]`. No `DL-NNN` for the wave.
4. If a wave's change plainly reaches beyond its own tests, run the affected module or
   package locally — still never the whole suite.

**Overlap the waits, never the proofs.** While wave N's green run is in flight (a background task
through `scripts/run_tests.py`, naming the wave's test files), dispatch wave N+1's TEST authors in
the same message. Wave N+1's red capture runs only after wave N's green capture passed and wave N
is committed — `git add` names wave N's files, never the next wave's — so every capture still
proves exactly its own wave. Independent suites of ONE capture (a Python suite and a UI suite) run
concurrently, each in its own host-wide slot, collected with `python .claude/hooks/wait_for.py`.
Nothing is skipped, merged or reordered to save time; only the waiting stops being serial.

The Stop and push gates accept a wave capture for every task id its `# tasks:` line
declares; a task marked `[x]` with no capture that declares it is refused.

## Batch boundary — push ONCE, wait in the foreground, bounded

After the last wave is committed:

1. Push the branch ONCE (`ci-owns-the-test-suite.md`).
2. Do the unblocked work first — the evidence report skeleton, the issue note, the docs —
   then wait for the run in the FOREGROUND with the wrapper's blocking wait (`pipeline wait
   <id> --timeout-seconds 540` / `wait-run <id> --timeout-seconds 540`), re-issued while
   it exits 11. Never `sleep`-poll, and never end the turn to be notified
   (`parallel-by-default.md`).
3. The run's verdict is the regression evidence: capture it to
   `evidence/regress/ci-<run id>-<sha>.txt`. Red → enumerate EVERY failing job and failure
   before changing anything, group by root cause, fix them all, push once, wait again. Green →
   VERIFY; the PR is enqueued only after VERIFY and the EVIDENCE_REPORT (`.claude/docs/delivery.md`).
4. During a declared CI outage the `pre-push` hook's local run is the capture instead.

## The end-to-end check runs in CI

Where the project deploys, the E2E script committed in the final wave runs in the
pipeline's post-deploy stage after the merge; its verdict on the merged SHA is the E2E
evidence, captured from the wrapper — or, where `config/delivery.json` names the verdict
watcher, judged by the deploy's last job on the first deployed commit that CONTAINS the
landing, which ticks the issue's `(post-deploy)` items and closes it. The agent never deploys a branch to a shared
environment, never takes a deploy lock or asks for a merge freeze, and never asks the
operator to sign in, copy a response or observe a screen. A red post-merge E2E is a
defect fixed in an immediate follow-up commit on a fresh worktree (or a revert if the
fix is not immediate). For a local-only project the E2E is `run_checks.py --group e2e`.

## VERIFY — adversarial, bounded

Invoke `adversarial-verifier` with the spec directory and the CI run id. It reads the CI
verdict (never re-runs the suite when a run exists), kills the mutant for each wave
(revert or stub the wave's implementation, run the wave's paired tests locally — they must
fail — restore), scans for skip/xfail/vacuous assertions, and audits `evidence/red/*` for
right-reason. It writes `evidence/verify/refutation-report.md` (≤ 8,000 bytes) and returns
`VERIFIED` or `REFUTED <ids>`. Refuted → reopen only the affected tasks. Then ONE
delta-mode pass of the review panel over the implemented diff (M/L) or of the combined
reviewer (S): A/B on the code → reopen the tasks; else → EVIDENCE_REPORT. No further
review rounds are opened in VERIFY.

## EVIDENCE_REPORT

`evidence/REPORT.md` (≤ 8,000 bytes): a table criterion → test → capture file → verdict;
the CI run id and SHA; the verifier's verdict; the number of CI runs the batch took (one is
the target); `git diff --stat`. Set `workflow_state.md` to `Status: COMPLETED`. The final
message to the operator is the table and the PR link, nothing more.

## Push gating (commits are not gated)

The `spec-tdd-gate` gate blocks `git push` when a `[x]` task has no capture that declares it,
when the newest green capture is red or contains skip/xfail, or when a CI outage is
declared with no green full-suite capture. It bans `--no-verify` on commit and push.
Commits themselves need no evidence.

## Defects discovered while implementing

`issue-filing-discipline.md`: blocking → absorbed; small and clear → fixed now, noted in
the commit; needing research, design options or out-of-scope work → ONE gated issue via
intake; anything else → a ledger row. Zero new issues is the expected outcome.
