---
description: End-of-session close-out — assess with evidence (working tree, leftover files, this run's worktree/branch/lock, shared local main, pending remote follow-ups), remediate THIS run's own artifacts as keep-git-clean requires, record a terminal Phase, and report whether the session is safe to close.
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, mcp__ccd_session_mgmt__archive_session
---

<!-- The archive tool is listed because step 9 offers to invoke it after an explicit go-ahead; a body that
     directs a tool the frontmatter allowlist excludes is a trap that fails at the last step of the command.
     It is an MCP tool and may be absent (a plain CLI session has no session-management server): in that case
     RECOMMEND archiving and let the user do it, rather than reporting a failure. -->


Answer the recurring end-of-session question: **"Can we close this here? Is git clean? Any
leftover files? Can we close the session?"** Assess with evidence, remediate what is yours to
remediate, then report.

**Running this command is not permission to stop.** If any work remains unfinished, close-out
is not what comes next — the work is. Per `.claude/rules/continuous-work.md`, an accurate
close-out report over unfinished work is a disguised check-in, and `issue-loop-gate.sh` will
refuse the turn-end anyway.

Read COMPLETE command output (no `tail`/`head`/`Select-Object` — see
`.claude/rules/no-output-shortening.md`). Every claim must be backed by quoted output
(`.claude/rules/no-guessing.md`). If work is genuinely incomplete, say so plainly rather than
declaring the session closeable.

## What this command may do, and what it must ask about first

The two halves are deliberately different, because the project's rules put them on opposite
sides of a line:

- **ASSESSMENT is read-only.** Never `git add`, commit, or push in this command. Reading is
  how the verdict is earned.
- **REMEDIATING THIS RUN'S OWN, REVERSIBLE ARTIFACTS IS MANDATORY, not a request.**
  `.claude/rules/keep-git-clean.md` states the clean end-state is **per run**: "each run
  leaves no worktree, branch, or lock of its own behind", and a per-issue worktree is
  EPHEMERAL once the work reaches a terminal state. So tearing down THIS run's worktree,
  branch and lock, removing THIS run's claim markers, cleaning the files THIS run put in
  `tmp/`, and appending this run's terminal `Phase` are the work — doing them needs no
  go-ahead (`continuous-work.md`: if a reversible path exists, take it and do not ask).
- **ANYTHING ELSE IS RECOMMEND-AND-WAIT.** Do not delete an untracked file whose fate is the
  user's call, do not touch another session's worktree/branch/lock, do not move the shared
  local `main`, and do NOT archive or close the session yourself. Classify, report, recommend,
  and wait for an explicit go-ahead.

## Run identity — read this before writing any state (NON-NEGOTIABLE)

`session-register.sh` (SessionStart) has ALREADY created this session's `runs/<run-id>/`
directory and seeded `resume_state.md` and `workflow_state.md` in it. **Your job is to
UPDATE those files. You do not choose where they live.**

- **Find the path:** read `.claude/agent-state/issue-work-orchestrator/registry.json`, find
  the entry whose KEY is THIS session's `session_id`, and use that entry's `state_dir` value
  VERBATIM (it is relative to `.claude/agent-state/issue-work-orchestrator/`). The
  `State file:` line in the `## Your recorded place in the work` block that
  `continuous-work-reinject.sh` prints at session start / resume / compaction is the same
  path character for character — use it if you have it.
- **NEVER invent a readable run-id label** such as `run-issue<N>-<timestamp>`. Every Stop
  gate resolves this session's state from the registry-derived path; state written anywhere
  else is read by NOTHING, which silently disables every gate for the entire session.
  MEASURED: exactly this deviation left both Stop hooks inert and cost four spurious
  turn-ends under a standing instruction never to stop without a proven reason.
- **State fields are plain `Name: value` lines**, and hooks read the **LAST** occurrence of
  each. **Correct a value by APPENDING a new block at the END of the file** — never edit an
  earlier line, never prepend. A bold `**Name:** value` spelling is read by NO hook, and a
  line inside a fenced code block is ignored. Prose you add for a human reader must contain no
  `Name: value` lines of its own. Use the seeded field NAMES exactly — `BRANCH`, `WORKTREE`,
  `PR`, not `CURRENT_BRANCH`/`CURRENT_WORKTREE`/`CURRENT_PR`.
- **Keep `SESSION_ID:` intact.** It is the rung by which a hook recovers this run if state
  ever lands under a differently-named directory.
- A proven Exception is recorded as an `AWAITING_USER` line naming the ACTUAL reason — the one
  sanctioned pause, checked for SUBSTANCE and not presence. An escalation you only described
  in chat is, to the gate, indistinguishable from abandoning the work, and the turn-end will
  be REFUSED.

## The checks (this run's own working area only)

Per `.claude/rules/keep-git-clean.md` the clean end-state is **per run**: assert cleanliness on
what THIS run created, never on the developer's shared checkout or a sibling run's artifacts.
Quote the command output for each check.

**Step 1: Working-tree cleanliness**
   - `git status --porcelain` — empty output = clean. Quote the result. Run it in this run's
     working area and in each worktree it still holds.
   - `git status --porcelain --untracked-files=all` — surface any untracked files the short
     form hides.
   - Classify every changed/untracked path per `.claude/rules/keep-git-clean.md` (COMMIT vs
     NEVER-COMMIT) before acting: source, config, docs and tests belong in version control;
     auto-generated, cache and temp files never do — a missing `.gitignore` entry is the fix
     for those. Never `git add -A` blindly. Flag anything that should be committed or ignored
     and recommend it; do not commit it from this command.

**Step 2: Leftover / temporary files**
   - List `tmp/` (`ls -la tmp/`). Per `.claude/rules/file-organization.md`, `tmp/` should be
     empty at end of task. **Remove the files THIS run created there** — deleting `tmp/` must
     never break the project. Residue this run did NOT create: report it and ask before
     deleting.
   - Note any obviously stray scratch files elsewhere in the tree that this session created
     and did not clean up.

**Step 3: This run's git artifacts (worktree / branch / lock)**
   - `git worktree list` and `git branch -vv`.
   - For each `.claude/worktrees/issue-<N>/` THIS run created: tear down its per-worktree venv
     FIRST if it provisioned one (locked file handles otherwise block removal on Windows),
     then `git worktree remove <path>` — plain, with `--force` only after confirming no
     uncommitted work would be lost — then `git branch -d/-D <branch>`. Verify with
     `git worktree list` and a directory check that nothing is left.
   - **Do NOT flag or remove sibling sessions' worktrees/branches/locks** — on this shared
     clone other live sessions legitimately own `.claude/worktrees/issue-*` directories and
     their branches. Only THIS run's own artifacts must be gone.
   - Check for this run's lock under
     `.claude/agent-state/issue-work-orchestrator/.locks/` if an orchestrator ran.

**Step 4: Claim markers — THIS RUN'S OWN CLAIM SET ONLY**
   - Derive the set mechanically from evidence this run wrote: its `.locks/issue-<N>.lock`
     owner records, its registry entry, and its `issue_queue.md`. **Never from topical
     adjacency** — an issue split out of yours, or one whose title resembles yours, is not
     yours to unclaim.
   - For each issue in that set, remove the claim per the convention recorded in
     `environment.md` (unassign, and/or remove the `in-progress`-style label through the
     ADDITIVE `remove-label` primitive with this run's `--run-id`, never a whole-set `labels`
     write), and **remove the marker BEFORE removing that issue's local lock**: the lock is
     the local ownership evidence the removal guard reads, so releasing it first would leave
     the legitimate close-out path unevidenced. Then `rmdir .locks/issue-<N>.lock` and update
     the registry entry (`current_issue` cleared, `status` set, heartbeat refreshed).

**Step 5: Issues updated and closed with evidence**
   - For each issue this run finished: a final comment linking the merged PR and the evidence,
     the checklist fully ticked (or a remaining item explicitly deferred WITH its reason,
     routed per `.claude/rules/issue-filing-discipline.md` rather than becoming an automatic
     follow-up issue), the time spent recorded in the host's field or in the closing comment,
     and the issue closed via the wrapper.
   - For an issue this run did NOT finish: leave it OPEN with a status comment carrying the
     branch, worktree, PR and evidence location, so any agent can resume from the issue alone
     — and do not remove its claim if the work is still in flight elsewhere.

**Step 6: Shared local `main` (do NOT "fix" an expected state)**
   - `git rev-parse main` and `git rev-parse origin/main`.
   - Local `main` being `[origin/main: behind N]` is the DESIGNED state on this shared clone
     (`.claude/rules/keep-git-clean.md`): the shared local `main` is deliberately never
     fast-forwarded because sibling sessions and the developer depend on it. Report it as
     expected, not as drift, and do not move it.

**Step 7: Outstanding remote/CI follow-ups (report, do not block on)**
   - If this session merged a PR under the CI-capacity exception
     (`.claude/rules/remote-ci-must-pass.md`), remind that re-verifying the trunk CI run once
     capacity returns is still pending. This lives on the repo/PR, not the working tree, and
     does not block closing the local session.

**Step 8: A terminal `Phase` recorded**
   - APPEND a block at the END of this run's `resume_state.md` carrying `Status: COMPLETED`
     and a terminal `Phase` (`DONE`/`COMPLETED`/`ABANDONED`/`ESCALATED`) — **that terminal
     value is what releases `issue-loop-gate.sh`**, and it must be the WHOLE value of the
     field (`Phase: DONE`, never `Phase: DONE (was IMPLEMENT)`).
     `WORKABLE_ISSUES_REMAIN` does not release the gate and never did, so recording `no` there
     is for consistency only.
   - Do NOT record a terminal `Phase` to end a turn on work that is not finished: that is the
     failure this gate exists to catch, and the state file is the record someone will trust
     later.

## Step 9: Verdict (the only exit point)

State clearly **YES/NO — safe to close**, with one line of quoted evidence for each: working
tree clean, `tmp/` empty, this run's worktree/branch/lock torn down, this run's claim markers
removed and its issues resolved, local `main` untouched (expected-behind), a terminal `Phase`
recorded, and any pending remote follow-up.

Also report: anything left deliberately in place and why, and every issue this run claimed with
its final claim state.

If a check FAILED on something that is yours to fix, **fix it now and re-check** — an
unresolved failure is work remaining, so close-out has not been reached and this is not a
turn-end. If everything checks out, ask whether to archive the session now — and only archive
after an explicit go-ahead, via `archive_session` with `session_id: "self"` if that tool is
available to you. It is an MCP tool and may not be (a plain CLI session has no
session-management server): then simply RECOMMEND archiving and leave it to the user, rather
than reporting a tool failure as a close-out failure. If
anything is unclean or unfinished for a reason outside this run's control, list exactly what
remains and recommend against closing until it is resolved.

No AI attribution in any comment, commit or issue text
(`.claude/rules/no-ai-attribution.md`). Never touch `.kiro/`.
