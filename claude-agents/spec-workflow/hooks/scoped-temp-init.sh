#!/usr/bin/env bash
# scoped-temp-init.sh — SessionStart hook. Guarantees this tree's scoped temp directory
# exists, so the TMPDIR/TEMP/TMP values set in .claude/settings.local.json are usable.
#
# WHY
#   Agent tooling leaks unbounded scratch into the SHARED OS temp directory: every `cdk`
#   invocation orphans a `jsii-kernel-*` directory that is never removed (aws/jsii#700),
#   randomized `cdk.out<hash>` cloud assemblies accumulate with nothing reused
#   (aws/aws-cdk-cli#802 — 170 GB in two days), and an aborted bundling leaves a
#   `bundling-temp-*`/empty `asset.<hash>` that makes the NEXT deploy fail
#   (aws/aws-cdk#33201). Pointing TMPDIR/TEMP/TMP at a per-tree directory turns all of
#   that from unattributable shared garbage into one directory this tree provably owns —
#   which is what makes cleanup safe while sibling sessions run concurrently.
#
#   The env values are static (a settings file cannot compute a path), so something must
#   ensure the directory EXISTS: Python's tempfile and Node's os.tmpdir() do not create a
#   missing TMPDIR, they fail or silently fall back to the global temp dir — which is the
#   leak returning unnoticed. This hook is that guarantee, and it is idempotent.
#
# WIRE IT (SessionStart, no matcher — every session, including resume and compact):
#   "SessionStart": [
#     { "hooks": [ { "type": "command", "command": "bash",
#                    "args": ["${CLAUDE_PROJECT_DIR}/.claude/hooks/scoped-temp-init.sh"] } ] }
#   ]
#
# Pairs with `.claude/settings.local.json` (per clone/worktree, gitignored):
#   { "env": { "TMPDIR": "<abs>/tmp/os-temp",
#              "TEMP":   "<abs>/tmp/os-temp",
#              "TMP":    "<abs>/tmp/os-temp" } }
#
# Silent on success: SessionStart stdout is injected as CONTEXT, so a chatty hook spends
# tokens every session for nothing. It speaks only when something is wrong.
set -u

proj="${CLAUDE_PROJECT_DIR:-.}"
scoped="$proj/tmp/os-temp"

mkdir -p "$scoped" 2>/dev/null || {
    echo "scoped-temp-init: could not create $scoped — TMPDIR/TEMP/TMP may point at a" >&2
    echo "missing directory, so tooling will fall back to the shared OS temp dir and its" >&2
    echo "residue will not be attributable to this tree. Create it or drop the env block." >&2
    exit 0   # SessionStart cannot block; never wedge a session over a temp dir
}

# Only speak up if the env block is absent or disagrees — that is the actionable case,
# because then the leak is silently back in the shared temp directory.
settings="$proj/.claude/settings.local.json"
configured=""
if [[ -f "$settings" ]] && command -v python >/dev/null 2>&1; then
    configured="$(python -c '
import json,sys
try:
    env = (json.load(open(sys.argv[1])) or {}).get("env") or {}
    print(env.get("TMPDIR") or env.get("TEMP") or env.get("TMP") or "")
except Exception:
    print("")
' "$settings" 2>/dev/null)"
fi

if [[ -z "$configured" ]]; then
    echo "Scoped temp is NOT configured for this tree: .claude/settings.local.json has no"
    echo "env TMPDIR/TEMP/TMP. Tooling will write into the shared OS temp directory, where"
    echo "jsii-kernel-* and cdk.out<hash> residue accumulates unattributably. Point them at"
    echo "$scoped (absolute path) to make it cleanable; /close-session reaps it."
fi

exit 0
