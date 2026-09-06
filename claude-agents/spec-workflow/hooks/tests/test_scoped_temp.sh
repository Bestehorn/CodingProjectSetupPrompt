#!/usr/bin/env bash
# Exercise scoped-temp-init.sh (SessionStart). The hook must NEVER exit non-zero and must
# self-write the settings.local.json env block when missing — that is the whole point: the
# block is per-tree (an absolute path), a manual step per clone/worktree was skipped in
# practice, and a notice nobody acts on is not a mechanism.
#
# The dangerous directions pinned here:
#   * it must never clobber a settings file it cannot parse, and never fight a custom
#     TMPDIR the user chose;
#   * it must MERGE — other top-level keys and other env vars survive the write;
#   * it must be silent when everything is already right (SessionStart stdout is context).
set -u

HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pass=0; fail=0

check() { # $1 label, $2 expected, $3 actual
    if [[ "$2" == "$3" ]]; then printf '  PASS  %-64s\n' "$1"; pass=$(( pass + 1 ))
    else printf '  FAIL  %-64s expected [%s], got [%s]\n' "$1" "$2" "$3"; fail=$(( fail + 1 )); fi
}

new_arena() {
    A="$(mktemp -d 2>/dev/null || echo "/tmp/scopedtemp.$$")"
    mkdir -p "$A/.claude"
}

run_hook() { # uses $A; prints "<rc>|<stdout>"
    local out rc
    out="$(CLAUDE_PROJECT_DIR="$A" bash "$HOOKS/scoped-temp-init.sh" 2>/dev/null)"
    rc=$?
    printf '%s|%s' "$rc" "$out"
}

json_env() { # $1 = var name -> prints value from the arena's settings file
    python -c '
import json,sys
try:
    print(((json.load(open(sys.argv[1])) or {}).get("env") or {}).get(sys.argv[2]) or "")
except Exception:
    print("")
' "$A/.claude/settings.local.json" "$1" 2>/dev/null
}

json_key() { # $1 = top-level key -> prints json-dumped value
    python -c '
import json,sys
try:
    print(json.dumps((json.load(open(sys.argv[1])) or {}).get(sys.argv[2])))
except Exception:
    print("PARSE-FAIL")
' "$A/.claude/settings.local.json" "$1" 2>/dev/null
}

echo "=============================================================================================="
echo "self-configuration — a missing block is WRITTEN, not merely announced"
echo "=============================================================================================="

