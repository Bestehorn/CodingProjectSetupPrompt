"""hooklib.py — the ONE identity-and-state library every gate imports.

Standard library only, Python 3.9+. Installed as `.claude/hooks/hooklib.py` (Claude Code) and, through
`kiro_hooks.py`, as `.kiro/hooks-bin/hooklib.py` (Kiro CLI). The gates import it; nothing else does.

WHY PYTHON. The hooks were bash. Registered in exec form (`"command": "bash"`), the harness resolved `bash`
on the Windows PATH and found the WSL launcher alias, so on hosts without a WSL distribution every hook
exited 1 before its first line ran — a non-blocking error, invisible except in the transcript — and every
gate was inert (MEASURED: 399,278 of 400,015 recorded hook runs in one clone). A shell-form registration
would have fixed the resolution but would have made every gate depend on a Git Bash installation and pay
its start-up cost; `jq` was absent on every measured host, and the shell fallbacks could not read a command
containing a quote (99.5 percent of commands). Python is already a dependency of every project the
framework sets up, resolves on PATH on every machine, parses JSON correctly, and starts in a fraction of a
second. Each event now runs ONE interpreter for all of its gates (`hooks.py <event>`).

DESIGN RULES, each from a measured incident (the record is MIGRATION.md):
  1. IDENTITY IS SESSION-DERIVED, NEVER MTIME-DERIVED. No rung of `resolve_run_dir` looks at modification
     times; a hook must never borrow the most recently touched run's state.
  2. AN UNRESOLVABLE IDENTITY IS A VERDICT, NOT A SHRUG. `UNREGISTERED` (an ordinary session: gates are
     no-ops) is distinct from `BROKEN` (a registered run with no state: gates fail CLOSED).
  3. THE PAYLOAD IS PARSED ONCE, AS JSON. There is no pattern-matching fallback that stops at a quote.
  4. EVERY STATE FIELD IS THE LAST PLAIN `Name: value` LINE OUTSIDE A FENCE, trimmed, case-insensitive.
     A bold `**Name:**` spelling is invisible by design.
  5. A GATE THAT CANNOT COUNT ITS BLOCKS MUST NOT BLOCK: the counter is the bounded escape.

`selftest()` is deliberately the last definition in this file: a caller that can call it imported the whole
module, so a truncated copy fails closed in the gates that must fail closed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------------------------------------
# Constants. Callers may rely on these names and on the functions below; nothing else.
# ---------------------------------------------------------------------------------------------------------

ORCHESTRATOR_DIRNAME = "issue-work-orchestrator"
SINGLETON_DIRNAME = "spec-conductor"
STATE_FILENAME = "workflow_state.md"
RESUME_FILENAME = "resume_state.md"

OWNED = "OWNED"  # a session-keyed run directory with a resume_state.md
UNREGISTERED = "UNREGISTERED"  # not an orchestrator/spec run at all -> gates are no-ops
BROKEN = "BROKEN"  # registered as a run, but its state file is MISSING -> fail closed

# Wider than the four canonical words because the test is WHOLE-VALUE, and a whole-value test against a
# narrow vocabulary refuses an agent for its choice of synonym (measured: COMPLETE and FINISHED refused).
TERMINAL_PHASES = frozenset(
    {
        "DONE",
        "COMPLETE",
        "COMPLETED",
        "FINISHED",
        "CLOSED",
        "ABANDONED",
        "ESCALATED",
        "CANCELLED",
        "CANCELED",
    }
)
# Statuses that affirmatively mean "not begun". Anything outside this set and the terminal set is work in
# flight — inverted polarity on purpose: a novel status costs a visible refusal, not a silent fail-open.
IDLE_STATUSES = frozenset(
    {
        "NOT_STARTED",
        "NOT_YET_STARTED",
        "UNSTARTED",
        "NOT_IN_PROGRESS",
        "NOT_WORKING",
        "IDLE",
        "PENDING",
        "NEW",
        "NONE",
        "UNSET",
    }
)
PLACEHOLDERS = frozenset(
    {
        "none",
        "-",
        "--",
        "n/a",
        "na",
        "unset",
        "unknown",
        "empty",
        "null",
        "nil",
        "tbd",
        "todo",
        "pending",
        "placeholder",
        "xxx",
    }
)
NON_REASONS = frozenset(
    {
        "no",
        "false",
        "0",
        "1",
        "true",
        "yes",
        "y",
        "n",
        "?",
        "??",
        "waiting",
        "blocked",
        "ask",
        "question",
    }
)
MIN_ESCALATION_REASON = 12
DEFAULT_BLOCK_CAP = 8

IMPLEMENTATION_PHASE_RE = re.compile(r"^(IMPLEMENT(_.*)?|IMPLEMENTING|VERIFY(_.*)?|VERIFYING)$")
CLAIMING_MODE_RE = re.compile(r"^(ISSUE_LOOP|SINGLE_ISSUE|SPEC|BACKLOG|AUTO)", re.IGNORECASE)

# Runner-summary predicates, anchored on a NON-ZERO COUNTER, never a bare word: a test NAMED
# `test_reports_skipped_reason` is not a skip, and `0 failed` is not a failure.
FAILURE_RE = re.compile(r"[1-9][0-9]* (failed|failure|failures|error|errors)\b", re.IGNORECASE)
SKIP_RE = re.compile(r"[1-9][0-9]* (skipped|xfailed|xfail|xpassed|deselected)\b", re.IGNORECASE)
PASS_RE = re.compile(
    r"[1-9][0-9]* passed|passed in |^OK$|all tests passed|[1-9][0-9]* tests? ok",
    re.IGNORECASE | re.MULTILINE,
)
CHECKED_TASK_RE = re.compile(r"^\s*-\s*\[[xX]\]\s*(\d+(?:\.\d+)*)")
CHECKED_LINE_RE = re.compile(r"^\s*-\s*\[[xX]\]")
COMMENT_LINE_RE = re.compile(r"^\s*#")
WAVE_HEADER_RE = re.compile(r"^\s*#\s*tasks\s*:(.*)$", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s*(```|~~~)")
FIELD_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")
RUNS_RELATIVE_RE = re.compile(r"^runs/")


# ---------------------------------------------------------------------------------------------------------
# Hosts. The same gates serve Claude Code and Kiro; only the paths and the block conventions differ.
# ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Host:
    name: str
    config_dir: str  # ".claude" | ".kiro"
    project_dir_env: str  # the env var the harness exports with the project root
    rules_dir: str  # where the always-loaded rules live, for messages
    hooks_dir: str  # where the hooks are installed, for messages
    block_cap_env: str


CLAUDE = Host(
    name="claude",
    config_dir=".claude",
    project_dir_env="CLAUDE_PROJECT_DIR",
    rules_dir=".claude/rules",
    hooks_dir=".claude/hooks",
    block_cap_env="CLAUDE_CODE_STOP_HOOK_BLOCK_CAP",
)
KIRO = Host(
    name="kiro",
    config_dir=".kiro",
    project_dir_env="KIRO_PROJECT_DIR",
    rules_dir=".kiro/steering",
    hooks_dir=".kiro/hooks-bin",
    block_cap_env="KIRO_STOP_BLOCK_CAP",
)


# ---------------------------------------------------------------------------------------------------------
# The payload. Parsed ONCE, as JSON. Never raises: an unparseable payload is an EMPTY payload.
# ---------------------------------------------------------------------------------------------------------


@dataclass
class Payload:
    raw: str = ""
    data: Dict[str, object] = field(default_factory=dict)

    @classmethod
    def parse(cls, text: str) -> "Payload":
        try:
            parsed = json.loads(text) if text and text.strip() else {}
        except Exception:  # noqa: BLE001 — any malformed payload reads as empty, by design
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        return cls(raw=text or "", data=parsed)

    def string(self, key: str) -> str:
        value = self.data.get(key)
        if isinstance(value, str):
            return value.replace("\r", "")
        if isinstance(value, bool):
            return "true" if value else "false"
        return ""

    @property
    def session_id(self) -> str:
        return self.string("session_id").strip()

    @property
    def cwd(self) -> str:
        return self.string("cwd")

    @property
    def source(self) -> str:
        return self.string("source")

    @property
    def event(self) -> str:
        return self.string("hook_event_name")

    @property
    def tool_name(self) -> str:
        return self.string("tool_name")

    @property
    def command(self) -> str:
        """The Bash/shell command of a PreToolUse payload, read from `tool_input.command`.

        Carriage returns are stripped so a CR before a line break (a Windows artefact) cannot change a
        decision. A non-string value — a payload shape this gate family does not know — reads as EMPTY and is
        therefore ALLOWED by every command gate: fail open on an unknown shape, by design."""
        tool_input = self.data.get("tool_input")
        if isinstance(tool_input, dict):
            value = tool_input.get("command")
            if isinstance(value, str):
                return value.replace("\r", "")
        return ""


# ---------------------------------------------------------------------------------------------------------
# Small pure predicates.
# ---------------------------------------------------------------------------------------------------------


def is_placeholder(value: Optional[str]) -> bool:
    """True when the value means "nothing recorded here": empty, a `<token>` template, or a known filler."""
    text = (value or "").strip()
    if not text:
        return True
    if text.startswith("<") and text.endswith(">"):
        return True
    return text.lower() in PLACEHOLDERS


def is_substantive_escalation(value: Optional[str]) -> bool:
    """True when AWAITING_USER names a real reason. It is a self-issued permission slip, so a placeholder, a
    one-word token or anything shorter than MIN_ESCALATION_REASON characters does not count."""
    text = (value or "").strip()
    if is_placeholder(text):
        return False
    if text.lower() in NON_REASONS:
        return False
    return len(text) >= MIN_ESCALATION_REASON


def status_is_idle(status: Optional[str]) -> bool:
    text = (status or "").strip().upper()
    return not text or text in IDLE_STATUSES


def phase_is_terminal(value: Optional[str]) -> bool:
    return (value or "").strip().upper() in TERMINAL_PHASES


def is_implementation_phase(phase: Optional[str]) -> bool:
    """IMPLEMENT/VERIFY as WHOLE WORDS (with an underscore suffix allowed), case-insensitive. The substring
    form treated NOT_IMPLEMENTED and PRE_IMPLEMENT_REVIEW as implementation phases."""
    return bool(IMPLEMENTATION_PHASE_RE.match((phase or "").strip().upper()))


def normalize_verdict(verdict: Optional[str]) -> str:
    """Any unrecognised verdict becomes BROKEN (fail closed)."""
    return verdict if verdict in (OWNED, UNREGISTERED, BROKEN) else BROKEN


def resolve_block_cap(raw: Optional[str]) -> int:
    """A validated integer in [1, 64]; a typo or an empty value yields the default rather than disabling."""
    cap = DEFAULT_BLOCK_CAP
    if raw is not None and re.fullmatch(r"[0-9]+", raw.strip() or "x"):
        cap = int(raw.strip())
    return max(1, min(64, cap))


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------------------------------------
# State files: `Name: value` lines, LAST occurrence wins, fences ignored, bold invisible, trimmed.
# ---------------------------------------------------------------------------------------------------------


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_state(text: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    fence = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if FENCE_RE.match(line):
            fence = not fence
            continue
        if fence:
            continue
        idx = line.find(":")
        if idx <= 0:
            continue
        key = line[:idx]
        # Strip at most ONE leading list/emphasis marker, so `**Name:**` stays unmatched.
        key = re.sub(r"^\s*[*-]?\s*", "", key, count=1).rstrip()
        if not FIELD_KEY_RE.match(key):
            continue
        fields[key.upper()] = line[idx + 1 :].strip()
    return fields


class StateCache:
    """Per-process, per-file cache of parsed state. A hook reads six to eight fields of one file."""

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, str]] = {}

    def fields(self, path: Optional[Path]) -> Dict[str, str]:
        if path is None:
            return {}
        key = str(path)
        if key not in self._cache:
            self._cache[key] = parse_state(read_text(path)) if path.is_file() else {}
        return self._cache[key]

    def field(self, path: Optional[Path], name: str) -> str:
        return self.fields(path).get(name.upper(), "")


# ---------------------------------------------------------------------------------------------------------
# Registry and run resolution. Session-keyed rungs only. No mtime rung, ever.
# ---------------------------------------------------------------------------------------------------------


def registry_lookup(registry: Path, session: str) -> Tuple[Optional[str], str]:
    """-> ("HAS", state_dir) when the session has an entry, ("MISS", "") when it provably has none, and
    (None, "") when the registry cannot be read. The three answers are distinct on purpose: an unreadable
    registry must not read as "unregistered"."""
    if not session or not registry.is_file():
        return ("MISS", "") if registry.is_file() else (None, "")
    try:
        data = json.loads(read_text(registry) or "{}")
    except Exception:  # noqa: BLE001
        return (None, "")
    if not isinstance(data, dict):
        return (None, "")
    if session not in data:
        return ("MISS", "")
    entry = data.get(session)
    state_dir = entry.get("state_dir") if isinstance(entry, dict) else None
    return ("HAS", state_dir if isinstance(state_dir, str) else "")


def find_run_dir_by_session(base: Path, session: str) -> Optional[Path]:
    """The runs/*/ whose resume_state.md records this SESSION_ID — the repair rung for an agent that wrote its
    state under an invented directory name. Still session-derived, so it can only return this session's own."""
    runs = base / ORCHESTRATOR_DIRNAME / "runs"
    if not session or not runs.is_dir():
        return None
    pattern = re.compile(
        r"^\s*SESSION_ID\s*:\s*" + re.escape(session) + r"\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    try:
        candidates = sorted(runs.iterdir())
    except OSError:
        return None
    for run_dir in candidates:
        state = run_dir / RESUME_FILENAME
        if state.is_file() and pattern.search(read_text(state)):
            return run_dir
    return None


def resolve_run_dir(base: Path, session: str) -> Tuple[str, Optional[Path]]:
    """-> (verdict, run_dir). Rungs, all session-keyed: the registry's declared state_dir; runs/<sid8>/; a
    runs/*/ recording this SESSION_ID. A registered session that resolves nothing is BROKEN."""
    orch = base / ORCHESTRATOR_DIRNAME
    answer, declared = registry_lookup(orch / "registry.json", session)
    registered = answer == "HAS"
    if answer is None and session:
        # The registry could not be parsed. An unreadable registry must not read as "no entry": if this
        # session's id appears as a KEY in the raw text, the session IS a registered run whose state cannot be
        # resolved — BROKEN, which fails closed — rather than an ordinary session the gates ignore.
        registered = bool(re.search(r'"' + re.escape(session) + r'"\s*:', read_text(orch / "registry.json")))
    # A declared state_dir must name a run INSIDE the orchestrator subtree.
    if not RUNS_RELATIVE_RE.match(declared) or ".." in declared:
        declared = ""
    declared = declared.rstrip("/")
    if declared and (orch / declared / RESUME_FILENAME).is_file():
        return OWNED, orch / declared
    if session and (orch / "runs" / session[:8] / RESUME_FILENAME).is_file():
        return OWNED, orch / "runs" / session[:8]
    found = find_run_dir_by_session(base, session)
    if found is not None:
        return OWNED, found
    if registered:
        return BROKEN, orch / (declared or f"runs/{session[:8]}")
    return UNREGISTERED, None


def resolve_owned_state_file(base: Path, session: str, states: StateCache) -> Optional[Path]:
    """The workflow_state.md this session owns, or None. Keyed on whether the run's own state DECLARES a spec;
    the documented single-run `spec-conductor/workflow_state.md` is the only fallback, and it is a FIXED path."""
    verdict, run_dir = resolve_run_dir(base, session)
    singleton = base / SINGLETON_DIRNAME / STATE_FILENAME
    if verdict == OWNED and run_dir is not None:
        own = run_dir / STATE_FILENAME
        if own.is_file() and not is_placeholder(states.field(own, "CURRENT_SPEC")):
            return own
        if singleton.is_file() and not is_placeholder(states.field(singleton, "CURRENT_SPEC")):
            return singleton
        return own if own.is_file() else None
    if verdict == UNREGISTERED and singleton.is_file():
        return singleton
    return None


def owned_workflow_missing(base: Path, session: str) -> bool:
    verdict, run_dir = resolve_run_dir(base, session)
    return verdict == OWNED and run_dir is not None and not (run_dir / STATE_FILENAME).is_file()


# ---------------------------------------------------------------------------------------------------------
# Contract version, acknowledgements, revision notice, framework freshness.
# ---------------------------------------------------------------------------------------------------------


def _safe_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


def contract_version(project_dir: Path, host: Host = CLAUDE) -> str:
    path = project_dir / host.hooks_dir / "CONTRACT_VERSION"
    first = read_text(path).splitlines()[0] if path.is_file() and read_text(path).strip() else ""
    return re.sub(r"\s+", "", first) or "unversioned"


def contract_ack_file(run_dir: Path, version: str) -> Path:
    return run_dir / f"contract-ack-{_safe_token(version)}"


def contract_acknowledged(run_dir: Optional[Path], version: str) -> bool:
    if run_dir is None:
        return True  # nothing to migrate for a session with no run
    return contract_ack_file(run_dir, version).is_file()


def framework_ack_file(run_dir: Path, version: str) -> Path:
    return run_dir / f"framework-ack-{_safe_token(version)}"


def revision_notice(hooks_dir: Path, today: Optional[str] = None) -> Optional[str]:
    """The body of REVISION_NOTICE.md while its optional `Valid-until: YYYY-MM-DD` line has not passed."""
    path = hooks_dir / "REVISION_NOTICE.md"
    if not path.is_file():
        return None
    lines = read_text(path).replace("\r", "").split("\n")
    until = ""
    for line in lines[:3]:
        if line.lower().startswith("valid-until:"):
            until = line.split(":", 1)[1].strip()
            break
    if until and (today or today_iso()) > until:
        return None
    body = "\n".join(line for line in lines if not line.lower().startswith("valid-until:"))
    return body.strip("\n") + "\n"


def _git(args: List[str], cwd: Path, stdin: Optional[str] = None, timeout: float = 10.0) -> Optional[str]:
    try:
        completed = subprocess.run(  # nosec B603 B607 — git, fixed argv, no shell
            ["git", *args],
            cwd=str(cwd),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout if completed.returncode == 0 else None


def framework_stale(project_dir: Path, local_version: str, host: Host = CLAUDE) -> Optional[Tuple[str, str]]:  # noqa: C901 — one pass over the batch output
    """-> ("<remote>/<branch>", version) when a FETCHED trunk carries a newer CONTRACT_VERSION than this
    checkout. Reads local tracking refs only (no network); scans every remote, because a project may push to
    `gitlab` and keep `origin` as a frozen archive. The trunk of a remote is what its `HEAD` symref names
    (`refs/remotes/<remote>/HEAD`, written by clone and by `git remote set-head`); only a remote WITHOUT that
    symref falls back to `main` then `master`. The object spec goes to `cat-file --batch` on STDIN, so no
    shell can rewrite a `ref:path` argument. THREE git calls, whatever the number of remotes: a Stop event
    pays this on every turn-end of a working run, and one git start costs about half a second on a measured
    Windows host."""
    if _git(["rev-parse", "--git-dir"], project_dir) is None:
        return None
    listing = _git(["for-each-ref", "--format=%(refname) %(symref)", "refs/remotes"], project_dir) or ""
    heads: Dict[str, str] = {}
    present: Set[str] = set()
    for line in listing.splitlines():
        parts = line.split()
        if not parts:
            continue
        present.add(parts[0])
        if parts[0].endswith("/HEAD") and len(parts) > 1:
            heads[parts[0][: -len("/HEAD")]] = parts[1]
    remotes = {r.split("/")[2] for r in present if r.count("/") >= 3}
    refs: List[str] = []
    for remote in sorted(remotes):
        prefix = f"refs/remotes/{remote}"
        if prefix in heads:
            refs.append(heads[prefix])
            continue
        for branch in ("main", "master"):
            if f"{prefix}/{branch}" in present:
                refs.append(f"{prefix}/{branch}")
                break
    if not refs:
        return None
    local = "" if local_version == "unversioned" else local_version
    spec = "".join(f"{ref}:{host.hooks_dir}/CONTRACT_VERSION\n" for ref in refs)
    lines = (_git(["cat-file", "--batch"], project_dir, stdin=spec) or "").splitlines()
    # Batch output: per spec either `<spec> missing` or `<sha> blob <size>` followed by the blob's lines.
    versions: Dict[str, str] = {}
    i = 0
    order = 0
    while i < len(lines):
        header = lines[i].split()
        i += 1
        if len(header) == 3 and header[1] == "blob":
            value = lines[i].strip() if i < len(lines) else ""
            size = int(header[2]) if header[2].isdigit() else 0
            consumed = 0
            while i < len(lines) and consumed < size:
                consumed += len(lines[i].encode("utf-8")) + 1
                i += 1
            if i < len(lines) and lines[i] == "":
                i += 1
            if order < len(refs):
                versions[refs[order]] = value
        order += 1
    best: Optional[Tuple[str, str]] = None
    for ref in refs:
        remote_version = versions.get(ref, "")
        if remote_version and remote_version > local and (best is None or remote_version > best[1]):
            best = (ref[len("refs/remotes/") :], remote_version)
    return best


FRAMEWORK_STALE_CACHE = ".framework-stale.json"


def _git_common_dir_noexec(project_dir: Path) -> Optional[Path]:
    """The repository's common git dir resolved from `.git` WITHOUT spawning git: the `.git` directory, or
    the `gitdir: <path>` file of a worktree (whose `commondir` file points back at the shared repository).
    None when project_dir is not itself the top of a checkout; the caller then takes the uncached path."""
    dot = project_dir / ".git"
    if dot.is_dir():
        gitdir = dot
    elif dot.is_file():
        text = read_text(dot).strip()
        if not text.startswith("gitdir:"):
            return None
        gitdir = Path(text[len("gitdir:") :].strip())
        if not gitdir.is_absolute():
            gitdir = project_dir / gitdir
    else:
        return None
    common = gitdir
    pointer = gitdir / "commondir"
    if pointer.is_file():
        rel = read_text(pointer).strip()
        if rel:
            common = Path(rel) if Path(rel).is_absolute() else gitdir / rel
    return common if common.is_dir() else None


def refs_fingerprint(project_dir: Path) -> Optional[str]:
    """A digest of everything the freshness check reads — `packed-refs` and the loose files under
    `refs/remotes/` — computed with NO process spawned. It changes exactly when a fetch (or an update-ref)
    changes what `framework_stale` would read, so an answer cached under it is never stale."""
    common = _git_common_dir_noexec(project_dir)
    if common is None:
        return None
    digest = hashlib.sha1()  # a change detector, not a security boundary
    try:
        packed = common / "packed-refs"
        if packed.is_file():
            digest.update(b"packed-refs\0")
            digest.update(packed.read_bytes())
        remotes = common / "refs" / "remotes"
        if remotes.is_dir():
            for root, dirs, files in os.walk(str(remotes)):
                dirs.sort()
                for name in sorted(files):
                    path = Path(root) / name
                    digest.update(path.relative_to(remotes).as_posix().encode("utf-8") + b"\0")
                    digest.update(path.read_bytes())
    except OSError:
        return None
    return digest.hexdigest()


def framework_stale_cached(
    project_dir: Path, local_version: str, host: Host = CLAUDE, cache_dir: Optional[Path] = None
) -> Optional[Tuple[str, str]]:
    """`framework_stale`, answered from `<cache_dir>/.framework-stale.json` while nothing it reads has changed.
    Measured: the three git calls cost about 1.5 s of a loaded Windows host per Stop event, 485 turn-ends a
    day across one machine's sessions, for an answer that changes only when a fetch moves a tracking ref.
    The key is the refs fingerprint plus the checkout's own version and the hooks dir, so a moved ref, a
    bumped CONTRACT_VERSION or another host all miss. Without a fingerprint (not a checkout root) or a cache
    dir, this IS the uncached call."""
    fingerprint = refs_fingerprint(project_dir)
    if fingerprint is None or cache_dir is None:
        return framework_stale(project_dir, local_version, host)
    key = {"fingerprint": fingerprint, "hooks_dir": host.hooks_dir, "local": local_version}
    cache = cache_dir / FRAMEWORK_STALE_CACHE
    try:
        data = json.loads(read_text(cache) or "{}")
    except ValueError:
        data = {}
    if isinstance(data, dict) and data.get("key") == key:
        cached = data.get("result")
        if isinstance(cached, list) and len(cached) == 2:
            return (str(cached[0]), str(cached[1]))
        return None
    result = framework_stale(project_dir, local_version, host)
    write_json_atomic(cache, {"key": key, "result": list(result) if result else None, "checked_at": utc_stamp()})
    return result


def counter_path(base: Path, name: str, session: str) -> Path:
    return base / ORCHESTRATOR_DIRNAME / ".stop-gate-counters" / f"{name}-{session[:8]}.count"


def counter_read(counter: Path) -> int:
    """An integer, 0 when absent or unreadable, clamped to four digits so a corrupted file reads as 'cap
    reached' (stand down, saying the work is not done) rather than wedging the session."""
    digits = re.sub(r"[^0-9]", "", read_text(counter)) if counter.is_file() else ""
    if not digits:
        return 0
    return 9999 if len(digits) > 4 else int(digits)


