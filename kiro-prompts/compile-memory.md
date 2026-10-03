# @compile-memory — compile the project's agent memory

Bring this project's memory back to a shape every session can afford to load, without losing
anything it learned. Binding steering: `issue-filing-discipline` (the ledger is compiled, not
accumulated), `use-lessons-learned` (a lesson becomes a mechanism or is archived),
`proportionality`, `continuous-work` (run to completion; the only question you may ask is a
genuine product decision about promoting a finding to an issue). Nothing is deleted from git;
what changes is what a session loads.

**Step 1 — Measure.** Run `python scripts/memory_compile.py report` and read the whole
output: every capped file with its size and cap — the always-loaded corpus (root instruction
file plus every `inclusion: always` steering file), `docs/forLLMConsumption.md`,
`docs/lessons-learned.md`, `docs/findings-ledger.md` — and every steering file carrying dated
incident headings.

**Step 2 — Rules carry rules, not incidents.** For every steering file flagged with dated
headings or over 12,000 bytes: keep the normative statements, move each incident narrative
verbatim to `docs/archive/rule-incidents/<rule>.md`
(`python scripts/memory_compile.py extract-rule-incidents --apply`), leave one pointer line.
Where a narrative shows a mechanism is missing, add the mechanism (a test, a hook check)
rather than the story.

**Step 3 — Compile the ledger.** For every `docs/findings-ledger.md` row older than six weeks:
`promoted #N` (it recurred or caused measured damage — ONE issue via the issue-intake agent,
`Origin: agent-sweep`), `enforced <path>` (a test, hook check or one-line rule now catches the
class — write it), or `archived` (`python scripts/memory_compile.py archive-ledger --apply`
moves it verbatim to `docs/archive/findings-ledger-<YYYY-MM>.md`). A row open for twelve weeks
with no recurrence is archived without discussion. If the ledger is still over its cap after the age pass — a ledger that grew 880 KB in five
weeks has nothing six weeks old — archive oldest-first with `--until-under-cap --apply`; the
archive stays greppable, and a row that mattered comes back through recurrence. When the
unresolved rows alone do not bring the file under the cap, `--until-under-cap` also moves
resolved (`promoted`/`enforced`) rows oldest-first, and every row it archives has its CI-skip
tokens (`[skip ci]`, `[ci skip]`, `[no ci]`, `[skip actions]`, `***NO_CI***`) defanged so a
quoted row cannot silence a pipeline. The active ledger ends under 60,000 bytes.

**Step 4 — Compile the lessons.** Entries in `docs/lessons-learned.md` are at most five lines
(`Date`, `Lesson`, `Enforced-by`, `Scope`). For every entry older than six weeks whose
`Enforced-by` is `none`: enforce it and record the path, or archive it
(`python scripts/memory_compile.py archive-lessons --apply`). Longer entries are cut to the
format; their narrative goes to `docs/archive/incidents/<date>-<slug>.md`. Under 40,000 bytes.

**Step 5 — The map stays a map.** `docs/forLLMConsumption.md` is ≤ 40,000 bytes: purpose,
architecture in brief, where things are, invariants, how to run/test/deploy, pointers to topic
docs. Move detail into topic docs under `docs/`; do not delete it.

**Step 6 — Prove it.** `python scripts/run_tests.py test/test_instruction_corpus_budget.py`
must pass in full; then `python scripts/run_checks.py --group lint --group types`.

**Step 7 — Commit** with a message naming what was compiled. No push unless the session's
lifecycle calls for one.

**Output** — one fixed table and nothing else:

```
| File | Before | After | Cap |
| always-loaded corpus | … | … | 100,000 |
| paths:-scoped rules + fileMatch steering | … | … | 45,000 |
| docs/forLLMConsumption.md | … | … | 40,000 |
| docs/lessons-learned.md | … | … | 40,000 |
| docs/findings-ledger.md | … | … | 60,000 |
Ledger rows: <n> archived, <m> enforced (<paths>), <k> promoted (#…)
Lessons: <n> archived, <m> enforced
Rule incidents moved: <n> (from <files>)
Corpus test: PASS | FAIL (<assertion>)
```
