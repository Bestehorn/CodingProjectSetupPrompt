<!-- Installed to .claude/docs/ by the setup prompt (Part 12/13); the agent reads it at language setup time. -->

# Non-Python Language Matrix (dead-code-removal-agent)

Per-language tool-install, analysis, test-invocation, and uninstall rows for
the non-Python languages. The Python rows live inline in the agent
definition (the common case). Section numbers refer to the agent
definition's Discovery / Main Loop / Termination steps.

## JavaScript / TypeScript (if `src/` contains `.ts`/`.tsx`/`.js`/`.jsx`)

Dependency install strategy (Discovery Step 4):
  1. `package.json` + `pnpm-lock.yaml` → `pnpm add -D <pkg>`
  2. `package.json` + `yarn.lock` → `yarn add -D <pkg>`
  3. `package.json` + `package-lock.json` → `npm install --save-dev <pkg>`
  4. None detected → mode `TEMPORARY`: `npm install -g <pkg>` (or local
     install to a scratch directory) and record for uninstall

Required tools (Discovery Step 5):
  - `knip` — primary dead-code / unused-export detector (REQUIRED)
  - `ts-prune` — complementary unused-export detector for TS (REQUIRED for
    TypeScript projects)
  - `depcheck` — unused npm dependency detector (REQUIRED)
  - `madge` — dependency graph generator (REQUIRED)

Availability probe (Step 5.1): `<pkg-manager> list <pkg>` or
`npx --no-install <tool> --version`.

Analysis invocations (Main Loop Step 1): `knip`, `ts-prune`, `depcheck`,
`madge` via the recorded invocation pattern (`npx <tool>` or
`./node_modules/.bin/<tool>`).

Test invocation (Discovery Step 9):
  - Jest: `<pkg-manager> test -- --maxWorkers=50% --coverage`
  - Vitest: `<pkg-manager> test -- --reporter=default --coverage` (Vitest
    is threaded by default)
  - Mocha: `<pkg-manager> test` (add `--parallel` if the config does not
    already set it and the test base tolerates parallel; verify by running
    once sequentially and once parallel in the pre-flight and confirm
    identical results)

Uninstall of `TEMPORARY` installs (Termination Step 7.4):
`<pkg-manager> uninstall <pkg>` (if global: `npm uninstall -g`).

## Rust (if `Cargo.toml` is present)

Install strategy (Discovery Step 4): analysis tools (`cargo-udeps`,
`cargo-machete`) are binary subcommands, not project dependencies. Install
mode is always `GLOBAL_BINARY` via `cargo install <tool>`. Record in
`tool_install_manifest.md` for uninstall at termination if they were not
already present.

Required tools (Discovery Step 5):
  - `cargo-udeps` (nightly) OR `cargo-machete` (stable) — at least one is
    REQUIRED; prefer `cargo-machete` unless nightly is explicitly in
    `rust-toolchain`.
  - `cargo clippy` with `dead_code` lint enabled — REQUIRED (typically
    already present with rustup).

Availability probe (Step 5.1): `<tool> --version` or `which <tool>`.

Analysis invocations (Main Loop Step 1): `cargo-machete` (or
`cargo-udeps`), `cargo clippy -- -W dead_code`.

Test invocation (Discovery Step 9): `cargo test` (parallel by default;
test binaries use all cores unless `--test-threads=1` is configured).

Uninstall (Termination Step 7.4): `cargo uninstall <tool>` (only if the
tool was `GLOBAL_BINARY` and was not present before — verified by the
`PRESENT_ALREADY` flag in the manifest).

## Go (if `go.mod` is present)

Install strategy (Discovery Step 4): analysis tools (official `deadcode`,
`staticcheck`) are binaries. Install mode `GLOBAL_BINARY` via
`go install <tool>@latest`. Record for uninstall if not already present.

Required tools (Discovery Step 5):
  - `golang.org/x/tools/cmd/deadcode` — REQUIRED
  - `staticcheck` — REQUIRED

Availability probe (Step 5.1): `<tool> --version` or `which <tool>`.

Analysis invocations (Main Loop Step 1): `deadcode ./...`,
`staticcheck -checks U1000 ./...`.

Test invocation (Discovery Step 9): `go test ./... -parallel=$(nproc)`
(package-level parallelism; test functions within a package are parallel
if they call `t.Parallel()`).

Uninstall (Termination Step 7.4): `rm $(go env GOPATH)/bin/<tool>` (only
if not `PRESENT_ALREADY`).
