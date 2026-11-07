# project-docs/ — documents installed verbatim into a set-up project's `docs/`

Unlike [`templates/`](../templates/) (files with placeholders that the setup prompt fills
in), everything here is copied **byte-for-byte** into the target project's `docs/`
directory. Both setup prompts install them:

- `ClaudeCodeSetupPrompt.txt` — Part 9 (Documentation)
- `KiroProjectSetupPrompt.v2.txt` — PART 12 (Documentation)

Installation happens on setup, migration, AND re-configuration of an existing project, so
a project that hits a CI capacity outage already has the implementation instructions on
disk — that is exactly the moment it cannot go and fetch them.

## Contents

| File | Read it for |
|---|---|
| `codebuild-ci-backup-mechanism.md` | How to BUILD a CI fallback onto CodeBuild-hosted ephemeral GitHub Actions runners, in any repository. Written from a working implementation, with placeholders for every name the project must choose (`<runner-project-name>`, `<mode-variable>`, `<fallback-token>`, …), a three-phase plan where each phase ships alone, the runner-label contract, the refusal classifier, the sizing arithmetic, and a verification checklist. Referenced by the `remote-ci-must-pass` capacity ladder, Rung 2. |

## Only project-agnostic documents belong here

The point of this directory is that **no project has to redesign the mechanism.** A
document earns a place here by being implementable in a repository that has never seen the
originating project — which means placeholders instead of names, and stated measurements
instead of local run ids.

The originating project's own operational runbook is deliberately **NOT** shipped. It
carries the same design but names that project's stack, repository, mode variable, issue
numbers, source paths and measured run ids; an agent following it literally elsewhere
would try to deploy a stack that does not exist. Its measured evidence is already folded
into the guide above as MEASURED claims, which is the part that transfers. A project that
builds the mechanism should write its own runbook for its own coordinates — the guide's
§12 checklist is the natural skeleton.

Before adding anything else here, check it against that bar: if it names a stack, an
account, a repository or an issue number, it is a project artifact, not a project-docs
document.

## Updating

`codebuild-ci-backup-mechanism.md` is a copy; the originating project's `docs/` holds the
live version and the two will drift. When the mechanism changes materially, re-copy and
say so in the commit — do not hand-patch one side. Verify on re-copy that the placeholder
discipline survived: a concrete stack or repository name appearing in the guide is a
regression, not an improvement.
