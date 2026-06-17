# Push the repo.
#
# This used to pass `-c core.hooksPath=.git/hooks` on every invocation to
# bypass a system-level hooks directory (e.g. git-defender, which writes
# core.hooksPath into the SYSTEM gitconfig). That is now handled durably:
# `scripts/setup-hooks.sh` sets `core.hooksPath` in the repo's LOCAL config
# (to an absolute .git/hooks path), which overrides the system value for
# every git operation in this repo — so no per-command flag is needed.
#
# As a safety net for a fresh clone where setup-hooks.sh has not run yet,
# this script ensures the local override is in place before pushing.
if (-not (git config --local --get core.hooksPath)) {
    $hooksDir = (Resolve-Path (Join-Path (git rev-parse --git-common-dir) 'hooks')).Path
    git config --local core.hooksPath $hooksDir
    Write-Host "push_repo: set local core.hooksPath -> $hooksDir"
}
git push @args
