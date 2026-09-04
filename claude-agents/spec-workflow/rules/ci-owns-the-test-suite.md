# CI Owns the Test Suite — commit cheaply, push once, fix everything (ALL agents, always loaded)

Governs WHERE tests run, WHEN you may push, and WHAT you do with a red CI run. Companion
of `remote-ci-must-pass.md`, which governs the CI run itself.

Why (three MEASURED failures of the per-commit-suite arrangement; full accounts in the
`scripts/run_tests.py` header and `.claude/hooks/MIGRATION.md` §Incident record): a
60-minute suite made every commit an hour, so agents
batched whole features into single unreviewable commits; concurrent worktrees each
running `pytest -n auto` made the host unusable and killed the agent mid-run; fail-fast
CI reported one failure per run, so ten failures cost ten pipeline runs. None of it
bought correctness — a local and a CI suite run on the same SHA prove the same thing, and
only one is free.

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

`remote-ci-must-pass.md` governs the CI run itself (monitoring, debugging loop, capacity
ladder); `tests-must-not-fail.md` still bars every skip/xfail dodge unconditionally —
this rule only changes WHERE the run happens; frequent commits are not a licence to
commit generated files (`keep-git-clean.md`); waiting on CI is not a turn-end
(`continuous-work.md`); "every failing job" means full logs and quoted evidence
(`no-output-shortening.md`, `no-guessing.md`). The mechanisms are `scripts/run_tests.py`,
`scripts/run_checks.py` (the same command CI runs, so a local pipeline cannot drift from
the real one), and `scripts/ci_outage_mode.py`.
