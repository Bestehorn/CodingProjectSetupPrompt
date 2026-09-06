#!/usr/bin/env bash
# scoped-temp-init.sh — SessionStart hook. Guarantees this tree's scoped temp directory
# exists AND that .claude/settings.local.json points TMPDIR/TEMP/TMP at it — writing the
# env block itself when it is missing, so no clone or worktree needs a manual setup step.
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
#   The env values are static (a settings file cannot compute a path) and PER TREE (the
#   value is that tree's absolute path), which made the block a manual step on every
#   clone and worktree — a step that was skipped in practice, leaving the leak in place
#   with only a notice announcing it (MEASURED: the first rollout project ran without the
#   block; nothing fails without it, so nothing forced the fix). This hook now closes the
#   loop itself: when no TMPDIR/TEMP/TMP is configured, it MERGES the env block into
#   settings.local.json (creating the file if absent), effective from the next session.
#   Python's tempfile and Node's os.tmpdir() do not create a missing TMPDIR — they fail
#   or silently fall back to the global temp dir — so the directory itself is also
#   created here, every session, idempotently.
#
# WIRE IT (SessionStart, no matcher — every session, including resume and compact):
#   "SessionStart": [
#     { "hooks": [ { "type": "command", "command": "bash",
#                    "args": ["${CLAUDE_PROJECT_DIR}/.claude/hooks/scoped-temp-init.sh"] } ] }
#   ]
#
# What it writes (per clone/worktree, gitignored; other keys and other env vars in the
# file are preserved — the block is MERGED, never overwritten):
#   { "env": { "TMPDIR": "<abs>/tmp/os-temp",
#              "TEMP":   "<abs>/tmp/os-temp",
#              "TMP":    "<abs>/tmp/os-temp" } }
#
# DECISIONS, so an edit does not regress them:
#   - If ANY of TMPDIR/TEMP/TMP is already configured, the hook stays silent and writes
#     NOTHING — a deliberate custom value is never fought.
#   - A settings.local.json that does not parse as a JSON object is NEVER touched; the
#     hook says so and leaves the repair to a human. Clobbering a hand-edited settings
#     file to fix a temp path would be a terrible trade.
#   - The write is atomic (temp file + os.replace) and the whole check-and-repair is ONE
#     python invocation — process spawns cost >1s on some measured hosts.
#   - Exit is ALWAYS 0: SessionStart cannot block, and a session must never wedge over a
#     temp dir.
#
# Silent when everything is already right: SessionStart stdout is injected as CONTEXT,
# so a chatty hook spends tokens every session for nothing. It speaks only when it wrote
# the block (one line, so the session knows the values arrive NEXT session) or when it
# could not (the actionable cases).
set -u

proj="${CLAUDE_PROJECT_DIR:-.}"
scoped="$proj/tmp/os-temp"

mkdir -p "$scoped" 2>/dev/null || {
    echo "scoped-temp-init: could not create $scoped — TMPDIR/TEMP/TMP may point at a" >&2
    echo "missing directory, so tooling will fall back to the shared OS temp dir and its" >&2
    echo "residue will not be attributable to this tree. Create it or drop the env block." >&2
    exit 0   # SessionStart cannot block; never wedge a session over a temp dir
}

settings="$proj/.claude/settings.local.json"

py=""
if command -v python >/dev/null 2>&1; then py=python
elif command -v python3 >/dev/null 2>&1; then py=python3
fi

if [[ -z "$py" ]]; then
    echo "Scoped temp: no python on PATH, so .claude/settings.local.json cannot be checked"
    echo "or written. Ensure its env block points TMPDIR/TEMP/TMP at $scoped (ABSOLUTE"
    echo "path), or tooling keeps writing into the shared OS temp directory."
    exit 0
fi

# One interpreter does the check AND the repair. First word of output is the verdict:
#   configured — a TMPDIR/TEMP/TMP is already set; nothing to do, nothing to say
#   wrote <path> — the env block was merged in; effective next session
#   invalid — the file exists but is not a JSON object; NOT touched
#   error: <detail> — anything else; NOT touched
out="$("$py" - "$settings" "$scoped" <<'PYEOF' 2>&1
import json, os, sys
settings_path, scoped = sys.argv[1], sys.argv[2]
try:
    data = {}
    if os.path.exists(settings_path):
        with open(settings_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            print("invalid")
            raise SystemExit(0)
    env = data.get("env")
    if not isinstance(env, dict):
        env = {}
    if env.get("TMPDIR") or env.get("TEMP") or env.get("TMP"):
        print("configured")
        raise SystemExit(0)
    target = os.path.abspath(scoped)
    for name in ("TMPDIR", "TEMP", "TMP"):
        env[name] = target
    data["env"] = env
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    tmp_path = settings_path + ".scoped-temp.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, settings_path)
    print("wrote " + target)
except SystemExit:
    raise
except json.JSONDecodeError:
    print("invalid")
except Exception as exc:
    print("error: %s" % exc)
PYEOF
)"

case "$out" in
    configured)
        : ;;   # already right — say nothing
    wrote\ *)
        echo "Scoped temp CONFIGURED: wrote the TMPDIR/TEMP/TMP env block into"
        echo ".claude/settings.local.json pointing at ${out#wrote } — it takes effect"
        echo "from the NEXT session; this session still uses the previous temp settings."
        ;;
    invalid)
        echo "Scoped temp NOT configured, and .claude/settings.local.json is not a valid"
        echo "JSON object — NOT touching it. Repair the file, or add the env block"
        echo "yourself: TMPDIR/TEMP/TMP -> $scoped (ABSOLUTE path)."
        ;;
    *)
        echo "Scoped temp NOT configured and the env block could not be written"
        echo "($out). Tooling will write into the shared OS temp directory, where"
        echo "jsii-kernel-* and cdk.out<hash> residue accumulates unattributably. Point"
        echo "TMPDIR/TEMP/TMP in .claude/settings.local.json at $scoped (ABSOLUTE path)."
        ;;
esac

exit 0
