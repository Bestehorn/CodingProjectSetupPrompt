---
description: End-of-session close-out — confirm the assigned work is actually complete, wait out any running CI, clean up this session's own files, temp residue, worktree/branch/lock and claim markers, record a terminal Phase, then give a one-glance safe-to-close verdict.
argument-hint: "[nothing]"
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch, mcp__ccd_session_mgmt__archive_session, Agent(spec-author, spec-researcher, spec-review-agent, test-architect, standards-reviewer, best-practice-reviewer, security-reviewer, devops-iac-reviewer, adversarial-verifier, spec-implementer, code-merge-reviewer)
---

<!-- The archive tool is listed because the final step offers to invoke it after an explicit go-ahead; a body
     that directs a tool the frontmatter allowlist excludes is a trap that fails at the last step of the
     command. It is an MCP tool and may be absent (a plain CLI session has no session-management server): in
     that case RECOMMEND archiving and let the user do it, rather than reporting a failure. -->

Answer **"can we close this session?"** — by finishing anything unfinished, not by describing
it. Steps 1–2 and the remediation in steps 4–6 and 8 may CHANGE things (that is the point);
everything else is read-only assessment. The line between the two is the project's own:
remediating THIS run's own, reversible artifacts is MANDATORY, not a request
(`keep-git-clean.md` makes the clean end-state per run; `continuous-work.md` Exception 1 says
take a reversible path rather than ask for one) — ANYTHING ELSE is recommend-and-wait: never
another run's artifacts, never the shared local `main`, never an untracked file whose fate is
the user's call.

**Running this command is not permission to stop.** If any work remains unfinished, close-out
is not what comes next — the work is. Per `.claude/rules/continuous-work.md`, an accurate
close-out report over unfinished work is a disguised check-in, and `issue-loop-gate.sh` will
refuse the turn-end anyway.

**Scope: THIS session only.** Consider only your own worktree, branch, lock, claim markers,
files and temp residue. Do not inspect, enumerate, or mention other sessions' worktrees,
branches, locks or issues — they are not your business and reporting them is noise. Resolve
your own scope from `.claude/agent-state/issue-work-orchestrator/registry.json` → your
`runs/<run-id>/` → the seeded `CURRENT_ISSUE` / `WORKTREE` / `BRANCH` / `PR` fields. With no
run state, your scope is the current working tree.

**Run identity — read this before writing any state (NON-NEGOTIABLE).**
`session-register.sh` (SessionStart) has ALREADY created this session's `runs/<run-id>/`
directory and seeded `resume_state.md` and `workflow_state.md` in it. Your job is to UPDATE
those files; you do not choose where they live. Find the path by reading `registry.json` and
using the `state_dir` of the entry keyed by THIS session's `session_id`, VERBATIM. NEVER
invent a readable run-id label such as `run-issue<N>-<timestamp>`: every Stop gate resolves
state from the registry-derived path, and state written anywhere else is read by NOTHING —
measured, exactly this deviation left both Stop hooks inert for a whole session. State fields
are plain `Name: value` lines and hooks read the LAST occurrence: correct a value by
APPENDING a new block at the END of the file, use the seeded field NAMES exactly (`BRANCH`,
`WORKTREE`, `PR` — not `CURRENT_BRANCH`/`CURRENT_WORKTREE`/`CURRENT_PR`), and keep
`SESSION_ID:` intact.

**Be terse.** Every finding is one line. No preamble, no restating these instructions, no
narrating what you are about to check. The verdict is the FIRST line of your reply so the
answer is visible at a glance. Evidence stays quoted but trimmed to the deciding fragment —
`no-guessing.md` still binds, `no-output-shortening.md` still governs what you READ (read
complete output; report the conclusion).

