---
description: Compile the project's agent memory — turn findings-ledger rows and lessons older than six weeks into tests, hooks or one-line rules, archive the rest to docs/archive/, move incident narratives out of the always-loaded rules, and bring the instruction corpus and the capped docs back under budget. Nothing is deleted from git; what changes is what every session loads.
argument-hint: "[nothing — optionally --weeks N to change the six-week window]"
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
---

Bring this project's memory back to a shape every session can afford to load, without
losing anything it learned. Binding: `issue-filing-discipline.md` (the ledger is compiled,
not accumulated), `use-lessons-learned.md` (a lesson becomes a mechanism or is archived),
`proportionality.md`, `continuous-work.md` (this command runs to completion; the only
question it may ask is a genuine product decision about promoting a finding to an issue).

**What is automatic, and what is yours.** Size is not this command's job any more. The cap
drives retention: `python scripts/memory_compile.py reconcile --apply` keeps
`docs/findings-ledger.md` and `docs/lessons-learned.md` under their caps by rolling the
OLDEST rows and entries into `docs/archive/` (status ignored; undated items count as oldest),
and it runs on every write path — `ledger add` and `lesson add` call it — and from the
pre-commit hook `memory-reconcile`. Agents write rows ONLY with
`python scripts/memory_compile.py ledger add --subject S --finding F --evidence E --why W`
(one line, at most 240 bytes: a pointer, never the analysis) and lessons ONLY with
`python scripts/memory_compile.py lesson add --lesson L --enforced-by X --scope S`; they
check recurrence with `python scripts/memory_compile.py search <terms>`, which spans the
archive. What stays with this command is the human-judgment part: PROMOTE a row that
recurred or caused measured damage to an issue, ENFORCE one with a test, hook or rule line,
fill in a lesson's `Enforced-by`.

**Step 1 — Measure.** Run `python scripts/memory_compile.py report`. It prints every
capped file with its size and cap: the always-loaded corpus (`CLAUDE.md` + every
`.claude/rules/*.md` without `paths:`), `docs/forLLMConsumption.md`,
`docs/lessons-learned.md`, `docs/findings-ledger.md`, and any rule file carrying dated
incident headings. Read the whole output.

**Step 2 — Rules carry rules, not incidents.** For every rule file the report flags with
dated headings or with more than 12,000 bytes: keep the normative statements (what to do,
what is forbidden, the one-line why), move each incident narrative verbatim to
`docs/archive/rule-incidents/<rule>.md` under its date (`memory_compile.py
extract-rule-incidents --apply` does the mechanical move), and leave one pointer line.
Where a narrative proves a mechanism is missing (a guard the incident shows was inert), add
the mechanism — a test under `test/`, a hook check — rather than the story.

**Step 3 — Compile the ledger.** For every `docs/findings-ledger.md` row older than the
window (default six weeks; `memory_compile.py report` lists them): decide one of three.
`promoted #N` — it recurred or caused measured damage: file ONE issue through
`issue-intake-agent` with `Origin: agent-sweep`, `Filing-rationale: RESEARCH |
DESIGN-OPTIONS | OUT-OF-SCOPE`. `enforced <path>` — a test, a hook check or a one-line
rule statement now catches the class: write it, cite its path. `archived` — neither: move
the row verbatim with `memory_compile.py archive-ledger --apply` to
`docs/archive/findings-ledger-<YYYY-MM>.md`, or leave it to `reconcile`, which rolls it out
when the window fills. A row that has been `open` for twelve weeks with no recurrence is
archived without discussion. Then run `python scripts/memory_compile.py reconcile --apply`
once; every row it archives has its CI-skip tokens (`[skip ci]`, `[ci skip]`, `[no ci]`,
`[skip actions]`, `***NO_CI***`) defanged so a quoted row cannot silence a pipeline. The
active ledger ends under 60,000 bytes.

**Step 4 — Compile the lessons.** `docs/lessons-learned.md` holds entries of at most
five lines (`Date`, `Lesson`, `Enforced-by`, `Scope`). For every entry older than the
window whose `Enforced-by` is `none`: enforce it (test, hook, rule line — then fill in the
path) or archive it with `memory_compile.py archive-lessons --apply` to
`docs/archive/lessons-learned-<YYYY-MM>.md` (or leave it to `reconcile`). Entries longer
than five lines are rewritten through `memory_compile.py lesson add`; the narrative goes to
`docs/archive/incidents/<date>-<slug>.md`. The file ends under 40,000 bytes.

**Step 5 — The map stays a map.** `docs/forLLMConsumption.md` is ≤ 40,000 bytes: purpose,
architecture in brief, where things are, the invariants a change must respect, how to run,
test and deploy, and pointers to the topic docs. Anything longer is a topic doc under
`docs/` that is read on demand. Move, do not delete.

**Step 6 — Prove it.** Run `python scripts/run_tests.py test/test_instruction_corpus_budget.py`
and read the complete output. Every cap assertion passes, or Steps 2 to 5 are not done.
Then `python scripts/run_checks.py --group lint --group types`.

**Step 7 — Commit** on the current branch with a message naming what was compiled
(`n` rows archived, `m` enforced, `k` promoted; corpus `x` → `y` bytes). No push unless the
session's lifecycle calls for one.

**Output** — one fixed table and nothing else:

```
| File | Before | After | Cap |
| CLAUDE.md + unscoped rules | … | … | 100,000 |
| paths:-scoped rules + fileMatch steering | … | … | 45,000 |
| docs/forLLMConsumption.md | … | … | 40,000 |
| docs/lessons-learned.md | … | … | 40,000 |
| docs/findings-ledger.md | … | … | 60,000 |
Ledger rows: <n> archived, <m> enforced (<paths>), <k> promoted (#…)
Lessons: <n> archived, <m> enforced
Rule incidents moved: <n> (from <files>)
Corpus test: PASS | FAIL (<assertion>)
```