def counter_bump(counter: Path) -> bool:
    """True when the increment LANDED. A caller that cannot count its blocks must not block."""
    current = counter_read(counter)
    try:
        counter.parent.mkdir(parents=True, exist_ok=True)
        counter.write_text(str(current + 1), encoding="utf-8")
    except OSError:
        return False
    return counter_read(counter) == current + 1


def counter_reset(counter: Path) -> None:
    for suffix in ("", ".capped", ".fingerprint"):
        try:
            Path(str(counter) + suffix).unlink()
        except OSError:
            pass


def counter_mark_capped(counter: Path) -> bool:
    try:
        counter.parent.mkdir(parents=True, exist_ok=True)
        Path(str(counter) + ".capped").write_text("capped\n", encoding="utf-8")
    except OSError:
        return False
    return True


def counter_is_capped(counter: Path) -> bool:
    return Path(str(counter) + ".capped").is_file()


def counter_note_progress(counter: Path, fingerprint: str) -> bool:
    """True when the fingerprint CHANGED since the last observation (a first observation is not progress)."""
    marker = Path(str(counter) + ".fingerprint")
    previous = read_text(marker) if marker.is_file() else ""
    if previous == fingerprint:
        return False
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(fingerprint, encoding="utf-8")
    except OSError:
        return False
    return bool(previous)


