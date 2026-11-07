# Directory restructure proposal (2026-11-07)

**Status:** revision 2; phase 1 implemented on branch `restructure/phase-1` (§11). **Scope:** the layout of this repository
before the overhaul that turns it into a project that runs on its own framework. The general mechanism
stays: a pasted prompt sets up or updates a project, for Claude Code and/or Kiro.

**Revision 2, after review:** the CV suite leaves the repository and goes to a git-ignored `archive/`
(§6). Content shared by several clients lives once in a `common/` folder next to the client folders,
and a small renderer produces each client's files from it (§5). The rest of revision 1 was accepted.

## 1. Recommendation in brief

```
prompts/       what an operator pastes; later also the setup specification, split into parts
  common/        parts shared by the Claude and Kiro setups                         (phase 2)
  claude/ kiro/  parts only one client needs                                        (phase 2)
clients/       natural-language assets that get installed
  common/        everything more than one client uses, written ONCE
  claude/        only what differs for Claude Code   → rendered into a project's .claude/
  kiro/          only what differs for Kiro          → rendered into a project's .kiro/
src/           ALL Python
  hooks/         the agent hook runtime (both clients)
  payload/       project scripts and their tests, laid out like a project root
  framework/     this repository's own tooling: the renderer (phase 2)
templates/     skeletons with placeholders + documents shipped verbatim (no Python)
docs/          this repository's own reports and design notes, never installed
test/          tests of the framework itself
archive/       git-ignored, local only: the CV suite and the legacy prompts
```

Seven rules carry the design (§3). The two that matter most: **nothing is written twice**, so shared
content lives in a `common/` folder next to the per-client folders. And **all Python lives in `src/`**,
where it is linted and tested. Phase 1 moves files and archives CV, and changes no install destination
other than dropping CV (§8). Phase 2 fills `common/`, which is editing work rather than moving (§5.4).

## 2. What the repository holds today

287 tracked files. Your three kinds of asset are all present, and four more kinds have no home of
their own yet:

| Kind | Where it lives today | Volume |
|---|---|---|
| **1. Prompts** (pasted) | root: `ClaudeCodeSetupPrompt.txt`, `KiroProjectSetupPrompt.v2.txt`, `FrameworkUpdatePrompt.txt` | 3,706 + 5,178 + 335 lines |
| — legacy prompts | root: `KiroProjectSetupPrompt.txt` (v1, superseded), `PythonProjectSetupPrompt.txt` (last changed 2025-11-28) | not referenced by any live file |
| **2. Code** | `claude-agents/spec-workflow/hooks/` (hook runtime, shared by Kiro), `cli-agents/spec-workflow/hooks/kiro_hooks.py`, `templates/*.py.template` (14 files, ~8,900 lines), `scripts/` | |
| **3. Templates & other files** | `templates/` (config skeletons, CI YAML, git hooks), `project-docs/codebuild-ci-backup-mechanism.md` (shipped verbatim) | |
| 4. Per-client natural-language assets (installed, not pasted) | `claude-agents/`, `claude-commands/`, `cli-agents/`, `kiro-prompts/` | 20 agents per client, 11 + 4 commands, 11 rules |
| 5. Prose shared by both clients | `claude-agents/spec-workflow/{phases,docs}/`. Written in Claude dialect; the Kiro prompt renders it with `sed 's#\.claude/#.kiro/#g'` (setup-kiro §8A) | 8 files |
| 6. The CV suite | `claude-agents/cv/`, `cli-agents/cv/`, `.kiro/specs/cv-customizer-agents/`; the only users of `python-docx` and `hypothesis` | 73 files → **archive** (§6) |
| 7. The repository's own records | `project-docs/*-2026-*.md` (9 reports), `ClaudeCodePortingAnalysis.md`, `KiroAdaptationAnalysis.md`, 8 agent design notes (`cli-agents/**/*Discussion.txt` and similar), `.kiro/specs/` | |

Facts the layout has to address:

- **Shipped Python is never linted or tested here.** None of the 14 `*.py.template` files has a
  `{{PLACEHOLDER}}`. They are plain Python, excluded from ruff and bandit only because of the suffix.
  Their test files are templates as well, so they run only inside consumer projects.
  `scripts/run_tests.py` runs only the CV suite, which is leaving the repository.
- **Code shared by both clients sits under `claude-agents/`.** The Kiro prompt copies `hooklib.py`,
  `hooks.py` and every `gate_*.py` from `claude-agents/spec-workflow/hooks/` into `.kiro/hooks-bin/`.
- **Source names differ from installed names.** Each Kiro agent is stored as `KiroCLIAgent-<Name>.json`
  and renamed to `<name>.json` at install time, using a table in setup-kiro §8A.1.
- **The same content is maintained twice.** These figures were measured with `difflib`. Lines are
  counted Claude / Kiro / identical in both:

  | Asset | Pairs | Overlap |
  |---|---|---|
  | Agents (all 20 exist for both clients, same names) | 20 | spec-conductor 126/134/112, code-merge-reviewer 113/104/90, issue-work-orchestrator 861/874/611, ci-workflow-agent 397/474/321. The spec-workflow reviewers differ by 10–37 lines each. |
  | Kiro agents with the whole prompt inline in the JSON | 7 of 20 | ~250 KB of prompt text inside JSON strings, the twin of a Claude `.md` |
  | Commands ↔ Kiro prompts | 4 | close-session 355/368/172, auto-work 210/181/70, compile-memory 99/86/31, continue-work 142/87/23 |
  | Rules ↔ steering | 11 | Claude rule files vs. the bodies inline in setup-kiro Part 8.27–8.37. Another 25 steering bodies (8.1–8.25) exist only inline, and setup-claude refers to them ("See KiroProjectSetupPrompt.v2.txt Part 4…"). |
  | The two setup prompts | — | 146 identical lines of substance out of ~3,000 each. They cover the same topics (MCP, layout, venv and git hooks, `.gitignore`, `pyproject`, AWS, wrappers, CI, docs) in text written separately. |

  Most differences in the agents are dialect: `.claude/` against `.kiro/`, `Read/Grep/Glob` against
  `read/grep/glob`, `/close-session` against `@close-session`. The rest is drift, where one copy
  received a fix the other did not.
- **`project-docs/` mixes two purposes.** One file ships to projects; nine are this repository's own reports.
- **This checkout has no framework installed yet.** There is no `CLAUDE.md`, and `.claude/` holds only
  `agent-state/` and `settings.local.json`.

## 3. Design rules

1. **One kind of asset per top-level directory.** From the path alone it is clear whether a file is
   pasted, installed, executed, or only read here.
2. **Nothing is written twice.** Wherever per-client folders exist (`clients/`, later `prompts/`), a
   `common/` sibling holds everything more than one client uses. A client folder holds only what is
   genuinely different for that client: metadata in that client's format, and files no other client
   has. The CI guard catches two near-identical files in different client folders (§7).
3. **Install output mirrors the install destination.** Rendering `clients/` for Claude produces a tree
   laid out exactly like a project's `.claude/`; for Kiro, exactly like `.kiro/`. `src/payload/` is
   laid out like the project root. No rename tables are needed, and the shipped tests'
   `ROOT = Path(__file__).parents[1]` finds `scripts/` in place.
4. **All Python lives in `src/`.** `clients/`, `prompts/` and `templates/` hold no Python, so every
   shipped module is linted, scanned and tested here before any consumer receives it.
5. **Sources are not installed copies.** Once the repository runs its own framework, the root's
   `.claude/`, `.kiro/`, `scripts/`, `.githooks/` and `CLAUDE.md` are output of its own update prompt,
   pinned by `.claude/FRAMEWORK_COMMIT`. A broken gate in `src/` reaches this repository's sessions only
   through a self-update.
6. **Shipped docs and own docs are separate.** `templates/docs/` ships into projects. `docs/` is only
   for this repository.
7. **A move is not a change.** Phase 1 moves files and rewrites paths; phase 2 changes content. Phase 1
   stays mechanical and verifiable, and every phase 2 change can be reviewed as content.

