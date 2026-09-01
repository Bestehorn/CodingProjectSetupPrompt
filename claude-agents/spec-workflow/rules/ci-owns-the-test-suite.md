# CI Owns the Test Suite — commit cheaply, push once, fix everything (ALL agents, always loaded)

This rule is shared by EVERY agent and the main session. It is installed at
`.claude/rules/ci-owns-the-test-suite.md` (no `paths:` frontmatter → always loaded) and is
pointed to from the project's root `CLAUDE.md`. It governs WHERE tests run, WHEN you are
allowed to push, and WHAT you must do with a red CI run. It is the companion of
`remote-ci-must-pass.md`, which governs the CI run itself.

## Why this rule exists

Three measured failures of the previous arrangement, in which the full suite was a
precondition for every commit:

1. **Commits cost an hour.** On a project whose suite runs for 60 minutes, a per-commit
   suite made each commit a 60-minute operation. Agents responded rationally: they stopped
   committing, batched an entire feature into one enormous commit, and the history became
   unreviewable — the exact opposite of what a commit gate is for.
2. **The machine died.** `pytest -n auto` takes one worker per vCPU. Several concurrent
   per-issue worktrees each doing that made the host unusable and got the agent process
   killed mid-run, losing the work.
3. **Fail-fast turned one run into many.** A CI pipeline that stops at the first failing
   stage reports ONE problem per run. The worker fixed it, pushed, waited, found the next,
   and burned a full cycle per failure. Ten failures meant ten pipeline runs.

None of that bought any correctness. A local suite run and a CI suite run on the same SHA
prove the same thing, and only one of them is free.

## Where things run

| Boundary | What runs | Cost |
|---|---|---|
| `pre-commit` hook | ruff lint, ruff-format, bandit (staged files), secret scan | < 2 s |
| `pre-push` hook | mypy | seconds |
| `pre-push` hook, **CI-OUTAGE MODE declared** | mypy + full suite, bounded workers | the exception |
| CI | every check + the full suite, **no fail-fast**, all failures reported together | authoritative |
| you, locally, while working | the AFFECTED tests — `python scripts/run_tests.py <paths or -k expr>` | your call |

**The full test suite is never a precondition for a commit.** Not by a hook, not by a gate,
not by your own discipline. If you find yourself about to run the whole suite so that you
are allowed to commit, that is this rule being violated.

## Commit often; push once

- A commit costs about a second. Commit at every natural boundary — a task finished, a test
  written, a refactor separated from a behaviour change. A readable series of small commits
  is the deliverable, not an accident.
- **The push is the batching boundary.** Push when the batch of work is complete and
  self-consistent, not when you want to know whether it works. Never push "to see if CI
  passes" — that is the trial-and-error loop this rule exists to end.
- Before a push you owe: the paired tests for what you built, green, captured. You do NOT
  owe a local full-suite run. CI runs the suite on the pushed SHA and that run is the
  authoritative verdict.
- `--no-verify` is forbidden on both commit and push. At commit the hook is a second of
  lint and secret scanning, so there is nothing to save; at push it is the only local gate
  there is. The TDD gate hook blocks both.

## Local test execution is bounded

When you do run tests locally, go through `python scripts/run_tests.py`. It derives a
BOUNDED worker count — `min(4, cores // 4)`, floor 1 — and refuses `-x` / `--maxfail`.

- **Never `pytest -n auto` locally.** That is a CI-runner setting. `run_tests.py --workers
  auto` exists for CI and nothing else.
- **Never run suites in two worktrees at the same time.** The bound is per process; four
  concurrent worktrees at four workers each is sixteen pytest processes, which is how the
  host became unusable.
- If a suite is flaky under parallelism, `--workers 1` is the honest answer while the shared
  state gets fixed — not a retry loop, and never an `xfail` (`tests-must-not-fail.md`).

## One CI run per fix batch (the discipline that matters most)

CI runs every check and reports every failure in a single run — that is what
`scripts/run_checks.py` is for, and why no CI job may be a multi-command step list. Your
side of that bargain: **use the whole report.**

When a CI run comes back red:

1. **Enumerate completely first.** Retrieve the logs of EVERY non-successful job through
   the wrapper script, and within each, every failing test and every failing check. Read
   complete output (`no-output-shortening.md`). Do not start fixing while you are still
   reading.
2. **Group by root cause.** Ten failures are usually two or three causes. Write the grouping
   down: `N failures across M jobs → K root causes`.
3. **Fix every group.** All of them, in this working session, before you push again.
4. **Push once.** Then monitor that run to a terminal state.

**Fixing one failure and re-pushing to find the next is a rule violation, not a work
style.** So is "I'll fix the obvious one and see what's left." If a failure genuinely
cannot be diagnosed from the logs you have, say so explicitly with the evidence, fix
everything else, and treat the extra run as a cost you are consciously choosing.

Record each CI run you cause in your run state with its purpose and what it surfaced (run
id, why you pushed, failures found, root-cause groups). The count is the metric: a fix that
took four runs when it could have taken two is a defect in how the work was done, and
without the record nobody can see it.

## When CI cannot run at all

That is `remote-ci-must-pass.md`'s capacity ladder, not this rule's business — with one
mechanical consequence that lives here: while the outage lasts, the suite runs at PUSH
time, never at commit time.

```bash
python scripts/ci_outage_mode.py declare --evidence-run <id> --issue <n> --rung <2|3>
python scripts/ci_outage_mode.py clear      # the moment a real CI run goes green
```

`declare` writes a marker into the SHARED git dir, so one declaration covers every
concurrent worktree in the clone, and the `pre-push` hook picks it up with no further
configuration. Clearing it is not housekeeping: while it is set, every push in every
worktree pays for a full local suite.

## Self-check

Before pushing, confirm: paired tests green and captured; the batch is complete rather than
a probe; no `--no-verify` anywhere; no local full-suite run was performed to satisfy a gate.
After a red CI run, confirm: every failing job read, every failure enumerated, root causes
grouped and written down, all of them fixed, exactly one push.

## Integration

- `remote-ci-must-pass.md`: the CI run itself — monitoring it, the debugging loop, and the
  capacity ladder when it cannot run. This rule says what you do with its output.
- `tests-must-not-fail.md`: a failing test is always fixed, never skipped or xfailed. That
  is unchanged and unconditional; this rule only changes WHERE the run happens.
- `post-activity.md`: the completion checklist runs the affected tests locally and takes the
  suite verdict from CI.
- `keep-git-clean.md`: commit only what belongs — a frequent-commit habit is not a licence
  to commit generated files or `reports/`.
- `continuous-work.md`: waiting for a CI run is not a reason to end a turn. Monitor it, and
  work on anything that does not depend on its result meanwhile.
- `no-output-shortening.md` / `no-guessing.md`: "every failing job" means every log read in
  full, and every claim about a failure backed by quoted output.
- `scripts/run_tests.py`, `scripts/run_checks.py`, `scripts/ci_outage_mode.py`: the
  mechanisms. `run_checks.py` is the same command CI runs, which is what keeps a local
  pipeline execution from drifting away from the real pipeline.
