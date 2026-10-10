# Native Tools Over Shell — a Bash call is the expensive tool (ALL agents, always loaded)

Governs HOW you touch files and wait for things. The model's work runs on the inference
side; what the local machine pays for is process creation, and a shell call is the one tool
that creates processes.

Why: a Bash call spawns a login shell of about 21 processes plus the hook dispatcher before
the command runs; the Read, Grep, Glob, Write and Edit tools spawn nothing and fire no hook.
(The 2026-10-01 measurement behind this rule is recorded in the setup prompt's 2026-10-03
changelog entry, not here.)

## The rule

- **Read a file with Read**, never `cat`, `head`, `tail`, `sed -n`, `type`. Read takes an
  offset and a limit, so a slice of a long file is Read too.
- **Search with Grep and Glob**, never `grep`/`rg`, `find`, `ls`. A directory listing is a
  Glob pattern; a text search is Grep with a path filter.
- **Write and edit with Write and Edit**, never `cat > file <<EOF`, `echo > file`, `sed -i`,
  `tee`. A heredoc is a shell write; the Write tool is not.
- **Bash is for executing**: tests, linters, git, the wrapper scripts, build and deploy tools.
  One Bash call carries a whole step (`a && b && c`), not one call per command, and a
  timestamp or a value a step needs is fetched in the same call that uses it, never alone.
- **Never `sleep` in a foreground call.** A pipeline is awaited with the wrapper's blocking
  `wait` as a background task; anything else is awaited by running THAT command with
  `run_in_background: true`. The `no-foreground-sleep` gate refuses a foreground wait of
  10 s or more and any sleep inside a loop (`parallel-by-default.md`).
- **Local suites go through `scripts/run_tests.py`**, which bounds its workers AND holds one
  of the host-wide suite slots (`scripts/suite_semaphore.py`) for any run wider than named
  test files; a CDK synth, `npm test` or a harness runs under
  `python scripts/suite_semaphore.py run -- <command>` (`ci-owns-the-test-suite.md`).

## Self-check before a Bash call

Does this command only read, search or write a file? Then it is a Read, Grep, Glob, Write or
Edit call. Does it wait? Then it runs in the background. Is it a suite or a synth? Then it goes
through the runner or the semaphore. Otherwise, chain the step into ONE call.