**Step 1 — Is the work actually DONE? (gate: nothing else runs until this passes)**
   For every issue this session was working, check against the project's standards, not your
   memory: implemented, tested (a test that reproduces the original symptom now passes, and
   the full suite is green for the merged SHA — cited from the CI run, not a local
   full-suite run: `ci-owns-the-test-suite.md` — with no skip/xfail dodges), and documented
   (issue updated, checklist ticked, spec artifacts committed, docs touched where the change
   requires it). Read the issue and `runs/<run-id>/resume_state.md` rather than trusting
   recall.
   - **If anything is missing, FINISH IT NOW** — `continue-work` semantics: resume the
     recorded phase and drive it to a terminal state. Do not report a gap and stop; do not
     ask whether to finish it. The answer is always yes, and `continuous-work.md` governs.
     Then re-enter Step 1.
   - Only when it genuinely passes, continue. If it CANNOT pass (a Proven Exception from
     `continuous-work.md` — irreversible action, sensitive information, a real design fork,
     a hard blocker), state which one in one line with its proof and record it as an
     `AWAITING_USER` line naming the ACTUAL reason (the gates check it for SUBSTANCE; an
     escalation described only in chat is indistinguishable from abandoning the work): not
     closeable.

**Step 2 — Is CI still running? (wait for it; it is part of the work)**
   Pending CI means the work is not finished, so this precedes every cleanliness check.
   - Determine your own run: the PR/branch from your run state, via the wrapper script
     (`use-git-wrapper-scripts.md`) — never `gh`/`glab`/`curl`.
   - If a run is non-terminal, WAIT and monitor to a terminal state. Do NOT use `watch-run`
     (no clock, no timeout — it cannot evidence elapsed time and will hold the terminal).
     Take repeated `get-run <id>` captures on a stated interval, and report only the latest
     status plus elapsed.
   - Red CI is the debugging loop, not a close-out: enumerate EVERY failing job and every
     failure inside it, group by root cause, fix them ALL, and push once
     (`remote-ci-must-pass.md`, `ci-owns-the-test-suite.md`). If CI cannot run at all, that
     rule's capacity ladder applies — relocate if the fallback exists, else file/comment then
     declare CI-OUTAGE MODE (`scripts/ci_outage_mode.py declare`) and run the pipeline
     locally via `scripts/run_checks.py`.
   - If CI-OUTAGE MODE is still declared (`python scripts/ci_outage_mode.py status`) but a
     real CI run has since gone green, CLEAR it — until it is cleared, every push in every
     worktree of this clone pays for a full local suite.
   - Carry forward one obligation only: if this session merged with the pipeline unrun
     (Rung 3) or with any job that did not execute, note in ONE line that a later run must
     confirm green. It lives on the repo, not the tree, and does not block closing.

**Step 3 — Your working tree is clean**
   `git status --porcelain` in your own tree (`git -C <your worktree>` if you have one), then
   `--untracked-files=all` to surface what the short form hides. Classify each untracked file
   per `keep-git-clean.md`: anything that BELONGS gets committed (or `.gitignore`d) before you
   can close; anything generated or temporary is deleted in Step 4. Never `git add -A`
   blindly.

**Step 4 — Delete your own leftovers**
   Delete what THIS session created. Never delete a file you did not create, and never touch
   another session's scratch — if ownership is unclear, leave it and say so in one line.
   1. `tmp/` (per `file-organization.md`, empty at end of task) and any scratch files this
      session wrote elsewhere in the tree. Untracked + self-created + generated = delete, no
      confirmation needed. Tracked, or possibly someone else's = leave.
   2. **OS temp residue — this is the big one.** Agent tooling leaks unbounded scratch OUTSIDE
      the project: every `cdk` invocation orphans a `jsii-kernel-*` directory that is never
      removed, and randomized `cdk.out<hash>` assemblies accumulate in the OS temp dir (one
      report reached 170 GB in two days). An aborted bundling also leaves `bundling-temp-*` /
      empty `asset.<hash>` that makes the NEXT deploy fail, so this is correctness, not just
      disk. Run the reaper:
      ```bash
      python scripts/reap_agent_temp.py --scoped-temp tmp/os-temp --apply
      ```
      It removes your session-scoped temp contents wholesale (provably yours) and, in the
      shared OS temp dir, only known residue patterns untouched for 30+ minutes — so a
      sibling's in-flight `cdk synth` is never harmed. Report its one-line total. Anything it
      reports as skipped or failed gets one line; do not expand on it.
   3. If `tmp/os-temp` is not configured as this tree's `TMPDIR`/`TEMP`/`TMP`, say so in one
      line — the reaper then falls back to pattern matching in the shared temp dir, which is
      best-effort. Wiring it is a setup step, not something to fix here.