## 4. Proposed tree

### 4.1 Top level (end state; phase markers where the content arrives later)

```
README.md                    rewritten: what the framework is, the asset kinds, this map, which prompt to paste
LICENSE
.gitattributes .gitignore .pre-commit-config.yaml .secrets.baseline .githooks/   (this repo's own; paths updated)
prompts/
  README.md                  which prompt for which situation
  setup-claude.txt           ← ClaudeCodeSetupPrompt.txt      (phase 2: thin entry that reads common/ + claude/)
  setup-kiro.txt             ← KiroProjectSetupPrompt.v2.txt  (phase 2: thin entry that reads common/ + kiro/)
  update.txt                 ← FrameworkUpdatePrompt.txt
  common/                    (phase 2) setup parts both clients share: layout, venv + git hooks, .gitignore,
                               pyproject, AWS, wrappers, CI + delivery, docs + memory budget, verification
  claude/                    (phase 2) Claude-only parts: settings + hook registration, CLAUDE.md, SDD/TDD, orchestrator
  kiro/                      (phase 2) Kiro-only parts: MCP specifics, IDE hooks, editor settings
clients/
  README.md                  the common/client rule, the render step, the agent index
  common/                    written once, rendered for every client
    agents/<name>.md         (phase 2) the 20 agent bodies; neutral front matter: name, description
    commands/<name>.md       (phase 2) close-session, continue-work, auto-work, compile-memory
    rules/<name>.md          (phase 2) the 36 rule/steering bodies; neutral front matter: scope
    phases/                  ← claude-agents/spec-workflow/phases/*.md   (already single-source; phase 1)
    docs/                    ← claude-agents/spec-workflow/docs/{delivery,review-contract}.md   (phase 1)
  claude/                    only what differs for Claude Code
    dialect.json             (phase 2) substitutions, empty for the authoring dialect (§5.2)
    agents/<name>.md         phase 1: the Claude twin, moved flat; phase 2: shrinks to front matter (tools, model)
    commands/                ← claude-commands/*.md; phase 2 keeps only the 7 Claude-only commands
                               (spec-new, spec-tasks, spec-review, spec-implement, issues-work, work-issue, supervise)
    rules/                   ← claude-agents/spec-workflow/rules/*.md; phase 2 moves the bodies to common/rules/
    docs/                    run-identity.md + the 4 agent-sibling templates (Claude-only today)
  kiro/                      only what differs for Kiro
    dialect.json             (phase 2) .claude/rules/→.kiro/steering/, .claude/hooks/→.kiro/hooks-bin/, .claude/→.kiro/, /cmd→@cmd
    agents/<name>.json       ← cli-agents/**/KiroCLIAgent-<Name>.json renamed; phase 2: descriptor only, prompt rendered
    agents/<name>.md         phase 1 only: the 13 Kiro bodies; phase 2: merged into common/agents/, removed here
    prompts/                 ← kiro-prompts/*.md; phase 2: merged into common/commands/
src/
  hooks/                     ← claude-agents/spec-workflow/hooks/ (unchanged inside) + kiro_hooks.py
    tests/                   unchanged: shipped with the hooks, own pytest.ini/conftest
  payload/                   laid out like a project root
    scripts/                 ← templates/*.py.template without the suffix (wrappers, steward, reaper, memory_compile,
                               run_tests, run_checks, suite_semaphore, ci_outage_mode)
    src/aws_config.py        ← templates/aws_config.py.template
    test/                    ← templates/test_*.py.template
  framework/                 (phase 2) render.py, the renderer; stdlib only
templates/                   no Python
  README.md  ci/  githooks/  pre-commit-config.yaml.template  setup-hooks.sh.template
  config/                    ← aws_accounts.json.template, delivery.json.template, gitlab.json.template
  docs/                      ← project-docs/codebuild-ci-backup-mechanism.md   → a project's docs/
docs/                        never installed
  README.md                  includes the old→new path map
  reports/                   ← project-docs/*-2026-*.md (+ the 2 untracked ones), ClaudeCodePortingAnalysis.md,
                               KiroAdaptationAnalysis.md
  design/agents/             ← the 8 non-CV agent design notes and the agent-family READMEs
test/                        NEW: tests of the framework itself (§7)
scripts/                     this repo's own tools (run_tests.py re-pointed at the remaining suites, ci_outage_mode.py)
.kiro/steering/              unchanged (becomes part of the self-install)
archive/                     git-ignored as /archive/ — see §6
```

