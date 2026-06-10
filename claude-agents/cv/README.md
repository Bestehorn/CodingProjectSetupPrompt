# CV Customizer Suite — Claude Code

This is the Claude Code port of the seven-agent CV Customizer suite from
[`cli-agents/cv/`](../../cli-agents/cv/). It turns a candidate's CV (`.docx`)
and an optional motivational letter into a polished package tailored to a
specific job description, through an iterative review-and-edit loop driven by an
orchestrator that delegates to six specialist agents.

| Agent | Role |
|---|---|
| `cv-orchestrator` | Entry point; drives the loop; the only agent you talk to. |
| `cv-editor` | Sole writer of the CV / letter working copies. |
| `cv-spell-format-reviewer` | Spelling, punctuation, capitalization, formatting. |
| `cv-language-content-reviewer` | Prose quality; length reduction over the page limit. |
| `cv-jd-alignment-reviewer` | Gap analysis vs. the job description; candidate Q&A. |
| `cv-ats-reviewer` | Applicant-tracking-system hazards and keyword coverage. |
| `cv-hiring-manager-reviewer` | Whole-package review; `INVITE` / `DO_NOT_INVITE`. |

## Why this one needs special handling

In Kiro, `cv-orchestrator` was a normal custom agent that spawned the six
delegates through Kiro's native `subagent` tool. **Claude Code subagents cannot
spawn other subagents** — only the *main session* can delegate (via the built-in
`Agent` tool).

So the rule is simple and it fully preserves the architecture:

> **`cv-orchestrator` must run as the main session, not as a subagent.**
> The six delegates run as ordinary subagents that the main session calls.

When `cv-orchestrator` is the main session, it *does* have the `Agent` tool, and
its frontmatter pre-authorizes exactly the six delegates:

```yaml
tools: Read, Write, Edit, Bash, Agent(cv-editor, cv-spell-format-reviewer, cv-language-content-reviewer, cv-jd-alignment-reviewer, cv-ats-reviewer, cv-hiring-manager-reviewer)
```

This `Agent(...)` allowlist is the direct equivalent of Kiro's
`toolsSettings.subagent.availableAgents`. Nothing about the loop, the
convergence predicate, the 10-iteration cap, the backups, or the resume
protocol changes — only the spawn mechanism (Kiro `subagent` tool →
Claude Code `Agent` tool), which the orchestrator file's adaptation preamble
spells out.

## One-time setup (you do this, the agents do not)

The agents never install anything. Install the prerequisites yourself once per
machine — same as the Kiro suite.

### 1. Python packages (into the environment Claude Code's Bash tool uses)

```bash
python -m pip install python-docx pdfminer.six beautifulsoup4 pypdf pywin32
```

`pywin32` is Windows-only (Microsoft Word page-count engine). On macOS/Linux,
omit it and install LibreOffice so `soffice` is on the PATH (the page-count
fallback). The scripts import each heavy library lazily — a `.docx`-only run
with a `.txt` job description needs neither the PDF nor HTML libraries.

### 2. Install the agents into `.claude/agents/`

```bash
mkdir -p .claude/agents
cp claude-agents/cv/cv-*.md .claude/agents/
```

That copies all seven (`cv-orchestrator` + the six delegates). The deterministic
helper scripts stay where they are — `cli-agents/cv/shared/scripts/` — and the
agents reference them by that repo-relative path. **No installer and no path
rewriting** is needed (unlike the Kiro `install_agents.py` flow); Claude Code
discovers the agents from `.claude/agents/` directly.

> If you run from a copy of the repo that does not include
> `cli-agents/cv/shared/`, copy that `shared/` tree along with the agents and
> tell the orchestrator the path to the scripts in your first message.

## Running the workflow

Start Claude Code **with the orchestrator as the main session**:

```bash
claude --agent cv-orchestrator
```