new_arena
res="$(run_hook)"; rc="${res%%|*}"; out="${res#*|}"
check "no settings file: exit 0"                          0 "$rc"
case "$out" in *"takes effect"*"NEXT session"*) w=yes;; *) w=no;; esac
check "no settings file: announces next-session effect"   yes "$w"
check "settings file was created"                         yes "$([[ -f "$A/.claude/settings.local.json" ]] && echo yes || echo no)"
tmpdir_val="$(json_env TMPDIR)"
case "$tmpdir_val" in *os-temp) v=yes;; *) v=no;; esac
check "TMPDIR points at .../os-temp"                      yes "$v"
case "$tmpdir_val" in [A-Za-z]:*|/*) abs=yes;; *) abs=no;; esac
check "TMPDIR is an ABSOLUTE path"                        yes "$abs"
check "TEMP matches TMPDIR"                               "$tmpdir_val" "$(json_env TEMP)"
check "TMP matches TMPDIR"                                "$tmpdir_val" "$(json_env TMP)"
check "tmp/os-temp directory exists"                      yes "$([[ -d "$A/tmp/os-temp" ]] && echo yes || echo no)"

# Idempotence: the second run has nothing to do and nothing to say.
before="$(cat "$A/.claude/settings.local.json")"
res="$(run_hook)"; rc="${res%%|*}"; out="${res#*|}"
check "second run: exit 0"                                0 "$rc"
check "second run: SILENT (stdout is context)"            "" "$out"
check "second run: file byte-identical"                   "$before" "$(cat "$A/.claude/settings.local.json")"
rm -rf "$A"

echo ""
echo "=============================================================================================="
echo "merge semantics — never overwrite, never fight"
echo "=============================================================================================="

# Other top-level keys and other env vars survive the merge.
new_arena
printf '{"permissions":{"allow":["Bash(ls:*)"]},"env":{"FOO":"bar"}}' > "$A/.claude/settings.local.json"
res="$(run_hook)"
check "merge run: exit 0"                                 0 "${res%%|*}"
check "other top-level key survives"                      '{"allow": ["Bash(ls:*)"]}' "$(json_key permissions)"
check "other env var survives"                            bar "$(json_env FOO)"
case "$(json_env TMPDIR)" in *os-temp) v=yes;; *) v=no;; esac
check "TMPDIR added beside FOO"                           yes "$v"
rm -rf "$A"

# A custom TMPDIR is respected: silent, nothing written.
new_arena
printf '{"env":{"TMPDIR":"/my/custom/tempdir"}}' > "$A/.claude/settings.local.json"
before="$(cat "$A/.claude/settings.local.json")"
res="$(run_hook)"; out="${res#*|}"
check "custom TMPDIR: exit 0"                             0 "${res%%|*}"
check "custom TMPDIR: silent"                             "" "$out"
check "custom TMPDIR: file untouched"                     "$before" "$(cat "$A/.claude/settings.local.json")"
rm -rf "$A"

# A file that does not parse is NEVER touched.
new_arena
printf '{oops, not json' > "$A/.claude/settings.local.json"
before="$(cat "$A/.claude/settings.local.json")"
res="$(run_hook)"; rc="${res%%|*}"; out="${res#*|}"
check "malformed JSON: exit 0"                            0 "$rc"
case "$out" in *"not a valid"*"JSON"*|*"not a valid JSON"*) v=yes;; *) v=no;; esac
check "malformed JSON: says so instead of clobbering"     yes "$v"
check "malformed JSON: file byte-identical"               "$before" "$(cat "$A/.claude/settings.local.json")"
rm -rf "$A"

# A JSON array is an invalid settings shape: same never-touch rule.
new_arena
printf '[1,2,3]' > "$A/.claude/settings.local.json"
before="$(cat "$A/.claude/settings.local.json")"
res="$(run_hook)"; out="${res#*|}"
check "JSON-array settings: file byte-identical"          "$before" "$(cat "$A/.claude/settings.local.json")"
rm -rf "$A"

echo ""
echo "=============================================================================================="
echo "degraded hosts — no python still exits 0 and still speaks"
echo "=============================================================================================="

# python/python3 shims that fail: the hook must fall back to the notice, write nothing,
# and still exit 0.
new_arena
SHIM="$(mktemp -d 2>/dev/null || echo "/tmp/scopedshim.$$")"
printf '#!/usr/bin/env bash\nexit 9\n' > "$SHIM/python";  chmod +x "$SHIM/python"
printf '#!/usr/bin/env bash\nexit 9\n' > "$SHIM/python3"; chmod +x "$SHIM/python3"
out="$(CLAUDE_PROJECT_DIR="$A" PATH="$SHIM:$PATH" bash "$HOOKS/scoped-temp-init.sh" 2>/dev/null)"
rc=$?
check "broken python: exit 0"                             0 "$rc"
case "$out" in *settings.local.json*) v=yes;; *) v=no;; esac
check "broken python: notice names the settings file"     yes "$v"
check "broken python: nothing written"                    no "$([[ -f "$A/.claude/settings.local.json" ]] && echo yes || echo no)"
check "broken python: tmp/os-temp still created"          yes "$([[ -d "$A/tmp/os-temp" ]] && echo yes || echo no)"
rm -rf "$A" "$SHIM"

echo ""
printf 'TOTAL: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
