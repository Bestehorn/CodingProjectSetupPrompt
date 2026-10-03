"""no-env-vars — PreToolUse(Bash) gate enforcing the no-environment-vars rule.

Blocks (exit 2) when the command SETS a shell environment variable this project forbids — AWS_* or
GH_TOKEN/GITHUB_TOKEN/GITLAB_TOKEN, in any letter case — through `export VAR=`, `setx VAR`, PowerShell
`$env:VAR =` or `set VAR=`. Reading
one is not blocked. Profiles and regions are resolved through the project's aws_config at session creation;
git-host tokens are read from project-local credential files by the wrapper. The `env` blocks in .mcp.json
and settings files are scoped subprocess configuration, not shell variables, and are unaffected.
"""

from __future__ import annotations

import re

import hooklib as lib

HOOK = "no-env-vars"
EVENT = "pre-tool-use"  # the dispatcher runs this gate on this event
ORDER = 10  # framework gates 10..90; a project gate takes >100 (or <10 to run first)
SHELL_TOOLS = {"Bash", "shell", "execute_bash", "execute_cmd", "executeBash"}
TOOLS = SHELL_TOOLS  # PreToolUse only: the tool names this gate judges

# The NAME is matched case-insensitively: Windows environment variable names are case-insensitive, so
# `export aws_profile=x` sets the real variable (16 of 117 rows in a measured command corpus were
# lower- or mixed-case). GH_TOKEN is the gh CLI's own name for the GitHub token.
FORBIDDEN = r"(?i:(AWS_[A-Z0-9_]+|GH_TOKEN|GITHUB_TOKEN|GITLAB_TOKEN))"
SETTERS = [
    re.compile(r"(^|[;&|\s])export\s+" + FORBIDDEN + r"\s*="),
    re.compile(r"(^|[;&|\s])setx\s+" + FORBIDDEN + r"(\s|=)"),
    re.compile(r"\$env:" + FORBIDDEN + r"\s*="),
    re.compile(r"(^|[;&|\s])set\s+" + FORBIDDEN + r"\s*="),
]


def run(ctx: lib.Context) -> lib.Decision:
    command = ctx.payload.command
    if not command:
        return lib.allow()
    if any(pattern.search(command) for pattern in SETTERS):
        return lib.block(
            f"{HOOK}: setting AWS_*/GH_TOKEN/GITHUB_TOKEN/GITLAB_TOKEN shell environment variables is forbidden "
            f"({ctx.host.rules_dir}/no-environment-vars.md). This system hosts multiple projects and shell env "
            "vars leak across them. Pass profile/region explicitly to boto3.Session(profile_name=...) / the AWS "
            "CLI (--profile/--region), and let the project's git wrapper read the token from its credentials file."
        )
    return lib.allow()