**Step 5 — Your worktree, branch, lock AND claim markers are gone**
   Confirm the worktree and branch this session created were removed after merge. Tear down a
   per-worktree venv FIRST if one exists (locked DLLs otherwise block removal on Windows);
   `git worktree remove` plain, `--force` only after confirming no uncommitted work would be
   lost; then delete the branch and verify with `git worktree list`.
   Derive your claim set mechanically from evidence this run wrote — its
   `.locks/issue-<N>.lock` owner records, its registry entry, its `issue_queue.md` — **never
   from topical adjacency** (an issue split out of yours, or one whose title resembles yours,
   is not yours to unclaim). For each issue in that set, remove the claim per the convention
   in `environment.md` (unassign and/or remove the in-progress label through the ADDITIVE
   `remove-label` primitive with this run's `--run-id`, never a whole-set `labels` write),
   and remove the marker BEFORE removing that issue's local lock — the lock is the ownership
   evidence the removal guard reads. Then release your lock under
   `.claude/agent-state/issue-work-orchestrator/.locks/` and update the registry entry.
   Report only your own; say nothing about anyone else's.

**Step 6 — Issues updated and closed with evidence**
   For each issue this run finished: a final comment linking the merged PR and the evidence,
   the checklist fully ticked (or a remaining item explicitly deferred WITH its reason,
   routed per `issue-filing-discipline.md`), time spent recorded, and the issue closed via
   the wrapper. For an issue this run did NOT finish (Proven Exception only, per Step 1):
   leave it OPEN with a status comment carrying the branch, worktree, PR and evidence
   location, so any agent can resume from the issue alone — and do not remove its claim if
   the work is still in flight elsewhere.

**Step 7 — The shared local `main` was not moved**
   `git rev-parse main` vs `origin/main`. Local `main` being behind is the DESIGNED state on a
   shared clone (`keep-git-clean.md`) — report it as expected in one line, never as drift, and
   do not move it.

**Step 8 — A terminal `Phase` recorded**
   APPEND a block at the END of this run's `resume_state.md` carrying `Status: COMPLETED` and
   a terminal `Phase` (`DONE`/`COMPLETED`/`ABANDONED`/`ESCALATED`) — **that terminal value is
   what releases `issue-loop-gate.sh`**, and it must be the WHOLE value of the field
   (`Phase: DONE`, never `Phase: DONE (was IMPLEMENT)`). `WORKABLE_ISSUES_REMAIN` does not
   release the gate and never did. Do NOT record a terminal `Phase` to end a turn on work
   that is not finished: that is the failure the gate exists to catch, and the state file is
   the record someone will trust later.

**Output format — exactly this, nothing more**

```
CLOSE: YES|NO[ — <n> blocker(s)]

- [x] Work complete — <one clause>
- [x] CI — <status/run id, or "none">
- [x] Tree clean — <one clause>
- [x] Leftovers — <reclaimed total; tmp/ state>
- [x] Worktree/branch/lock/claims — <one clause>
- [x] Issues — <closed with evidence, or open-with-status>
- [x] Local main — <one clause>
- [x] Terminal Phase — <recorded value>
<optional: one line per carried-forward obligation>
```

Then: if every box is checked, ask in one sentence whether to archive now (`archive_session`
with `session_id: "self"`), and archive ONLY after an explicit go-ahead. If that MCP tool is
absent (a plain CLI session has no session-management server), RECOMMEND archiving and leave
it to the user rather than reporting a tool failure. If any box is unchecked, that box's
clause IS the explanation — do not add a paragraph about it.

No AI attribution in any comment, commit or issue text (`no-ai-attribution.md`). Never touch
`.kiro/`.
