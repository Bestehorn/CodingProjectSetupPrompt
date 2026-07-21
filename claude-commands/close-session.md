---
description: End-of-session close-out check — verify the git working tree is clean, no leftover/temp files remain, no stale artifacts from THIS run are left behind, and report whether the session is safe to close.
allowed-tools: Bash, Read, Grep, Glob
---
Answer the recurring end-of-session question: **"Can we close this here? Is git clean?
Any leftover files? Can we close the session?"** Assess with evidence, then report — do
NOT archive/close the session yourself; recommend and wait for the user's go-ahead.

Read COMPLETE command output (no `tail`/`head`/`Select-Object` — see
`.claude/rules/no-output-shortening.md`). Every claim must be backed by quoted output
(`.claude/rules/no-guessing.md`). Do NOT `git add`, commit, push, or delete anything in
this command — it is read-only assessment. If work is genuinely incomplete, say so
plainly rather than declaring the session closeable.

**Step 1: Working-tree cleanliness**
   - `git status --porcelain` — empty output = clean. Quote the result.
   - `git status --porcelain --untracked-files=all` — surface any untracked files the
     short form hides. If untracked files exist, classify each per
     `.claude/rules/keep-git-clean.md` (COMMIT vs NEVER-COMMIT) and flag anything that
     should be committed or `.gitignore`d, without modifying anything.

**Step 2: Leftover / temporary files**
   - List `tmp/` (`ls -la tmp/`). Per `.claude/rules/file-organization.md`, `tmp/`
     should be empty at end of task; report any residue (do not delete without asking).
   - Note any obviously stray scratch files elsewhere in the tree that this session
     created and did not clean up.

**Step 3: This run's git artifacts (worktree / branch / lock)**
   - `git worktree list` and `git branch -vv`.
   - Identify worktrees/branches/locks created by THIS session's work and confirm they
     were cleaned up after merge (`.claude/rules/keep-git-clean.md`).
   - **Do NOT flag sibling sessions' worktrees/branches/locks as leftovers** — on this
     shared clone other live sessions legitimately own `.claude/worktrees/issue-*`
     directories and their branches. Only THIS run's own artifacts must be gone. Never
     remove another session's worktree.
   - Check for this run's lock under
     `.claude/agent-state/issue-work-orchestrator/.locks/` if an orchestrator ran.

**Step 4: Shared local `main` (do NOT "fix" an expected state)**
   - `git rev-parse main` and `git rev-parse origin/main`.
   - Local `main` being `[origin/main: behind N]` is the DESIGNED state on this shared
     clone (`.claude/rules/keep-git-clean.md`): the shared local `main` is deliberately
     never fast-forwarded because sibling sessions depend on it. Report it as expected,
     not as drift, and do not move it.

**Step 5: Outstanding remote/CI follow-ups (report, do not block on)**
   - If this session merged a PR under the Actions-quota exception
     (`.claude/rules/remote-ci-must-pass.md`), remind that **Step D** (re-verify the
     trunk CI run once GitHub Actions minutes return) is still pending. This lives on the
     repo/PR, not the working tree, and does not block closing the local session.

**Step 6: Verdict** (the only exit point)
   - State clearly: **YES/NO — safe to close**, with the one-line evidence for each:
     working tree clean, `tmp/` empty, this run's worktree/branch/lock cleaned up,
     local `main` untouched (expected-behind), and any pending remote follow-up.
   - If everything checks out, ask whether to archive the session now (via
     `archive_session` with `session_id: "self"`) — and only archive after an explicit
     go-ahead. If anything is unclean or unfinished, list exactly what remains and
     recommend against closing until it is resolved.
