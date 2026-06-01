# CV Customizer Agent Suite

A suite of seven Kiro CLI custom agents that turn a candidate's existing CV (a
Word `.docx`) and an optional motivational letter into a polished application
package tailored to a specific job description. One orchestrator agent drives an
iterative review-and-edit loop, delegating to six specialist agents as
subagents, until every reviewer's quality gate passes (or the iteration cap is
reached).

The candidate interacts only with the orchestrator. The other six agents run as
non-interactive subagents and hand their results back automatically.

| Canonical name                  | Role                                                        |
| -------------------------------- | ----------------------------------------------------------- |
| `cv-orchestrator`                | Entry point; drives the loop; the only agent you talk to.   |
| `cv-editor`                      | Sole writer of the CV/letter working copies.                |
| `cv-spell-format-reviewer`       | Spelling, punctuation, capitalization, formatting.          |
| `cv-language-content-reviewer`   | Prose quality; length reduction when over the page limit.   |
| `cv-jd-alignment-reviewer`       | Gap analysis vs. the job description; candidate Q&A.        |
| `cv-ats-reviewer`                | Applicant-tracking-system hazards and keyword coverage.     |
| `cv-hiring-manager-reviewer`     | Whole-package review; `INVITE` / `DO_NOT_INVITE`.           |

This authoring tree under `cli-agents/cv/` is the only version-controlled part
of the suite. The installer (`shared/install/install_agents.py`) copies it to a
fixed installed root and generates discovery configs under `.kiro/agents/`;
those outputs are gitignored and regenerated per machine because they carry
machine-specific absolute paths.

---

## 1. One-time environment setup (you run this, not the agents)

The agents never install anything. Per the suite's design, an agent that hits a
missing library exits with a clear error naming the package and the orchestrator
relays it as a fatal setup error — it will not run `pip install` on your behalf.
So before the first run, install the prerequisites yourself, once per machine.

### 1.1 Python packages

The deterministic helper scripts under `shared/scripts/` depend on these
packages (pip name on the left, what it powers on the right):

| pip package        | import name | used for                                                  |
| ------------------ | ----------- | --------------------------------------------------------- |
| `python-docx`      | `docx`      | reading/editing `.docx`, extracting Normalized_Text       |
| `pdfminer.six`     | `pdfminer`  | extracting text from PDF job descriptions / databases     |
| `beautifulsoup4`   | `bs4`       | extracting text from HTML job descriptions                |
| `pypdf`            | `pypdf`     | counting pages of the rendered PDF (LibreOffice fallback) |
| `pywin32`          | `win32com`  | Microsoft Word automation for page counting (Windows)     |

Install them into the Python environment Kiro CLI will use:

```
python -m pip install python-docx pdfminer.six beautifulsoup4 pypdf pywin32
```

Notes:

- `pywin32` is Windows-only and is only needed for the primary (Microsoft Word)
  page-counting engine. On non-Windows hosts, omit it and rely on the LibreOffice
  fallback described below.
- The scripts import each heavy library lazily, only in the code path that needs
  it. A `.txt`/`.md` job description needs none of `pdfminer.six` / `beautifulsoup4`;
  a `.docx`-only run needs neither PDF nor HTML libraries. Install the full set
  anyway if you expect to handle every input format.

### 1.2 Page-counting renderer (required for the page-limit gate)

The page limit (default: CV ≤ 2 pages, letter ≤ 1 page) is a hard convergence
gate, so the page count must be measured by actually rendering the document —
never guessed. `shared/scripts/page_count.py` uses, in order:

1. **Microsoft Word automation (primary).** Via `pywin32`, it opens the `.docx`,
   calls `Document.Repaginate()`, lets pagination settle, and reads
   `ComputeStatistics(wdStatisticPages)`. Word is authoritative because you edit
   the result in Word downstream, so the gate matches what you will see.
2. **LibreOffice headless (fallback).** If Word automation is unavailable, the
   script converts the document with `soffice --headless --convert-to pdf` and
   counts pages with `pypdf`. The `soffice` executable is located on the system
   executable search path (via `shutil.which`); install LibreOffice so that its
   `soffice` program is invocable from a normal shell. The standard LibreOffice
   installer arranges this on most platforms.

If **neither** renderer is available, `page_count.py` exits non-zero and the
orchestrator stops with a fatal setup error rather than risk silently passing an
over-length CV. To use the suite at all you need at least one of: Microsoft Word
(plus `pywin32`) or LibreOffice (plus `pypdf`).

### 1.3 No environment variables