def decision_log(base: Path, name: str, decision: str, detail: str) -> None:
    """One line per invocation, to a FILE: observability without touching the stderr contract."""
    log_dir = base / ORCHESTRATOR_DIRNAME / ".hook-decisions"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = utc_stamp()
        with (log_dir / f"{stamp[:10]}.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}\t{name}\t{decision}\t{detail}\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------------------
# Evidence: captures, task ids, runner summaries.
# ---------------------------------------------------------------------------------------------------------


def capture_for_task(spec_dir: Path, kind: str, task_id: str) -> Optional[Path]:
    """The capture covering a task: `evidence/<kind>/<id>.txt`, or a WAVE capture whose first five lines
    carry `# tasks: <id> <id> ...` naming it (whole tokens: `1.1` never covers `1.10`; commas separate)."""
    own = spec_dir / "evidence" / kind / f"{task_id}.txt"
    if own.is_file():
        return own
    folder = spec_dir / "evidence" / kind
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob("*.txt")):
        head = read_text(path).replace("\r", "").split("\n")[:5]
        for line in head:
            match = WAVE_HEADER_RE.match(line)
            if match:
                tokens = match.group(1).replace(",", " ").split()
                if task_id in tokens:
                    return path
                break
    return None


def capture_body(path: Path) -> str:
    """The capture with COMMENT lines removed — an agent's own `# earlier this run: 3 failed` annotation is
    not a runner summary."""
    return "\n".join(line for line in read_text(path).splitlines() if not COMMENT_LINE_RE.match(line))


