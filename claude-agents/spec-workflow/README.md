# Spec-Driven + Test-Driven Development for Claude Code

This is the automated spec+test workflow — the Claude Code replacement for the manual
Kiro CLI ↔ Kiro IDE loop (prompt-author → generate spec → review → resolve → repeat →
implement). It runs end to end in **one Claude Code session**, driven by a
main-session conductor that delegates to a panel of specialist subagents, converges
the spec to zero blocking defects, then implements test-first and **proves every claim
with captured command/test evidence**.

It generalizes the proven `cv-orchestrator` pattern (main session owns the loop,
delegates to flat subagents via the `Agent` tool, aggregates on-disk findings,
enforces a convergence predicate + iteration cap, never does the protected work
itself). Subagents cannot nest, so **every delegation originates from the conductor**.

## The pipeline

```
claude --agent spec-conductor
  SETUP → PROMPT_AUTHORING (interview)
        → REQUIREMENTS (EARS) → DESIGN (Correctness Properties, Testing Strategy,
                                        threat model, DevOps, AC→validation map)
        → DESIGN_REVIEW_LOOP  (6-reviewer panel ↔ author; exit: 0 A+B + full coverage)
        → TASKS (test-first)  → TASKS_REVIEW_LOOP (light panel; exit: 0 A+B)
        → IMPLEMENT_LOOP (per task: RED → GREEN → no-regress, conductor captures evidence)
        → VERIFY (adversarial-verifier re-runs & refutes; panel re-checks the diff)
        → EVIDENCE_REPORT (property → test → quoted output)
```

You stay out of the loop except: the interview (one question at a time), a single
batched escalation if a review loop hits its cap/oscillates, and the final report.

### The readiness gate (maximally autonomous)
A spec is ready to implement when **both** hold, after ≥1 review cycle:
- **Negative:** combined **A+B findings == 0** across the whole panel, computed
  against the *current* artifact (stale verdicts are rejected). A = execution
  blockers, B = intent deviations/gaps. C (clarifications) and D (nits) never block.
- **Positive:** `test-architect` confirms ≥1 Correctness Property per requirement and
  100% of acceptance criteria map to a test.

This is your "zero defects after at least one adversarial cycle" rule, hardened with a
positive proof-coverage gate so silence ≠ approval.

### Proof with evidence (hard requirement)
The `spec-implementer` writes tests and code but **never certifies its own work**. The
conductor runs the tests and captures complete output to `evidence/`. The
`adversarial-verifier` independently re-runs the suite and tries to *refute* every
"it works" claim (kill-the-mutant: revert/stub the impl and require the test to fail;
vacuity/skip/xfail scan; property stress; coverage; red-for-the-right-reason audit).
The final `evidence/REPORT.md` quotes real command output for every passing claim.

## The agents (in `claude-agents/spec-workflow/`)

| Agent | Role | Gate phase |
|---|---|---|
| `spec-conductor` | Main-session orchestrator; owns the loop, delegation, gates, state. | all |
| `spec-author` | Writes/edits requirements, design, tasks. Never grades itself. | gen + revise |
| `spec-researcher` | Read-only codebase/MCP research bursts for the interview. | prompt |
| `test-architect` ★ | Properties + coverage map + AC→test mapping (positive gate). | design, tasks, verify |
| `adversarial-verifier` ★ | Re-runs & refutes every claim with evidence. | verify |
| `standards-reviewer` | Conformance to project/coding standards + `.claude/rules/`. | design, verify |
| `best-practice-reviewer` | Alignment with external best practices (MCP/web). | design, verify |
| `security-reviewer` | Threat model + vuln/secret/least-privilege review. | design, verify |
| `devops-iac-reviewer` | CI/CD, IaC least-privilege, observability, rollback. | design, verify |
| `spec-implementer` | Writes tests then code per task, test-first. Never certifies. | implement |

★ = core. Reused from `claude-agents/spec-review/`: `spec-review-agent` (the A/B/C/D
adversarial reviewer; runs in report-only mode under the conductor) and
`spec-prompt-author-agent` (the interview protocol; also backs `/spec-new`).

Phase procedures are authored once in `phases/spec-phase-*.md` and followed by both
the conductor and the slash commands (single source of truth). The shared decision-log
convention is `rules/agent-state-convention.md`. The TDD gates are in `hooks/`.

## Slash commands (in `claude-commands/`)

For running one phase on demand instead of the whole pipeline:

