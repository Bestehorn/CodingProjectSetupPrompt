# Keep Git Clean and Up-to-Date (ALL agents, always loaded)

The local git repository must never be left messy or stale. At every phase boundary, and
ALWAYS when an issue/PR/task reaches a terminal state: working tree clean
(`git status --porcelain` empty except deliberately in-progress files), no stale branches
or worktrees left behind.

## What to commit vs. what never to commit

- **COMMIT** (belongs in version control): source, tests, configuration
  (`pyproject.toml`, `.pre-commit-config.yaml`, CI config), documentation, IaC/CDK code,
  scripts, the tracked git hooks (`.githooks/`), the secret-scan baseline
  (`.secrets.baseline` — the audited allow-list; without it the pre-commit hook fails on
  every clone), spec artifacts kept under version control, `.gitignore`/`.gitattributes`
  updates.
- **NEVER COMMIT** (generated, transient, machine-local): build artifacts (`build/`,
  `dist/`, `*.egg-info/`, `*.pyc`, `__pycache__/`, `*.so`), caches (`.pytest_cache/`,
  `.mypy_cache/`, `.ruff_cache/`, `.hypothesis/`), coverage output, check/test reports
  (`reports/`), virtual environments (`venv/`, `.venv/`), editor/OS cruft, secrets,
  anything under `tmp/`, generated version files (`src/_version.py`), per-run agent state
  (`.claude/agent-state/`, `.claude/worktrees/`).

Principle: **generated and temporary files are never committed; everything else that is
part of the project IS.** If a never-commit file is not yet ignored, ADD a `.gitignore`
entry rather than leaving it untracked. Before any commit: review every changed/untracked
path, classify it, stage only the COMMIT set — never `git add -A` blindly. Committing
often (`ci-owns-the-test-suite.md`) is not a licence to skip this classification.

## Worktrees and branches

- Per-issue/per-task worktrees and branches are EPHEMERAL: at a terminal state (merged,
  abandoned, escalated), `git worktree remove <path>`, `git branch -d/-D`, and verify
  with `git worktree list` plus a directory check. The clean end-state is **per run** —
  each run leaves no worktree, branch, or lock of its own behind; assert cleanliness on
  the run's OWN working area.
- **Do NOT move the shared local `main` branch.** When multiple runs may share one clone,
  a run never checks out or fast-forwards local `main` — the developer and sibling runs
  depend on it. Fetch and base worktrees on `origin/<main>`; verify merges with
  `git merge-base --is-ancestor <sha> origin/<main>`. (A solo workflow may sync local
  `main`, but branch-off-origin is always safe and is the default.)
- Never leave a detached HEAD, a half-finished rebase/merge, or an orphaned worktree. If
  a git operation is interrupted, restore a clean known state before anything else.

## Concurrency-safe maintenance

The one real corruption hazard with several worktrees on one object store is concurrent
auto-gc/maintenance, which `git fetch` can trigger. Set once per clone (idempotent):

```
git config gc.auto 0
git config maintenance.auto false
git config gc.autoDetach false
```

Pass `--no-auto-gc` on every fetch (`git fetch origin --prune --no-auto-gc`). NEVER
`--prune=now` or manual `git gc` while any worktree operation may be in flight. (On git
≥ 2.51, `--no-auto-maintenance` is NOT a valid fetch flag — use `--no-auto-gc` plus the
config.) A single quiescent `git gc` only between backlog passes with no run active.

## Stay up-to-date

Integrate remote changes regularly (fetch + fast-forward/rebase) so local work never
drifts far from the remote. Any conflict is resolved per the line-by-line merge
discipline — delegate to `code-merge-reviewer` where installed; never blind
"take theirs/ours".

Self-check before ending any phase or closing any issue/PR/task: tree clean, nothing
generated staged, no stale worktrees/branches, checkout synced. A messy git state is a
defect — fix it before proceeding.