def has_failures(text: str) -> bool:
    return bool(FAILURE_RE.search(text))


def has_skips(text: str) -> bool:
    return bool(SKIP_RE.search(text))


def has_pass_marker(text: str) -> bool:
    return bool(PASS_RE.search(text))


def latest_capture(spec_dir: Path, kind: str) -> Optional[Path]:
    folder = spec_dir / "evidence" / kind
    if not folder.is_dir():
        return None
    captures = [p for p in folder.glob("*.txt") if p.is_file()]
    if not captures:
        return None
    return max(captures, key=lambda p: p.stat().st_mtime)


def evidence_fingerprint(spec_dir: Path) -> str:
    """Name and size of every capture: new evidence changes it, re-running the same turn does not."""
    parts: List[str] = []
    evidence = spec_dir / "evidence"
    if evidence.is_dir():
        for path in sorted(evidence.glob("*/*.txt")):
            try:
                parts.append(f"{path.stat().st_size} {path.as_posix()}")
            except OSError:
                continue
    return ";".join(parts)


def checked_task_ids(tasks_md: Path) -> Tuple[List[str], List[str]]:
    """-> (ids of checked tasks, checked lines whose id cannot be parsed). Bold markers are stripped first.
    An unparseable checked line is a PROBLEM for the caller, never a free pass."""
    ids: List[str] = []
    unparseable: List[str] = []
    for line in read_text(tasks_md).splitlines():
        if not CHECKED_LINE_RE.match(line):
            continue
        stripped = line.replace("**", "")
        match = CHECKED_TASK_RE.match(stripped)
        if match:
            ids.append(match.group(1))
        else:
            unparseable.append(line.rstrip("\r"))
    return ids, unparseable


