# Phase Fragment: IMPLEMENT_LOOP + VERIFY + EVIDENCE_REPORT

Followed by `spec-conductor` (and the `/spec-implement` command). Turns an approved
spec into evidence-proven code, test-first. Installed at
`.claude/specs/_workflow/phases/spec-phase-implement.md`.

The non-negotiable rule of this phase: **the implementer never certifies its own
work.** `spec-implementer` writes tests and code; the CONDUCTOR runs the tests and
captures evidence; the `adversarial-verifier` independently grades it. No claim of
"works/passes" exists without captured command output under `evidence/`.

## Preconditions

- Requirements/design/tasks reviews have passed the readiness gate (0 A+B + coverage).
  (`/spec-implement` first checks `review/review-latest.md` shows 0 A+B and
  test-architect `TEST-READY`; if not, it runs the review loop or refuses with the
  open findings.)
- The venv exists and is active (create it per use-venv if missing). The test command is
  `python scripts/run_tests.py` — bounded local workers, no fail-fast. Record it. Never
  `pytest -n auto`: one worker per vCPU across several per-issue worktrees is what makes
  the host unusable and kills the session (`ci-owns-the-test-suite.md`).
- Spec-drift guard: during this phase the `spec-implementer` MUST NOT edit
  `requirements.md`/`design.md`/`tasks.md`. Enforce with the TDD-gate hook and/or
  `permissions.deny` on those paths.

## IMPLEMENT_LOOP — per task, in tasks.md order

For each unchecked task:

### TEST task
1. Invoke `spec-implementer` to write the test(s) ONLY for the named Property /
   acceptance criterion. It must make the symbols importable (minimal stub signature
   in `src/` if needed) but MUST NOT implement the behavior.
2. **Conductor runs the tests** via Bash, capturing COMPLETE output (no tail/head) to
   `evidence/red/<task>.txt`.
3. **Assert RED-FOR-THE-RIGHT-REASON** (run the pre-filter
   `.claude/hooks/red-for-right-reason.sh evidence/red/<task>.txt`, or check
   inline): the failure must be an `AssertionError` / Hypothesis "Falsifying example",
   and must NOT be dominated by `ImportError`/`ModuleNotFoundError`/`CollectionError`/
   `SyntaxError`/`fixture '...' not found`. If green, or red for the wrong reason,
   reject and re-invoke `spec-implementer` to fix the test. Append a `DL-NNN` entry.

### IMPL task
1. Invoke `spec-implementer` to write the MINIMAL code to pass the paired tests,
   without touching unrelated tests and without suppressions.
2. **Conductor runs the paired tests** → `evidence/green/<task>.txt` (must be green):
   `python scripts/run_tests.py <the paired test paths>`.
3. **Commit** the task. The pre-commit hook is lint + security, about a second — commit
   at every task boundary rather than accumulating one enormous change
   (`ci-owns-the-test-suite.md`).
4. Only when the paired capture is green: mark the task `[x]` in `tasks.md` and append a
   `DL-NNN` entry citing the design section implemented.
5. If green cannot be reached after the implementer's attempts, leave the task
   unchecked; loop with more evidence or escalate (one batched message).

**No per-task full-suite run.** That used to be step 3 here, and on a project whose
suite takes an hour it made each task cost an hour — so the whole spec got implemented
in one commit and the history stopped being reviewable. The regression verdict comes
from ONE CI run over the finished batch (see below), which is both free and
authoritative. If a change plainly reaches beyond its paired tests, run the affected
module or package locally — still not the whole suite.

When all tasks are `[x]`, transition to VERIFY.

### Batch boundary — push ONCE, and let CI regress the whole change

After the last task is `[x]` and committed:

1. Push the branch ONCE. Never push per task, and never push to find out whether the
   work is good.
2. Monitor the CI run to a terminal state via the wrapper script. It runs the full suite
   with no fail-fast, so its result is the regression evidence for the batch: capture it
   to `evidence/regress/<last-task>.txt` with the run id and head SHA quoted.
3. If it is red, apply the debugging loop in `remote-ci-must-pass.md`: enumerate EVERY
   failing job and every failure inside it before changing anything, group by root
   cause, fix them ALL, then push once. One run in, all fixes out.
4. While CI-OUTAGE MODE is declared there is no run to read — the `pre-push` hook runs
   the suite locally with bounded workers instead, and that output is the regress
   capture.

## VERIFY — adversarial

1. Invoke `adversarial-verifier`. It obtains an INDEPENDENT whole-suite result for the
   pushed SHA — normally by reading the CI run rather than re-running locally, which is
   the same execution on the same SHA by machinery it does not control — and tries to
   REFUTE every "works" claim: kill-the-mutant (revert/stub the impl → the paired
   test must then fail; this stays LOCAL and paired-only, and is cheap), vacuity/dodge
   scan (skipped/xfail/assert-nothing), property stress (more Hypothesis examples),
   coverage of the changed code, and a red-for-right-reason audit of `evidence/red/*`.
   It writes `evidence/verify/refutation-report.md` + captures, and restores the tree.
2. Re-invoke the full reviewer panel against the IMPLEMENTED diff (design drift
   surfaces as fresh A/B on the code).
3. If the verifier `REFUTED` any claim, or any reviewer raises A/B on the code:
   uncheck the affected tasks and return to IMPLEMENT_LOOP. Else → EVIDENCE_REPORT.

## EVIDENCE_REPORT

Assemble `evidence/REPORT.md`:
- For each requirement → its Correctness Properties → the test(s) proving them → the
  quoted red→green command output → the verifier's failed refutation attempts.
- Final full-suite result and coverage of the change, quoted from captures — normally the
  CI run for the merged SHA (quote the run id and the SHA), or the `pre-push` hook's local
  run while CI-OUTAGE MODE is declared.
- The number of CI runs the implementation took and what each surfaced. One run for a
  clean batch is the target; several runs each fixing one failure is a defect in how the
  work was done (`ci-owns-the-test-suite.md`).
- The `git diff --stat` of the implementation.
Set `workflow_state.md` to `Status: COMPLETED`. The final user-facing message quotes
the report's summary table — every "passes" is a quoted command, never an assertion.

## Push gating (commits are not gated)

The TDD-gate hook gates the PUSH, not the commit. It blocks `git push` when a task
marked `[x]` has no capture, when the newest paired-test capture is red or contains
skip/xfail dodges, or when CI-OUTAGE MODE is declared with no green full-suite capture.
It also bans `--no-verify` on both commit and push.

A commit itself needs no evidence — that is the point. The evidence requirement used to
sit on `git commit`, which is what made a task cost a full suite run
(`ci-owns-the-test-suite.md`). Commit freely; owe evidence at the push, where CI and
other people start depending on the work. `remote-ci-must-pass.md` governs the run that
follows.

## Defects discovered during implementation

Per `issue-filing-discipline.md`: a defect that blocks the task is absorbed into it; a
small, clear one (a few lines, no design choice) is FIXED NOW and noted in the commit
message; one that needs extensive research, an evaluation of design options, or work
outside this spec's scope goes to the issue-intake agent as ONE gated issue
(`Origin: spawned-discovery`, `Spawned-from: #<N>` when a tracker issue drove this spec);
anything else is a row in `docs/findings-ledger.md`. Completing a spec with zero new
issues filed is the expected outcome, not a sign something was missed.