Then give it your inputs in the first message, as labeled lines (you can also
phrase it conversationally — the orchestrator echoes back its interpretation
before proceeding):

```
cv: path/to/cv.docx                 # MANDATORY — the CV (.docx)
jd: path/to/job-description.pdf     # MANDATORY — the job description (.html/.txt/.pdf/.docx/.md)
letter: path/to/cover-letter.docx   # OPTIONAL — the motivational letter (.docx)
database: path/to/extensive-cv.md   # OPTIONAL — the bullet-point database (.docx/.md/.txt/.pdf)
cv_page_limit: 2                    # OPTIONAL — override the CV page limit (default 2)
letter_page_limit: 1                # OPTIONAL — override the letter page limit (default 1)
```

- `cv` and `jd` are mandatory; the workflow fails fast if either is missing.
- All paths are workspace-relative literal paths (never environment variables).
- The orchestrator works on **copies** under `.claude/agent-state/cv-workflow/working/`
  and never touches your originals. On completion it writes a termination report
  with the tailored package, accepted gaps, any database writeback/sidecar
  location, and the final per-document page counts.

That is the whole change. The candidate still talks only to the orchestrator;
the six delegates run non-interactively and hand their on-disk Findings back,
exactly as designed.

### Auto-approving the delegates and helper scripts

To avoid an approval prompt each time the orchestrator delegates or runs a
helper script, add to `.claude/settings.json` (or `settings.local.json`):

```json
{
  "permissions": {
    "allow": [
      "Agent(cv-editor)",
      "Agent(cv-spell-format-reviewer)",
      "Agent(cv-language-content-reviewer)",
      "Agent(cv-jd-alignment-reviewer)",
      "Agent(cv-ats-reviewer)",
      "Agent(cv-hiring-manager-reviewer)",
      "Bash(python cli-agents/cv/shared/scripts/*)",
      "Bash(python tmp/cv-editor/*)"
    ]
  }
}
```

These mirror the Kiro `shell.allowedCommands` / `subagent.availableAgents`
allowlists. (The Kiro originals also *denied* `git`, `pip install`, `rm`,
`curl`, etc. for the delegates; the agent bodies already forbid those actions.
If you want hard enforcement, add matching `permissions.deny` rules — note they
apply session-wide, not per delegate.)

## Fallback: driving the suite by hand (no orchestrator agent)

If you prefer not to run `cv-orchestrator` as the main session — or you want to
inspect each step — you can act as the conductor yourself from a normal Claude
Code session and call each delegate explicitly. The delegates are unchanged and
self-contained; each writes its Findings to
`.claude/agent-state/cv-workflow/`. A single iteration looks like:

1. `@agent-cv-spell-format-reviewer review the working copy at <path>, iteration 1`
2. `@agent-cv-language-content-reviewer …` (and the other reviewers, in the
   order the orchestrator body specifies)
3. `@agent-cv-jd-alignment-reviewer …` — relay its candidate questions yourself,
   one at a time.
4. Aggregate the reviewers' Findings into a Change_List and hand it to
   `@agent-cv-editor` for the one working copy.
5. Re-run the reviewers; stop when the convergence predicate in the orchestrator
   body is met or after 10 iterations.

This is more manual and you take on the orchestrator's bookkeeping, so the
`claude --agent cv-orchestrator` path above is the recommended way. The fallback
exists only for step-by-step inspection or environments where launching a
named main-session agent is inconvenient.

## State, resume, and outputs

- Shared workflow state: `.claude/agent-state/cv-workflow/` (working copies,
  backups, run manifest, iteration log, change lists).
- Per-agent state: `.claude/agent-state/<agent-name>/`.
- Resume: if a run is interrupted, start `claude --agent cv-orchestrator` again
  and tell it to resume; it reads its state-directory markers and continues
  (the delegates have their own resume protocols).
- Add `.claude/agent-state/` to `.gitignore` — it is per-run runtime state.