def is_heading_id(task_id: str, all_ids: Iterable[str]) -> bool:
    """A parent heading: some other checked id extends it with a further dotted component."""
    prefix = task_id + "."
    return any(other.startswith(prefix) for other in all_ids)


# ---------------------------------------------------------------------------------------------------------
# Commands: classification helpers shared by the PreToolUse gates.
# ---------------------------------------------------------------------------------------------------------


def strip_quoted(command: str) -> str:
    """The command with quoted strings REMOVED, so `git commit -m "prepare for push"` is not a push."""
    return re.sub(r"'[^']*'", "", re.sub(r'"[^"]*"', "", command))


GIT_COMMIT_RE = re.compile(r"(^|[;&| ])git\s+([^;&|]*\s)?commit(\s|$)")
GIT_PUSH_RE = re.compile(r"(^|[;&| ])git\s+([^;&|]*\s)?push(\s|$)")
STASH_PUSH_RE = re.compile(r"stash\s+push")


def is_git_commit(stripped: str) -> bool:
    return bool(GIT_COMMIT_RE.search(stripped))


def is_git_push(stripped: str) -> bool:
    return bool(GIT_PUSH_RE.search(stripped)) and not STASH_PUSH_RE.search(stripped)


def python_interpreter(project_dir: Path) -> Optional[str]:
    """A project venv interpreter when present, else the running interpreter."""
    for candidate in (
        project_dir / "venv" / "Scripts" / "python.exe",
        project_dir / "venv" / "bin" / "python",
    ):
        if candidate.is_file():
            return str(candidate)
    return sys.executable or None


