# Push the repo.
#
# This used to pass `-c core.hooksPath=.git/hooks` on every invocation to
# bypass a system-level hooks directory (e.g. git-defender, which writes
# core.hooksPath into the SYSTEM gitconfig). That is now handled durably:
# `scripts/setup-hooks.sh` sets `core.hooksPath` in the repo's LOCAL config to
# the tracked `.githooks` directory, which overrides the system value for every
# git operation in this repo — so no per-command flag is needed.
#
# As a safety net for a fresh clone where setup-hooks.sh has not run yet, this
# script ensures the local override points at the tracked hooks before pushing.
if ((git config --local --get core.hooksPath) -ne '.githooks') {
    if (Test-Path '.githooks') {
        git config --local core.hooksPath '.githooks'
        Write-Host "push_repo: set local core.hooksPath -> .githooks"
    }
}
git push @args