### 4.2 Why `src/payload/` mirrors a project root

The shipped tests locate the code they test from their own position
(`ROOT = Path(__file__).resolve().parents[1]`, then `ROOT / "scripts" / "merge_steward.py"`). With
`src/payload/test/` and `src/payload/scripts/` as siblings, the same file works unchanged in this
repository and in a consumer. The hook suite's conftest puts `tests/..` on `sys.path`, which
`src/hooks/tests/` keeps. `test_instruction_corpus_budget` checks a project's `CLAUDE.md` and rules, so
it runs only from the self-installed copy at `test/`.

### 4.3 Why the shared hook runtime is not under `clients/common/`

It is Python (rule 4). `src/` needs no `common/` split: everything in it is already client-neutral, and
which files a client receives is decided by the install step. `kiro_hooks.py` installs beside
`hooks.py` and imports it by bare name, so it sits in the same directory.

## 5. `common/`: one source, rendered per client

### 5.1 What goes where

| Lives in | Rule | Today's examples |
|---|---|---|
| `clients/common/` | used by two or more clients | agent bodies, the 4 command twins, rule bodies, phases, `delivery.md`, `review-contract.md` |
| `clients/<client>/` | metadata in that client's own format, or a file only that client has | Claude front matter (`tools`, `model`); Kiro agent JSON (`toolsSettings`, `hooks`, `allowedTools`); Claude-only commands; `run-identity.md`; Kiro IDE hook files |