def write_json_atomic(path: Path, data: object) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False)
        try:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        finally:
            handle.close()
        os.replace(handle.name, str(path))
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------------------------------------
# The per-invocation context: where the project is, where state lives, the parsed payload, the caches.
# ---------------------------------------------------------------------------------------------------------


class Context:
    def __init__(
        self,
        payload: Payload,
        host: Host = CLAUDE,
        environ: Optional[Dict[str, str]] = None,
        hooks_dir: Optional[Path] = None,
        cwd: Optional[Path] = None,
    ) -> None:
        self.payload = payload
        self.host = host
        self.environ = dict(os.environ if environ is None else environ)
        self.hooks_dir = hooks_dir or Path(__file__).resolve().parent
        self.process_cwd = cwd or Path.cwd()
        self.states = StateCache()
        self._project_dir: Optional[Path] = None
        self._state_base: Optional[Path] = None
        self._resolved: Dict[str, Tuple[str, Optional[Path]]] = {}

    @property
    def session_id(self) -> str:
        return self.payload.session_id

    def _candidates(self, with_git: bool) -> Iterable[Path]:
        env_dir = self.environ.get(self.host.project_dir_env, "")
        if env_dir and Path(env_dir).is_dir():
            yield Path(env_dir)
        if self.payload.cwd and Path(self.payload.cwd).is_dir():
            yield Path(self.payload.cwd)
        if with_git:
            top = (_git(["rev-parse", "--show-toplevel"], self.process_cwd) or "").strip()
            if top and Path(top).is_dir():
                yield Path(top)
        yield self.process_cwd

    @property
    def project_dir(self) -> Path:
        """The project root: the harness's project-dir variable, then the payload cwd, then the process cwd."""
        if self._project_dir is None:
            self._project_dir = next(iter(self._candidates(with_git=False)))
        return self._project_dir

    @property
    def state_base(self) -> Path:
        """<config>/agent-state. A ladder: the first candidate root that CONTAINS an orchestrator tree wins,
        so a stray empty directory cannot shadow the real one; otherwise the first resolvable root."""
        if self._state_base is None:
            first: Optional[Path] = None
            for candidate in self._candidates(with_git=True):
                base = candidate / self.host.config_dir / "agent-state"
                if first is None:
                    first = base
                if (base / ORCHESTRATOR_DIRNAME).is_dir():
                    self._state_base = base
                    break
            if self._state_base is None:
                self._state_base = first or (self.process_cwd / self.host.config_dir / "agent-state")
        return self._state_base

    @property
    def block_cap(self) -> int:
        return resolve_block_cap(self.environ.get(self.host.block_cap_env))

    @property
    def contract_version(self) -> str:
        return contract_version(self.project_dir, self.host)

    def resolve(self, session: Optional[str] = None) -> Tuple[str, Optional[Path]]:
        sid = self.session_id if session is None else session
        if sid not in self._resolved:
            verdict, run_dir = resolve_run_dir(self.state_base, sid)
            self._resolved[sid] = (normalize_verdict(verdict), run_dir)
        return self._resolved[sid]

    def owned_state_file(self) -> Optional[Path]:
        return resolve_owned_state_file(self.state_base, self.session_id, self.states)

    def field(self, path: Optional[Path], name: str) -> str:
        return self.states.field(path, name)

    def log(self, hook: str, decision: str, detail: str) -> None:
        decision_log(self.state_base, hook, decision, detail)


# ---------------------------------------------------------------------------------------------------------
# A gate's answer.
# ---------------------------------------------------------------------------------------------------------


@dataclass
class Decision:
    exit_code: int = 0  # 0 = allow, 2 = block
    stdout: str = ""  # SessionStart context, or a Kiro block document
    stderr: str = ""  # the reason, shown to the agent on a block

    @property
    def blocked(self) -> bool:
        return self.exit_code == 2


def allow(stdout: str = "", stderr: str = "") -> Decision:
    return Decision(0, stdout, stderr)


def block(reason: str) -> Decision:
    return Decision(2, "", reason if reason.endswith("\n") else reason + "\n")


# ---------------------------------------------------------------------------------------------------------
# THE SELF-TEST MUST REMAIN THE LAST DEFINITION IN THIS FILE. See the header.
# ---------------------------------------------------------------------------------------------------------


def selftest() -> bool:
    return True
