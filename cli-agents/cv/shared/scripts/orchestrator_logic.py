"""Deterministic reference implementation of the CV Orchestrator's decision logic.

The CV Orchestrator Agent is authored as a *prompt* (``orchestrator/prompt.md``),
not as executable Python. Its convergence / deduplication / conflict-resolution /
oscillation / one-question-at-a-time rules are therefore specified in prose. This
module encodes **exactly** those deterministic rules as a small, well-tested
reference so the spec's testable-logic emphasis can be exercised over recorded
fixture findings with **stubbed** subagent outputs (no real subagent is ever
spawned by this module or its tests).

It consumes the SAME ``Finding`` / ``Change_List`` shapes the real agents produce
(see ``shared/schemas/finding.schema.json`` and ``shared/schemas/change_list.schema.json``):
a Finding is a ``dict`` with ``id``, ``source_agent``, ``iteration``,
``target_document``, ``category``, ``severity``, ``anchor`` (with a stable
``paragraph_key``), optional ``current`` / ``proposed``, ``rationale``, and
``status``.

The rules implemented here are cross-checked against ``orchestrator/prompt.md``
sections "Phase EDIT", "Conflict priority order", "Oscillation detection and the
alternate -> wont_fix (3x) rule", "Convergence predicate and the single
success-termination path", and "Phase QA"; and against ``design.md`` sections
"Deduplication", "Conflict resolution [R9.4]", "Oscillation handling
[R10.3, R10.4]", "Convergence and termination [R10.1, R10.2]", and the
per-iteration control-flow pseudocode.

Requirements: 6.6, 9.4, 10.1-10.5, 11.6, 12.3.
Properties: 5 (accepted-gap exclusion), 6 (convergence predicate), 8 (one
question at a time), 9 (dedup/conflict determinism feeding anchor-safe edits).

No environment variables are read anywhere (global steering rule).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

__all__ = [
    "REVIEWER_ORDER",
    "HIRING_MANAGER",
    "LENGTH_REVIEWER",
    "SEVERITY_RANK",
    "normalize_proposed",
    "anchor_paragraph_key",
    "dedup_key",
    "edit_identity",
    "anchor_key",
    "conflict_priority_rank",
    "dedup_findings",
    "ChangeListEntry",
    "ConflictRecord",
    "ChangeListResult",
    "build_change_list",
    "is_open",
    "reviewer_gate_status",
    "all_gates_pass",
    "pages_within_limits",
    "convergence_predicate",
    "Termination",
    "decide_edit_phase",
    "derive_length_findings",
    "OscillationLedger",
    "OneAtATimeError",
    "QuestionQueue",
    "AcceptedGapsRegister",
    "exclude_accepted_gaps",
    "IterationFixture",
    "IterationRecord",
    "RunOutcome",
    "simulate_run",
]

# ---------------------------------------------------------------------------
# Canonical constants (mirrors orchestrator/prompt.md "Phase REVIEW")
# ---------------------------------------------------------------------------

#: The five reviewers in their canonical REVIEW spawn order [R2.5]. Earlier in
#: this list == earlier-spawned == wins a same-category, same-severity tie
#: ("prefer the earlier-spawned reviewer in the REVIEW order").
REVIEWER_ORDER = (
    "cv-spell-format-reviewer",
    "cv-language-content-reviewer",
    "cv-jd-alignment-reviewer",
    "cv-ats-reviewer",
    "cv-hiring-manager-reviewer",
)

HIRING_MANAGER = "cv-hiring-manager-reviewer"
#: The Language & Content reviewer also services length-reduction directives.
LENGTH_REVIEWER = "cv-language-content-reviewer"

#: Severity ordering; higher rank == higher severity == wins a same-tier tie.
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "blocking": 4}

_WS_RE = re.compile(r"\s+")


def _reviewer_index(source_agent: str) -> int:
    """Index of a reviewer in the REVIEW order; unknown agents sort last."""
    try:
        return REVIEWER_ORDER.index(source_agent)
    except ValueError:
        return len(REVIEWER_ORDER)


# ---------------------------------------------------------------------------
# Finding-shape helpers
# ---------------------------------------------------------------------------


def normalize_proposed(proposed: Optional[str]) -> str:
    """Canonicalize a Finding's ``proposed`` text for dedup/conflict/oscillation.

    Lower-cases, collapses any run of whitespace to a single space, and strips.
    ``None`` (a Finding with no proposed change) normalizes to the empty string,
    so two such Findings at one anchor are treated as the same (empty) edit.
    """
    if proposed is None:
        return ""
    return _WS_RE.sub(" ", proposed).strip().lower()


def anchor_paragraph_key(finding: Mapping) -> str:
    """Stable paragraph key for a Finding's anchor.

    Returns ``anchor.paragraph_key`` when present (the design's coordinate
    system). For Findings whose anchor is structural (e.g. ats_structural.py
    emits ``type``/``hazard``/``section_index`` anchors without a
    ``paragraph_key``), a deterministic key is derived from the canonical JSON
    serialization of the anchor so dedup/conflict still behave deterministically
    for every Finding shape the suite produces.
    """
    anchor = finding.get("anchor") or {}
    pk = anchor.get("paragraph_key")
    if isinstance(pk, str) and pk:
        return pk
    return "anchor::" + json.dumps(anchor, sort_keys=True, ensure_ascii=False)


def dedup_key(finding: Mapping) -> tuple:
    """The canonical 4-tuple used for dedup AND oscillation matching.

    ``(target_document, anchor.paragraph_key, category, normalized(proposed))``
    -- identical across ``design.md`` "Deduplication" and "Oscillation handling",
    and ``orchestrator/prompt.md`` "Phase EDIT" and "Oscillation detection".
    """
    return (
        finding["target_document"],
        anchor_paragraph_key(finding),
        finding["category"],
        normalize_proposed(finding.get("proposed")),
    )


def edit_identity(finding: Mapping) -> tuple:
    """The identity of the *edit* a Finding implies (category-independent).

    ``(target_document, anchor.paragraph_key, normalized(proposed))``. Two
    Findings with the same edit identity but different categories collapse into
    a single Change_List entry whose ``implements_findings`` lists both (e.g. a
    spelling fix that is also an ATS keyword fix), per ``design.md``
    "Deduplication".
    """
    return (
        finding["target_document"],
        anchor_paragraph_key(finding),
        normalize_proposed(finding.get("proposed")),
    )


def anchor_key(finding: Mapping) -> tuple:
    """``(target_document, anchor.paragraph_key)`` -- the locus of a conflict."""
    return (finding["target_document"], anchor_paragraph_key(finding))


def _conflict_tier(category: str, severity: str) -> int:
    """Priority tier for the conflict order (lower wins).

    Encodes ``orchestrator/prompt.md`` "Conflict priority order" /
    ``design.md`` "Conflict resolution [R9.4]" exactly:

        1. ats        + blocking                -> 10
        (ats          + non-blocking            -> 15, just below ats-blocking)
        2. hiring_manager_concern + blocking|high-> 20
        (hiring_manager_concern + low|medium     -> 25)
        3. jd_gap                                -> 30
        4. spelling / formatting                 -> 40
        5. language                              -> 50
        6. length                                -> 60

    The default rule of R9.4 ("ATS-blocking severity wins over language
    preferences") falls out directly: 10 < 50.
    """
    if category == "ats":
        return 10 if severity == "blocking" else 15
    if category == "hiring_manager_concern":
        return 20 if severity in ("blocking", "high") else 25
    return {
        "jd_gap": 30,
        "spelling": 40,
        "formatting": 40,
        "language": 50,
        "length": 60,
    }.get(category, 70)


def conflict_priority_rank(finding: Mapping) -> tuple:
    """Total deterministic priority key for conflict resolution (min == winner).

    ``(tier, -severity_rank, reviewer_index, id)``:

    * ``tier`` -- the conflict-priority order above (lower wins).
    * ``-severity_rank`` -- within a tier, the higher severity wins.
    * ``reviewer_index`` -- if still tied, the earlier-spawned reviewer wins.
    * ``id`` -- final tiebreak so ordering is total and reproducible.
    """
    severity = finding["severity"]
    return (
        _conflict_tier(finding["category"], severity),
        -SEVERITY_RANK.get(severity, 0),
        _reviewer_index(finding.get("source_agent", "")),
        finding["id"],
    )


# ---------------------------------------------------------------------------
# Deduplication (design "Deduplication", prompt "Phase EDIT") [R2.6, R9.3]
# ---------------------------------------------------------------------------


def dedup_findings(findings: Iterable[Mapping]) -> list[dict]:
    """Deduplicate Findings by the canonical 4-tuple ``dedup_key``.

    Findings that share ``(target_document, paragraph_key, category,
    normalized(proposed))`` are the *same* Finding produced by more than one
    agent; they collapse into one representative whose ``implements_findings``
    lists every contributing Finding ``id`` (sorted, de-duplicated).

    Determinism (Property 9): the result is invariant under any permutation of
    the input -- the representative of each group is the highest-priority Finding
    (``conflict_priority_rank``), the merged ``implements_findings`` is sorted,
    and the returned list is sorted by ``dedup_key``.
    """
    groups: dict[tuple, list[dict]] = {}
    for finding in findings:
        groups.setdefault(dedup_key(finding), []).append(dict(finding))

    deduped: list[dict] = []
    for key in sorted(groups, key=lambda k: tuple(map(str, k))):
        members = groups[key]
        representative = dict(min(members, key=conflict_priority_rank))
        ids = sorted({m["id"] for m in members})
        representative["implements_findings"] = ids
        deduped.append(representative)
    return deduped


# ---------------------------------------------------------------------------
# Change_List construction with conflict resolution [R9.4]
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConflictRecord:
    """A recorded conflict and its resolution (for ``iteration_log.md``)."""

    target_document: str
    paragraph_key: str
    winner_id: str
    winner_category: str
    winner_severity: str
    losers: tuple  # tuple[dict] -> {"id","category","severity","reason"}
    blocking_loss: bool
    alternate_applied: bool
    synthesis_preferred: bool


@dataclass(frozen=True)
class ChangeListEntry:
    """One Change_List entry; ``to_dict`` yields a change_list.schema-valid object."""

    id: str
    iteration: int
    target_document: str
    paragraph_key: str
    operation: str
    implements_findings: tuple
    proposed: Optional[str]
    category: str
    match_text: Optional[str] = None

    def to_dict(self) -> dict:
        anchor: dict = {"paragraph_key": self.paragraph_key}
        if self.operation == "replace_run_text" and self.match_text:
            anchor["match_text"] = self.match_text
        entry: dict = {
            "id": self.id,
            "iteration": self.iteration,
            "target_document": self.target_document,
            "implements_findings": list(self.implements_findings),
            "operation": self.operation,
            "anchor": anchor,
        }
        if self.operation != "delete_paragraph" and self.proposed is not None:
            entry["new_text"] = self.proposed
        return entry


@dataclass(frozen=True)
class ChangeListResult:
    entries: tuple
    conflicts: tuple

    def to_change_list(self) -> list[dict]:
        return [entry.to_dict() for entry in self.entries]


def _operation_for(representative: Mapping, synthesis: bool) -> str:
    category = representative["category"]
    proposed = representative.get("proposed")
    match_text = (representative.get("anchor") or {}).get("match_text")
    if synthesis:
        # A synthesis edit rewrites the whole paragraph to satisfy both intents.
        return "replace_paragraph_text"
    if category == "length" and not proposed:
        return "delete_paragraph"
    if match_text:
        return "replace_run_text"
    return "replace_paragraph_text"


def _make_entry(
    identity_members: list[dict],
    iteration: int,
    seq: int,
    synthesis: bool,
) -> ChangeListEntry:
    representative = min(identity_members, key=conflict_priority_rank)
    implements: set[str] = set()
    for member in identity_members:
        implements.update(member.get("implements_findings") or [member["id"]])
    operation = _operation_for(representative, synthesis)
    match_text = (representative.get("anchor") or {}).get("match_text")
    return ChangeListEntry(
        id=f"CL-{iteration}-{seq:03d}",
        iteration=iteration,
        target_document=representative["target_document"],
        paragraph_key=anchor_paragraph_key(representative),
        operation=operation,
        implements_findings=tuple(sorted(implements)),
        proposed=representative.get("proposed"),
        category=representative["category"],
        match_text=match_text if operation == "replace_run_text" else None,
    )


def build_change_list(
    open_findings: Iterable[Mapping],
    iteration: int,
    reverse_anchors: Iterable[tuple] = (),
) -> ChangeListResult:
    """Translate open Findings into a deduplicated, conflict-resolved Change_List.

    Pipeline (``orchestrator/prompt.md`` "Phase EDIT"):

    1. ``dedup_findings`` collapses identical Findings (the 4-tuple).
    2. Findings are grouped by anchor ``(target_document, paragraph_key)``.
    3. Within an anchor, Findings are partitioned by *edit identity*
       (``normalized(proposed)``). A single edit identity -> one entry merging all
       contributing Findings (the cross-category spelling+ATS collapse). Multiple
       incompatible edit identities -> a **conflict**: the highest-priority
       Finding's edit identity wins (``conflict_priority_rank``); losing
       identities are recorded, never silently dropped, and a blocking loss is
       flagged with ``synthesis_preferred`` so the orchestrator emits a synthesis
       ``replace_paragraph_text`` the next REVIEW validates.
    4. ``reverse_anchors`` (from the oscillation 2nd-recurrence rule) flips the
       winner at *that anchor only* to the runner-up edit identity.

    Determinism (Property 9): for fixed inputs the entries are emitted in sorted
    anchor order with stable ids, and the result is invariant under any
    permutation of ``open_findings``.
    """
    reverse_set = set(reverse_anchors)
    deduped = dedup_findings(open_findings)

    by_anchor: dict[tuple, list[dict]] = {}
    for finding in deduped:
        by_anchor.setdefault(anchor_key(finding), []).append(finding)

    entries: list[ChangeListEntry] = []
    conflicts: list[ConflictRecord] = []
    seq = 0

    for akey in sorted(by_anchor, key=lambda k: tuple(map(str, k))):
        members = by_anchor[akey]
        # Partition by edit identity, preserving a deterministic identity order.
        identities: dict[str, list[dict]] = {}
        for finding in members:
            identities.setdefault(normalize_proposed(finding.get("proposed")), []).append(finding)

        # Rank identities by the best (min) priority of any Finding within.
        ranked = sorted(
            identities.values(),
            key=lambda group: min(conflict_priority_rank(f) for f in group),
        )

        seq += 1
        if len(ranked) == 1:
            entries.append(_make_entry(ranked[0], iteration, seq, synthesis=False))
            continue

        # Conflict: incompatible proposals at the same anchor.
        reverse = akey in reverse_set
        winner_group = ranked[1] if (reverse and len(ranked) >= 2) else ranked[0]
        loser_groups = [g for g in ranked if g is not winner_group]
        winner_rep = min(winner_group, key=conflict_priority_rank)

        loser_records: list[dict] = []
        blocking_loss = False
        for group in loser_groups:
            for finding in group:
                if finding["severity"] == "blocking":
                    blocking_loss = True
                loser_records.append(
                    {
                        "id": finding["id"],
                        "category": finding["category"],
                        "severity": finding["severity"],
                        "reason": "alternate_resolution" if reverse else "lower_priority",
                    }
                )
        loser_records.sort(key=lambda r: r["id"])

        conflicts.append(
            ConflictRecord(
                target_document=akey[0],
                paragraph_key=akey[1],
                winner_id=winner_rep["id"],
                winner_category=winner_rep["category"],
                winner_severity=winner_rep["severity"],
                losers=tuple(loser_records),
                blocking_loss=blocking_loss,
                alternate_applied=reverse,
                synthesis_preferred=blocking_loss,
            )
        )
        entries.append(
            _make_entry(winner_group, iteration, seq, synthesis=blocking_loss)
        )

    return ChangeListResult(entries=tuple(entries), conflicts=tuple(conflicts))


# ---------------------------------------------------------------------------
# Gate evaluation [R10.5, R12.3, Property 5] and convergence [R10.1, Property 6]
# ---------------------------------------------------------------------------

#: Statuses that exclude a Finding from "open" -- i.e. from gate evaluation.
#: ``accepted_gap`` (R12.3, Property 5) and ``wont_fix`` (R10.4) are never open.
NON_OPEN_STATUSES = frozenset({"accepted_gap", "wont_fix"})


def is_open(finding: Mapping) -> bool:
    """True iff the Finding counts as an open issue for gate evaluation.

    A Finding is open unless its ``status`` is ``accepted_gap`` or ``wont_fix``
    (both excluded from gates), or it has already been resolved (``applied`` /
    ``already_satisfied``). ``open`` and ``verification_failed`` are open; the
    latter is an edit that did not stick and still needs attention [R3.6].
    """
    status = finding.get("status", "open")
    if status in NON_OPEN_STATUSES:
        return False
    if status in ("applied", "already_satisfied"):
        return False
    return True


def exclude_accepted_gaps(findings: Iterable[Mapping]) -> list[dict]:
    """Drop ``accepted_gap`` and ``wont_fix`` Findings (gate-exclusion view).

    Property 5 / R10.5 / R12.3: accepted gaps (and won't-fix items) are excluded
    from every subsequent gate evaluation.
    """
    return [dict(f) for f in findings if f.get("status") not in NON_OPEN_STATUSES]


def reviewer_gate_status(
    reviewer: str,
    findings: Iterable[Mapping],
    recommendation: Optional[str] = None,
) -> str:
    """``PASS`` or ``FAIL`` for one reviewer's findings this REVIEW.

    A reviewer's gate passes when it emitted **zero open Findings** for every
    document it reviewed (``accepted_gap`` / ``wont_fix`` excluded). The hiring
    manager additionally requires its recommendation to read ``INVITE`` [R8.5].
    """
    has_open = any(is_open(f) for f in findings if f.get("source_agent") == reviewer)
    if has_open:
        return "FAIL"
    if reviewer == HIRING_MANAGER:
        return "PASS" if recommendation == "INVITE" else "FAIL"
    return "PASS"


def all_gates_pass(
    findings_by_reviewer: Mapping[str, Iterable[Mapping]],
    recommendation: Optional[str],
) -> bool:
    """True iff every one of the five reviewer gates passes independently [R8.6]."""
    for reviewer in REVIEWER_ORDER:
        status = reviewer_gate_status(
            reviewer, findings_by_reviewer.get(reviewer, ()), recommendation
        )
        if status != "PASS":
            return False
    return True


def pages_within_limits(
    page_counts: Mapping[str, int],
    page_limits: Mapping[str, int],
) -> bool:
    """True iff every measured document is within its (possibly overridden) limit.

    Hard gate [R11.6, Property 7]: a document over its limit can never converge,
    regardless of all other gate states. Only documents that exist (present in
    ``page_counts``) are checked; a missing letter is simply absent.
    """
    for document, pages in page_counts.items():
        limit = page_limits.get(document)
        if limit is None:
            return False
        if pages > limit:
            return False
    return True


def convergence_predicate(
    findings_by_reviewer: Mapping[str, Iterable[Mapping]],
    recommendation: Optional[str],
    page_counts: Mapping[str, int],
    page_limits: Mapping[str, int],
) -> bool:
    """The full convergence predicate [R10.1, Property 6].

    Holds iff, simultaneously: every reviewer gate is PASS, every Working Copy is
    within its page limit, AND the hiring manager recommends ``INVITE``. An
    ``INVITE`` alone is necessary but not sufficient [R8.6, D-8].
    """
    return (
        all_gates_pass(findings_by_reviewer, recommendation)
        and pages_within_limits(page_counts, page_limits)
        and recommendation == "INVITE"
    )


# ---------------------------------------------------------------------------
# EDIT-phase decision: the single success-termination path [C1, Property 6]
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Termination:
    """The outcome of one EDIT-phase decision."""

    decision: str  # "TERMINATE_SUCCESS" | "EDIT" | "ADVANCE_REVIEW"
    change_list: ChangeListResult
    converged: bool


def decide_edit_phase(
    open_findings: Iterable[Mapping],
    findings_by_reviewer: Mapping[str, Iterable[Mapping]],
    recommendation: Optional[str],
    page_counts: Mapping[str, int],
    page_limits: Mapping[str, int],
    iteration: int,
    reverse_anchors: Iterable[tuple] = (),
) -> Termination:
    """Encode the EDIT phase's branch -- the ONLY place success is declared.

    ``orchestrator/prompt.md`` "Phase EDIT" / "Convergence predicate":

    * Build the Change_List from the open Findings (dedup + conflict rules).
    * **Empty Change_List** -> a fresh REVIEW produced nothing to change. This is
      the single success-check point: if ``convergence_predicate`` holds ->
      ``TERMINATE_SUCCESS``; otherwise -> ``ADVANCE_REVIEW`` (e.g. a page is still
      over limit or a gate still fails). Success is NEVER declared elsewhere.
    * **Non-empty Change_List** -> ``EDIT`` (snapshot backups, spawn the editor).
    """
    change_list = build_change_list(open_findings, iteration, reverse_anchors)
    if change_list.entries:
        return Termination(decision="EDIT", change_list=change_list, converged=False)

    converged = convergence_predicate(
        findings_by_reviewer, recommendation, page_counts, page_limits
    )
    decision = "TERMINATE_SUCCESS" if converged else "ADVANCE_REVIEW"
    return Termination(decision=decision, change_list=change_list, converged=converged)


def derive_length_findings(
    page_counts: Mapping[str, int],
    page_limits: Mapping[str, int],
    iteration: int,
) -> list[dict]:
    """EVALUATE-phase length work: one ``category: length`` Finding per over-limit doc.

    These feed the *next* iteration's REVIEW/EDIT exactly like any other open
    Finding [R11.5]. EVALUATE never declares success -- it only derives work and
    advances (Property 6).
    """
    findings: list[dict] = []
    for document in sorted(page_counts):
        pages = page_counts[document]
        limit = page_limits.get(document)
        if limit is not None and pages > limit:
            findings.append(
                {
                    "id": f"LEN-{iteration}-{document}",
                    "source_agent": LENGTH_REVIEWER,
                    "iteration": iteration,
                    "target_document": document,
                    "category": "length",
                    "severity": "medium",
                    "anchor": {"paragraph_key": f"{document}::length-directive"},
                    "proposed": (
                        f"Reduce {document} from {pages} to <= {limit} page(s), "
                        "preserving higher-priority content."
                    ),
                    "rationale": (
                        f"{document} renders to {pages} page(s); the limit is {limit}."
                    ),
                    "status": "open",
                }
            )
    return findings


# ---------------------------------------------------------------------------
# Oscillation ledger: alternate (2nd) -> wont_fix (3rd) [R10.3, R10.4]
# ---------------------------------------------------------------------------


@dataclass
class _OscEntry:
    first_applied_iteration: int
    recurred_iterations: list = field(default_factory=list)
    recurrence_count: int = 0
    alternate_applied: bool = False
    status: str = "tracking"  # "tracking" | "wont_fix"


class OscillationLedger:
    """Tracks Findings that recur after being ``applied`` (the 4-tuple key).

    Mirrors ``orchestrator/prompt.md`` "Oscillation detection and the alternate
    -> wont_fix (3x) rule" and ``design.md`` "Oscillation handling":

    * A Finding is "the same" across iterations when its ``dedup_key`` recurs
      after the editor marked that change ``applied``.
    * 1st recurrence -> classify as oscillation, re-apply through normal rules.
    * 2nd recurrence -> apply ONE alternate resolution (reverse the two
      contending agents' priority *for that anchor only*).
    * 3rd recurrence -> mark ``wont_fix`` and exclude from gate evaluation.

    The ledger is keyed by the stable 4-tuple, so it survives paragraph-index
    shifts and (in the real orchestrator) a resume.
    """

    def __init__(self) -> None:
        self._applied: dict[tuple, int] = {}
        self._entries: dict[tuple, _OscEntry] = {}

    def mark_applied(self, finding: Mapping, iteration: int) -> None:
        """Record that ``finding``'s change was applied in ``iteration``.

        Only the first application iteration is retained; a later genuine
        re-application (after a recurrence was re-applied) does not reset the
        recurrence count.
        """
        key = dedup_key(finding)
        self._applied.setdefault(key, iteration)

    def observe(self, finding: Mapping, iteration: int) -> str:
        """Observe a Finding re-flagged in ``iteration``; return the action.

        Returns one of:

        * ``"none"`` -- not previously applied; not an oscillation.
        * ``"reapply"`` -- 1st recurrence; re-apply through normal conflict rules.
        * ``"alternate"`` -- 2nd recurrence; apply the alternate resolution.
        * ``"wont_fix"`` -- 3rd recurrence; mark ``wont_fix`` and exclude.
        """
        key = dedup_key(finding)
        if key not in self._applied:
            return "none"

        entry = self._entries.get(key)
        if entry is None:
            entry = _OscEntry(first_applied_iteration=self._applied[key])
            self._entries[key] = entry

        if entry.status == "wont_fix":
            return "wont_fix"

        entry.recurred_iterations.append(iteration)
        entry.recurrence_count += 1

        if entry.recurrence_count == 1:
            return "reapply"
        if entry.recurrence_count == 2:
            entry.alternate_applied = True
            return "alternate"
        entry.status = "wont_fix"
        return "wont_fix"

    def recurrence_count(self, finding: Mapping) -> int:
        entry = self._entries.get(dedup_key(finding))
        return entry.recurrence_count if entry else 0

    def is_wont_fix(self, finding: Mapping) -> bool:
        entry = self._entries.get(dedup_key(finding))
        return bool(entry and entry.status == "wont_fix")

    def reverse_anchors(self) -> set[tuple]:
        """Anchors whose conflict priority is currently reversed (alternate active).

        An anchor is reversed once a Finding there hit its 2nd recurrence and has
        not yet escalated to ``wont_fix``.
        """
        anchors: set[tuple] = set()
        for key, entry in self._entries.items():
            if entry.alternate_applied and entry.status != "wont_fix":
                target_document, paragraph_key = key[0], key[1]
                anchors.add((target_document, paragraph_key))
        return anchors

    def wont_fix_keys(self) -> set[tuple]:
        return {k for k, e in self._entries.items() if e.status == "wont_fix"}

    def to_dict(self) -> dict:
        """Serialize to the ``oscillation_ledger.json`` shape from the prompt."""
        entries = []
        for key, entry in self._entries.items():
            entries.append(
                {
                    "key": {
                        "target_document": key[0],
                        "paragraph_key": key[1],
                        "category": key[2],
                        "proposed_norm": key[3],
                    },
                    "first_applied_iteration": entry.first_applied_iteration,
                    "recurred_iterations": list(entry.recurred_iterations),
                    "recurrence_count": entry.recurrence_count,
                    "alternate_applied": entry.alternate_applied,
                    "status": entry.status,
                }
            )
        return {"schema": "cv-oscillation-ledger/v1", "entries": entries}


# ---------------------------------------------------------------------------
# One-question-at-a-time queue [R2.13, R6.6, Property 8]
# ---------------------------------------------------------------------------


class OneAtATimeError(RuntimeError):
    """Raised when a question is issued before the previous answer is recorded."""


class QuestionQueue:
    """Serializes JD-alignment Q&A: one question at a time, answer-before-next.

    Mirrors ``orchestrator/prompt.md`` "Phase QA". The orchestrator presents
    exactly one question, waits, records the verbatim answer into
    ``answered_questions.json``, and only then presents the next. Accepted gaps
    are never re-asked [R12.3].

    Invariant (Property 8): ``next_question`` raises ``OneAtATimeError`` if the
    previously issued question has not yet been answered.
    """

    def __init__(self, questions: Iterable[Mapping]) -> None:
        # Preserve order; each question carries at least a ``qid``.
        self._pending: list[dict] = [dict(q) for q in questions]
        self._answered: list[dict] = []
        self._outstanding: Optional[dict] = None

    @property
    def outstanding(self) -> Optional[dict]:
        return self._outstanding

    @property
    def answered(self) -> list[dict]:
        return list(self._answered)

    def has_pending(self) -> bool:
        return bool(self._pending) or self._outstanding is not None

    def answered_qids(self) -> set:
        return {a["qid"] for a in self._answered}

    def next_question(self) -> Optional[dict]:
        """Issue the next unanswered question, or ``None`` when none remain.

        Raises ``OneAtATimeError`` if a previously issued question is still
        outstanding (no answer recorded) -- this is the Property 8 guard.
        """
        if self._outstanding is not None:
            raise OneAtATimeError(
                f"question {self._outstanding['qid']!r} issued but not yet answered; "
                "cannot present the next question (Property 8)."
            )
        if not self._pending:
            return None
        self._outstanding = self._pending.pop(0)
        return self._outstanding

    def record_answer(self, answer: str, *, answered_at: Optional[str] = None) -> dict:
        """Record the verbatim answer to the currently outstanding question."""
        if self._outstanding is None:
            raise OneAtATimeError("no outstanding question to answer.")
        record = {
            "qid": self._outstanding["qid"],
            "finding_ref": self._outstanding.get("finding_ref"),
            "question": self._outstanding.get("question"),
            "answer": answer,
            "status": "answered",
            "answered_at": answered_at,
        }
        self._answered.append(record)
        self._outstanding = None
        return record

    def append_questions(self, questions: Iterable[Mapping]) -> None:
        """Phase 2 may surface follow-up questions; never re-add an answered qid."""
        seen = self.answered_qids()
        for question in questions:
            if question["qid"] in seen:
                continue
            self._pending.append(dict(question))


# ---------------------------------------------------------------------------
# Accepted-gaps register [R12, Property 5]
# ---------------------------------------------------------------------------


class AcceptedGapsRegister:
    """The Accepted_Gaps register: record-once, exclude-and-never-re-ask.

    Mirrors ``accepted_gaps.md`` semantics [R12]: each entry preserves the
    originating Finding id, agent, iteration accepted, the candidate's verbatim
    declining response, and a one-line summary. An accepted gap is excluded from
    gate evaluation and never reopened or re-asked (Property 5, R12.3).
    """

    def __init__(self) -> None:
        self._entries: dict[str, dict] = {}

    def accept(
        self,
        finding: Mapping,
        verbatim_response: str,
        iteration: int,
        summary: str = "",
    ) -> dict:
        finding_id = finding["id"]
        # Record-once: an already-accepted gap is never overwritten or duplicated.
        if finding_id not in self._entries:
            self._entries[finding_id] = {
                "finding_id": finding_id,
                "source_agent": finding.get("source_agent", "cv-jd-alignment-reviewer"),
                "iteration": iteration,
                "verbatim_response": verbatim_response,
                "summary": summary or finding.get("rationale", ""),
            }
        return self._entries[finding_id]

    def is_accepted(self, finding_id: str) -> bool:
        return finding_id in self._entries

    def entries(self) -> list[dict]:
        return [self._entries[k] for k in sorted(self._entries)]

    def mark_findings(self, findings: Iterable[Mapping]) -> list[dict]:
        """Return ``findings`` with accepted ones forced to ``status: accepted_gap``."""
        out: list[dict] = []
        for finding in findings:
            f = dict(finding)
            if self.is_accepted(f["id"]):
                f["status"] = "accepted_gap"
            out.append(f)
        return out


# ---------------------------------------------------------------------------
# Whole-run simulation over recorded fixture findings (STUBBED subagents)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IterationFixture:
    """One iteration's *recorded* REVIEW outcome -- a STUB for the subagents.

    This is what a stubbed REVIEW phase would produce: the open Findings each
    reviewer emitted, the hiring-manager recommendation, and the page counts the
    (stubbed) ``page_count.py`` reported after the prior EDIT. No real subagent is
    spawned; these are recorded fixtures the deterministic logic drives over.

    ``findings`` is a flat list of Finding dicts across all reviewers (each tagged
    with its ``source_agent``). ``recommendation`` is the hiring manager's
    verdict (``INVITE`` / ``DO_NOT_INVITE``). ``page_counts`` maps each existing
    Working Copy to its rendered page count.
    """

    findings: tuple
    recommendation: str
    page_counts: Mapping[str, int]


@dataclass(frozen=True)
class IterationRecord:
    """What the orchestrator decided for one simulated iteration."""

    iteration: int
    decision: str  # "TERMINATE_SUCCESS" | "EDIT" | "ADVANCE_REVIEW"
    change_list: tuple  # the Change_List entry dicts built this iteration
    conflicts: tuple
    gate_status: Mapping[str, str]
    converged: bool
    wont_fixed: tuple  # dedup-keys escalated to wont_fix this iteration


@dataclass(frozen=True)
class RunOutcome:
    """The result of a whole simulated run."""

    outcome: str  # "COMPLETED" | "DID_NOT_CONVERGE"
    final_iteration: int
    records: tuple
    oscillation_ledger: Mapping


def _findings_by_reviewer(findings: Iterable[Mapping]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {r: [] for r in REVIEWER_ORDER}
    for finding in findings:
        grouped.setdefault(finding.get("source_agent", ""), []).append(dict(finding))
    return grouped


def simulate_run(
    iterations: list[IterationFixture],
    page_limits: Mapping[str, int],
    iteration_cap: int = 10,
) -> RunOutcome:
    """Drive the orchestrator loop over recorded fixture iterations (no subagents).

    For each recorded ``IterationFixture`` (a stubbed REVIEW result), this runs
    the deterministic decision logic:

    * exclude ``accepted_gap`` / ``wont_fix`` Findings from the open set
      (Property 5);
    * apply the oscillation escalation -- alternate at the 2nd recurrence,
      ``wont_fix`` at the 3rd -- against the persistent ledger [R10.3, R10.4];
    * build the deduplicated, conflict-resolved Change_List with any
      anchor-reversals the ledger requests;
    * take the EDIT-phase branch: empty Change_List -> evaluate the convergence
      predicate (the ONLY success path, Property 6); otherwise mark the entries
      ``applied`` (stubbed editor success) and ADVANCE to the next REVIEW.

    Honors the Iteration_Cap of 10: a run that never converges terminates
    ``DID_NOT_CONVERGE`` [R10.2].

    Determinism: identical fixtures always yield the identical ``RunOutcome``.
    """
    ledger = OscillationLedger()
    records: list[IterationRecord] = []

    n = 0
    for fixture in iterations:
        n += 1
        if n > iteration_cap:
            n -= 1
            break

        # --- apply oscillation escalation to this REVIEW's findings ---
        wont_fixed_this_iter: list[tuple] = []
        adjusted: list[dict] = []
        for finding in fixture.findings:
            f = dict(finding)
            if f.get("status") in NON_OPEN_STATUSES:
                adjusted.append(f)
                continue
            action = ledger.observe(f, n)
            if action == "wont_fix":
                f["status"] = "wont_fix"
                wont_fixed_this_iter.append(dedup_key(f))
            adjusted.append(f)

        # --- gate status (Property 5: accepted_gap / wont_fix excluded) ---
        by_reviewer = _findings_by_reviewer(adjusted)
        gate_status = {
            reviewer: reviewer_gate_status(
                reviewer, by_reviewer.get(reviewer, ()), fixture.recommendation
            )
            for reviewer in REVIEWER_ORDER
        }

        open_findings = [f for f in adjusted if is_open(f)]
        reverse_anchors = ledger.reverse_anchors()

        result = decide_edit_phase(
            open_findings=open_findings,
            findings_by_reviewer=by_reviewer,
            recommendation=fixture.recommendation,
            page_counts=fixture.page_counts,
            page_limits=page_limits,
            iteration=n,
            reverse_anchors=reverse_anchors,
        )

        if result.decision != "TERMINATE_SUCCESS":
            # Stubbed editor: every emitted entry applies successfully, so the
            # findings it implements are recorded as applied in the ledger.
            for entry in result.change_list.entries:
                ledger.mark_applied(
                    {
                        "target_document": entry.target_document,
                        "anchor": {"paragraph_key": entry.paragraph_key},
                        "category": entry.category,
                        "proposed": entry.proposed,
                    },
                    n,
                )

        records.append(
            IterationRecord(
                iteration=n,
                decision=result.decision,
                change_list=tuple(result.change_list.to_change_list()),
                conflicts=result.change_list.conflicts,
                gate_status=gate_status,
                converged=result.converged,
                wont_fixed=tuple(wont_fixed_this_iter),
            )
        )

        if result.decision == "TERMINATE_SUCCESS":
            return RunOutcome(
                outcome="COMPLETED",
                final_iteration=n,
                records=tuple(records),
                oscillation_ledger=ledger.to_dict(),
            )

    return RunOutcome(
        outcome="DID_NOT_CONVERGE",
        final_iteration=n,
        records=tuple(records),
        oscillation_ledger=ledger.to_dict(),
    )