| Command | Does |
|---|---|
| `/spec-new "<idea>"` | Interview + author `prompt.md` for a new feature/bugfix. |
| `/spec-review [slug]` | One review-panel pass; reports combined A+B + coverage. |
| `/spec-tasks [slug]` | Generate/regenerate `tasks.md` (test-first) + light review. |
| `/spec-implement [slug]` | TDD implement + adversarial verify + evidence report. |

## Install (per project)

```bash
mkdir -p .claude/agents .claude/commands .claude/rules \
         .claude/hooks .claude/specs/_workflow/phases

# agents
cp claude-agents/spec-workflow/spec-conductor.md          .claude/agents/
cp claude-agents/spec-workflow/spec-author.md             .claude/agents/
cp claude-agents/spec-workflow/spec-researcher.md         .claude/agents/
cp claude-agents/spec-workflow/test-architect.md          .claude/agents/
cp claude-agents/spec-workflow/adversarial-verifier.md    .claude/agents/
cp claude-agents/spec-workflow/standards-reviewer.md      .claude/agents/
cp claude-agents/spec-workflow/best-practice-reviewer.md  .claude/agents/
cp claude-agents/spec-workflow/security-reviewer.md       .claude/agents/
cp claude-agents/spec-workflow/devops-iac-reviewer.md     .claude/agents/
cp claude-agents/spec-workflow/spec-implementer.md        .claude/agents/
cp claude-agents/spec-review/spec-review-agent.md         .claude/agents/
cp claude-agents/spec-review/spec-prompt-author-agent.md  .claude/agents/

# commands, phase fragments, shared rule, hooks
cp claude-commands/spec-*.md                              .claude/commands/
cp claude-agents/spec-workflow/phases/*.md                .claude/specs/_workflow/phases/
cp claude-agents/spec-workflow/rules/agent-state-convention.md .claude/rules/
cp claude-agents/spec-workflow/rules/no-ai-attribution.md      .claude/rules/
cp claude-agents/spec-workflow/hooks/*.sh                 .claude/hooks/ && chmod +x .claude/hooks/*.sh
```

Then register the TDD gates in `.claude/settings.json` (PreToolUse(Bash) →
`spec-tdd-gate.sh`; Stop → `spec-stop-gate.sh`) and add to root `CLAUDE.md`:
"All agents follow `.claude/rules/agent-state-convention.md` for state and decision
logging, and `.claude/rules/no-ai-attribution.md` for descriptive names with no
Claude/AI attribution in commits, PRs, issues, branches, or worktrees."
`ClaudeCodeSetupPrompt.txt` (Part 12) does all of this for you.

## Durable state (preserved for later agents)

```
.claude/specs/<feature>/
  prompt.md  prompt-discussion.md  qa_log.md
  requirements.md (or bugfix.md)  design.md  tasks.md  open-questions.md
  review/{spec,test,standards,best-practice,security,devops}/iteration-NN.md
  review/review-latest.md          # conductor's aggregated A+B union
  decisions/decision-log.md        # append-only DL-NNN ledger (ALL agents write here)
  evidence/{red,green,regress,verify}/...   # captured command output
  evidence/REPORT.md               # the proof chain
.claude/agent-state/<agent>/       # per-agent resume_state.md + logs (gitignored)
.claude/agent-state/spec-conductor/workflow_state.md   # master phase machine
```

The `decisions/decision-log.md` (`DL-NNN` entries: Decision / Driver / Alternatives /
Evidence / Supersedes / Artifacts) is the cross-agent memory: every agent — these new
ones AND the ported ones (dead-code, doc-review, issue-*, product-management, cv/*) —
appends to it, so decisions and the discussion behind them survive across agents and
sessions. See `rules/agent-state-convention.md`.

## Coexistence with Kiro

Specs live under `.claude/specs/` and never touch `.kiro/`. You can keep using Kiro
spec mode on the same project; the two trees are independent. The artifact format
mirrors Kiro's (EARS requirements, design with properties, checkbox tasks) so the
mental model is identical.

## Bugfix vs feature

The conductor detects FEATURE vs BUGFIX from your kickoff. A bugfix produces
`bugfix.md` (Current / Expected / **Unchanged-behavior regression-prevention** in
EARS) instead of `requirements.md`, and the test-architect requires a regression test
for every "SHALL CONTINUE TO" clause — so a fix cannot silently break existing
behavior.