This suite never reads environment variables — not for input paths, not for
configuration, not for credentials. Do **not** set `AWS_PROFILE` or any other
environment variable for the suite's benefit, and the installer does not read
any. All locations are passed as explicit arguments or read from
workspace-relative files. (Even the LibreOffice `soffice` lookup uses the
process's existing executable search path, not a suite-specific variable.)

---

## 2. Installing the suite

Kiro CLI discovers custom agents only in `.kiro/agents/` (workspace) or
`~/.kiro/agents/` (global). It does **not** scan `cli-agents/cv/`. So you must
run the installer once to make the agents discoverable.

`shared/install/install_agents.py`:

1. Copies the whole authoring tree to a fixed installed root —
   `.kiro/cv-suite/` for a workspace install, or `<home>/.kiro/cv-suite/` for a
   global install — preserving prompts, `shared/scripts/`, and `shared/schemas/`
   together.
2. Generates one discovery config per agent at `.kiro/agents/<canonical-name>.json`
   (e.g. `.kiro/agents/cv-orchestrator.json`), with the `name` field set to the
   canonical name, the `prompt` rewritten to an absolute `file://` URI under the
   installed tree, and every shared-script reference rewritten to its absolute
   installed path.
3. Verifies the result: each config's `name` matches its filename and the
   orchestrator's `availableAgents`/`trustedAgents`, and every referenced prompt
   and script exists.

### 2.1 Workspace install (recommended)

Run from the repository root:

```
python cli-agents/cv/shared/install/install_agents.py --mode workspace
```

This installs into `<workspace-root>/.kiro/`. The workspace root is inferred
from the installer's own location (the repo root). To install into a different
workspace explicitly, pass `--workspace-root`:

```
python cli-agents/cv/shared/install/install_agents.py --mode workspace --workspace-root /path/to/other/workspace
```

### 2.2 Global install

A global install requires an explicit `--home-dir` — the installer never reads
`$HOME` / `%USERPROFILE%` from the environment:

```
python cli-agents/cv/shared/install/install_agents.py --mode global --home-dir D:\Users\you
```

This installs into `<home-dir>/.kiro/` (the tree at `<home-dir>/.kiro/cv-suite/`
and configs at `<home-dir>/.kiro/agents/`).

### 2.3 Flags

| Flag                       | Meaning                                                                                  |
| -------------------------- | ---------------------------------------------------------------------------------------- |
| `--mode workspace\|global` | Install scope. Default: `workspace`.                                                     |
| `--workspace-root PATH`    | Workspace root for `--mode workspace`. Default: inferred repo root.                      |
| `--home-dir PATH`          | Home directory for `--mode global`. **Required** for global installs (passed explicitly). |
| `--kiro-dir PATH`          | Explicit target `.kiro` directory. Overrides `--mode`/`--workspace-root`/`--home-dir`.   |
| `--authoring-root PATH`    | Path to the `cli-agents/cv/` authoring tree. Default: inferred from the script location. |
| `--no-verify`              | Skip the post-install verification pass (not recommended).                               |

### 2.4 What is gitignored

The installer outputs are regenerated per machine and are gitignored:

- `.kiro/agents/cv-*.json` — generated discovery configs (machine-specific absolute paths)
- `.kiro/cv-suite/` — the installed tree
- `.kiro/agent-state/` — per-run runtime state

Only the `cli-agents/cv/` authoring tree is version-controlled. Re-run the
installer after pulling changes or moving the tree to a new machine.

---

## 3. Running the workflow

After installing, start the orchestrator:

```
kiro-cli --agent cv-orchestrator
```

Then give it your inputs in your first message. The canonical format is a set of
labeled lines (you can also phrase it conversationally — the orchestrator echoes
back its interpretation before proceeding):

```
cv: path/to/cv.docx                 # MANDATORY — the CV (.docx)
jd: path/to/job-description.pdf     # MANDATORY — the job description (.html/.txt/.pdf/.docx/.md)
letter: path/to/cover-letter.docx   # OPTIONAL — the motivational letter (.docx)
database: path/to/extensive-cv.md   # OPTIONAL — the bullet-point database (.docx/.md/.txt/.pdf)
cv_page_limit: 2                    # OPTIONAL — override the CV page limit (default 2)
letter_page_limit: 1                # OPTIONAL — override the letter page limit (default 1)
```

Input rules:

- `cv` and `jd` are mandatory; the workflow fails fast with a clear error if
  either is missing or its file does not exist.
- All paths are treated as workspace-relative literal paths (never expanded as
  environment variables).
- Omitting `letter` skips all letter work. Omitting `database` disables
  database-driven gap-filling; content you provide during Q&A is recorded in a
  `Database_Sidecar` instead.
- `cv_page_limit` / `letter_page_limit` are optional positive integers; defaults
  apply when omitted.

The orchestrator never modifies your original input files. It works on copies
under `.kiro/agent-state/cv-workflow/working/`, the only exception being a
writable (`.md`/`.txt`) bullet-point database, which the JD-alignment agent may
append to in place. On completion it writes a termination report summarizing the
tailored package, accepted gaps, any database writeback or sidecar location, and
the final per-document page counts.

---

## 4. Self-contained copy-then-install

The suite is portable. To use it in another workspace with no other files from
this repository:

1. Copy the entire `cli-agents/cv/` tree into the target location.
2. Complete the one-time environment setup (Section 1) on that machine, if not
   already done.
3. Run the installer from the copied tree:

   ```
   python cli-agents/cv/shared/install/install_agents.py --mode workspace --workspace-root /path/to/target/workspace
   ```

   The installer infers the authoring root from its own location, copies the
   tree to `<target>/.kiro/cv-suite/`, and generates the discovery configs under
   `<target>/.kiro/agents/`.
4. Start the workflow: `kiro-cli --agent cv-orchestrator`.

That copy-plus-install yields a fully working suite — no additional files from
this repository are required.

---

## 5. Layout

- `orchestrator/`, `editor/`, and the five `*-reviewer/` directories — one per
  agent: its `KiroCLIAgent-*.json` config, `prompt.md`, and
  `CLIAgent-<Name>Discussion.txt` notes.
- `shared/scripts/` — deterministic Python core the agents invoke:
  `docx_normalize.py`, `input_normalize.py`, `page_count.py`, `docx_edit.py`,
  `ats_structural.py`. Also `orchestrator_logic.py`, a tested reference
  implementation of the orchestrator's convergence/dedup/conflict/oscillation
  rules used only by the test suite (no agent runs it).
- `shared/schemas/` — JSON schemas: `finding.schema.json`,
  `change_list.schema.json`, `resume_state.schema.json`.
- `shared/install/` — `install_agents.py`.
- `tests/` — pytest suite and versioned `fixtures/`.