When phase 2 merges a twin, three kinds of difference come up, and each is resolved differently:
- **Dialect** (paths, command prefixes): resolved by the client's `dialect.json`, never written by hand.
- **A genuine difference between clients** (Kiro's `subagent` tool runs at most four at a time;
  Claude's `/supervise` has no Kiro counterpart): written as a client block in the common file.
- **Drift** (one copy got a fix the other did not): resolved by keeping the newer text, once.

### 5.2 The common file format

- **Authoring dialect: Claude.** The 8 shared files are already written that way and rendered for Kiro.
  Keeping that dialect means they need no conversion. Claude is also the more detailed side of every
  twin.
- **Client blocks** for genuine differences:
  `<!-- client: kiro -->` … `<!-- end client -->`. The renderer keeps the blocks for the client being
  rendered and drops the others. Tool-name sentences ("Read/Grep/Glob for files; Bash only to run
  tests") are client blocks, not substitutions: a blind `Bash`→`shell` substitution would also rewrite
  "Git Bash".
- **Neutral front matter, flat `key: value` only**, so the renderer needs no YAML library. Agents
  carry `name` and `description` (today the two clients' descriptions differ, and the merge picks
  one). Rules carry `scope: always` or `scope: <globs>`, which the renderer maps to Claude `paths:` and
  Kiro `inclusion: always | fileMatch`. Commands carry `description` (and `argument-hint`, used by
  Claude only).

### 5.3 The renderer (`src/framework/render.py`, stdlib only)

`python src/framework/render.py --client claude|kiro --out <dir>` writes a tree laid out exactly like
`.claude/` or `.kiro/`. For each common file it resolves the client blocks, applies the dialect, and
merges the client overlay: Claude front matter is put in front of the body; the Kiro JSON gets
`name`/`description` and a `prompt: file://<name>.md`, so the seven inline prompts become files. Client-only
files are copied with their blocks resolved.

- **It never writes into a project.** The setup and update prompts run it from the pinned framework
  export into a staging directory. The agent then installs from there under the existing
  migration-aware merge rules, and uses the render as the update prompt's step-4 inventory. The
  mechanism stays prompt-driven, and the judgement about a project's local changes stays with the
  agent.
- It replaces the `sed` loops in setup-kiro §8A, which are the last shell-tool dependency in an install.
- **Rendered output is not committed.** A committed copy would bring back the duplicate this design
  removes. CI renders both clients on every change instead (§7).

### 5.4 Why filling `common/` is phase 2 and not part of the move

Every twin merge is a judgement per divergent line (dialect, genuine difference, or drift). Mixing
that into a move of 200 files would make the move impossible to review. Phase 1 puts each twin in its
client folder at its final path. In phase 2 the client file shrinks in place to an overlay, and the
body moves to `common/`. No client file moves twice.

## 6. Removing the CV suite

### 6.1 What goes to `archive/` (73 files, original paths kept so a restore is a plain move back)

| From | Files |
|---|---|
| `claude-agents/cv/` | 8 (7 agents + README) |
| `cli-agents/cv/` | 56 (7 agents × JSON, prompt and design note; `shared/` scripts, schemas, installer, READMEs; 20 test files and fixtures; `pytest.ini`) |
| `.kiro/specs/cv-customizer-agents/` | 9 |
| The legacy prompts `KiroProjectSetupPrompt.txt` (v1), `PythonProjectSetupPrompt.txt` | 2 (this changes revision 1's "delete": with `archive/` available, archiving gives the same repository state and keeps a local copy) |

### 6.2 What is edited instead (these files mention CV but are not only about CV)

- `prompts/setup-claude.txt`: the `cp claude-agents/cv/cv-*.md` line (Part 8.3), the CV README pointer
  and main-session note, the `cv-orchestrator` clause of verification item 9, and the appendix list.
- `prompts/setup-kiro.txt`: the header line, the "domain pack" sentence in §8A.1, and the two report lines.
- `claude-agents/README.md` → `clients/README.md`: the 7 CV rows, the CV section, and the CV mentions in
  the tool table. In `spec-workflow/README.md`, "generalizes the proven `cv-orchestrator` pattern"
  keeps the pattern and drops the name.
- `.gitignore`: the CV runtime section (`.kiro/agents/cv-*.json`, `.kiro/cv-suite/`) is replaced by `/archive/`.
- `.pre-commit-config.yaml`: the comments, and bandit `files: ^cli-agents/cv/shared/` → `^src/`.
- `scripts/run_tests.py`: `SUITE_DIR` points at the CV suite, its only suite. It becomes the list of
  remaining suites (hooks, payload, framework tests).
- Left as they are: `ClaudeCodePortingAnalysis.md` and `KiroAdaptationAnalysis.md`. They are reports,
  and their CV passages are history.

### 6.3 Consequences to know

- **The ignore entry must be `/archive/`, anchored to the root.** An unanchored `archive/` would also
  ignore `docs/archive/`. `memory_compile.py` writes there and the framework requires it to stay
  tracked ("verbatim, still in git"), and this repository gets that directory once it self-hosts.
- **`archive/` exists only in this checkout.** For git the move is a deletion. Other clones lose the
  files from their working trees on the next pull and keep them only in history. Recommendation: tag
  the last commit that still contains them (e.g. `cv-suite-final`). Then
  `git checkout cv-suite-final -- cli-agents/cv` restores them on any machine.
- **Dependencies shrink.** `python-docx` and `hypothesis` were used only by CV. What remains is
  standard library plus pytest and the dev tools.
- **Consumer projects:** a project that installed `cv-*.md` agents would, on its next update, find
  them classified as "obsolete (the framework no longer has it)". The update prompt removes such assets
  when nothing references them. See D6.

## 7. What the move touches, and the guard

- **Path references:** 573 occurrences in 88 files. About 100 are in historical records (left as they
  are; `docs/README.md` carries the old→new map), and CV removes some more. The rest are rewritten
  mechanically from one mapping table.
- **Repository configuration:** `.gitattributes` (`claude-agents/spec-workflow/hooks/** eol=lf` →
  `src/hooks/** eol=lf`), `.pre-commit-config.yaml` (drop the `templates/` lint exclusion, which no
  longer hides Python), `.gitignore` and `run_tests.py` (§6.2).
- **The guard (`test/test_layout.py`, stdlib, new in phase 1):** (a) every framework path named in a
  live file exists; (b) no `.py` file sits outside `src/`, `test/` or `scripts/`; (c) every
  `clients/kiro/agents/<x>.json` has `name == x`; (d) **no two files in different client folders are
  near-identical**, which keeps rule 2 true after phase 2 (the threshold is set when phase 2 starts,
  since phase 1 still holds the twins on purpose). Phase 2 adds render tests: both clients render;
  no `.claude/` survives in a Kiro render; every common agent has an overlay for every client; the
  output is deterministic.
- **First-run findings:** about 8,900 lines of Python come under ruff and bandit for the first time,
  and the shipped suites run here for the first time. The size of that debt is unmeasured. It is the
  first thing phase 1 checks.

## 8. Effect on consumer projects and operators

- **Phase 1:** no install destination changes except that CV agents are no longer shipped (D6).
  `.claude/FRAMEWORK_COMMIT` markers stay valid, and the next update sees comment-level deltas in
  shipped files.
- **Phase 2:** the rendered files are what projects already have, plus the fixes that drift had kept
  from one client. The merged twins show up as content updates in each project's next update, which
  is the intended effect.
- **Operators:** from phase 1 on, paste `prompts/update.txt`. A saved copy of `FrameworkUpdatePrompt.txt`
  names directories that no longer exist.
- **The pending repo rename** is independent of this work. If the local folder moves as well, do it
  outside any session working on the restructure, because the Claude memory key directory moves with it.

## 9. Plan

**Phase 1 — move and archive (one PR, mechanical):**
1. Branch. Measure the lint and test debt of the Python about to become visible (§7).
2. Tag the last commit with CV (`cv-suite-final`). Move the 75 files of §6.1 to `archive/`, and add
   `/archive/` to `.gitignore`.
3. `git mv` everything else per §4.1. Rename detection keeps the history (`git log --follow`).
4. Apply the reference rewrite and the §6.2 edits. Update `.gitattributes`, the pre-commit config and
   `run_tests.py`.
5. Add `test/test_layout.py` (a–c), and write `README.md`, `prompts/README.md`, `clients/README.md`
   and `docs/README.md`.
6. Verify: the guard passes, the remaining suites run, pre-commit passes on all files, and
   `hooks.py selftest` passes from `src/hooks/`. As a dry run, the branch's update prompt is run
   against one consumer project and must report no relocation and only the CV classification.

**Phase 2 — fill `common/`, then self-host** (separate PRs, in this order):
1. **Renderer** (`src/framework/render.py`) with its tests. The 8 already-shared files render first,
   which proves the renderer against today's `sed` output.
2. **Merge the twins** into `clients/common/`: the 20 agents (the 7 inline Kiro prompts become files),
   the 4 commands, and the 11 rule pairs. Extract the 25 Kiro-only steering bodies from setup-kiro
   Part 8 into `common/rules/`, which ends setup-claude's dependency on the Kiro prompt. Switch on
   guard (d).
3. **Split the setup prompts** into `prompts/common/`, `prompts/claude/` and `prompts/kiro/` parts,
   with thin entry files at the unchanged paths. With only 146 identical lines, this is a rewrite per
   topic, not an extraction. The render step replaces most of the 193 path references in the prompts.
4. **Self-hosting:** run `prompts/setup-claude.txt` against this repository from a pinned commit. It
   produces `CLAUDE.md`, `.claude/`, `pyproject.toml`, the installed `scripts/` and `test/` copies and
   the CI workflow.
5. **CI:** `run_checks.py` from the self-install, the render tests, and an
   install-into-scratch-project job that runs the shipped tests where they are installed.

## 10. Decisions

**Settled by the review** (revision 1's recommendations, accepted with "Otherwise, I like your proposal"):

| # | Decision |
|---|---|
| D1 | CV suite → git-ignored `archive/` (your call; replaces the `packs/cv/` recommendation) |
| D2 | Legacy prompts → `archive/` as well (§6.1) |
| D3 | Prompt names `setup-claude.txt` / `setup-kiro.txt` / `update.txt` |
| D4 | Non-CV agent design notes → `docs/design/agents/` (CV notes go to the archive with CV) |
| D5 | Shipped tests stay next to their code under `src/` |

**Decided 2026-11-07** (the recommendations, accepted with "Yes, start phase 1"):

| # | Question | Decision |
|---|---|---|
| D6 | When a consumer project still has the `cv-*` agents installed, should its next update remove them, or leave them? | Leave them. The update reports "no longer shipped by the framework; kept", and the project owner decides. One sentence in `prompts/update.txt` covers it. |
| D7 | Authoring dialect for `common/`: Claude dialect plus client blocks, or neutral placeholders (`{{dir}}`, `{{cmd:close-session}}`)? | Claude dialect. The 8 shared files already use it, and the source stays readable as plain prose. The renderer's "no `.claude/` in a Kiro render" check catches dialect gaps. |
| D8 | Should rendered client files be produced at install time, or committed to the repository? | At install time. Committing them would bring back the duplicate that `common/` exists to remove; CI renders both clients on every change instead. |
| D9 | Push the `cv-suite-final` tag to GitHub, so that every clone can restore the CV suite? | Yes. It is the only pointer to CV that other machines will have. |

## 11. Phase 1 as implemented (2026-11-07, branch `restructure/phase-1`)

- **Classification:** one script classified all 287 tracked files: 181 moved, 75 archived (copied from the
  committed bytes into the main checkout's git-ignored `archive/`, tag `cv-suite-final` on `71fb48d`), 2 deleted,
  29 left in place.
- **References:** 262 mechanical replacements, applied only at a path boundary; 76 anchored hand edits (the CV
  removal, the Kiro agent install section, whose rename table became a plain copy, and the reference lists); the
  `templates/README.md` table regenerated from its own rows; 5 relative links in `docs/design/agents/` fixed after
  the layout guard found them.
- **Deviations from §9 and the tree in §4.1:**
  - `cli-agents/spec-workflow/hooks/ruff.toml` is deleted, not moved: it had the same settings as the hooks'
    `ruff.toml`, which now covers `kiro_hooks.py` as well (rule 2).
  - A root `ruff.toml` extends `src/hooks/ruff.toml`, so the payload is linted with the hooks' profile (120
    columns, py39). The first-run debt, measured with the pinned pre-commit ruff, was 10 findings and 7 files to
    reformat. It was fixed in the move commit: 4 automatic fixes (2 unused imports in `github_wrapper.py`, 2 import
    orders), 3 wrapped lines, and 3 `noqa: C901` markers with reasons in `merge_steward.py`. Bandit at `-ll` finds
    nothing in `src/`.
  - The Claude install copies the hook modules by name (`hook*.py`, `gate_*.py`, ...) instead of
    `src/hooks/*.py`, which would now also copy `kiro_hooks.py` into `.claude/hooks/`.
  - `.gitignore` had a second unanchored rule, `reports/` (for JUnit output). It swallowed every new file in
    `docs/reports/`, so it is now `/reports/`. The guard probes a new file in every tracked directory against
    the ignore rules.
  - `scripts/run_tests.py` runs the three suites in one invocation from the root, with an explicit `--rootdir`.
  - The consumer dry run of step 6 was replaced by a check that needs no consumer: the project-side paths named
    in each prompt, compared before and after. `setup-kiro.txt` and `update.txt` name identical sets.
    `setup-claude.txt` lost only `.claude/agents/README.md`, which the removed glob-copy note was about.
  - The two untracked reports in the main checkout's `project-docs/` (red-pipeline, webhook-triggers) are not on
    the branch. They were never committed, and committing them was not part of this task.
- **Verification:** see the PR. The guard (`test/test_layout.py`) fails on a planted dangling path, a planted
  old-layout name and the unanchored `reports/` rule, and passes on the tree as committed.
