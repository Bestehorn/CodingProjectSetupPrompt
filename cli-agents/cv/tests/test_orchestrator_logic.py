"""Orchestrator-logic harness tests with STUBBED subagents (task 17).

The CV Orchestrator Agent is authored as a *prompt* (``orchestrator/prompt.md``);
its deterministic decision rules — deduplication, conflict-priority resolution,
oscillation escalation (alternate -> ``wont_fix`` at the 3rd recurrence),
one-question-at-a-time relay, and the single success-termination path — are
encoded as a reference implementation in ``shared/scripts/orchestrator_logic.py``.

These tests drive that reference logic over *recorded fixture Findings* without
ever spawning a real subagent (the ``IterationFixture`` objects ARE the stubbed
REVIEW outputs). They assert the design's correctness properties and the
conflict-priority / oscillation rules:

* **Property 5 — accepted-gap exclusion & persistence.** Accepted gaps are
  recorded with a verbatim response (once), excluded from every gate evaluation,
  and never re-asked.
* **Property 6 — convergence predicate / single success path.** ``COMPLETED`` is
  declared only when, in a REVIEW, every reviewer gate is PASS, every Working
  Copy is within its page limit, and the hiring manager recommends INVITE — and
  only via the EDIT phase's empty-Change_List branch. The EVALUATE phase never
  declares success; it only derives length work and advances.
* **Property 8 — one question at a time.** The QA relay never issues question
  ``k+1`` before question ``k`` is answered.
* **Property 9 — dedup/conflict determinism feeding anchor-safe edits.** The
  Change_List is invariant under any permutation of the input Findings, every
  entry targets an anchor that some input Finding named, and every entry's
  ``implements_findings`` is a non-empty subset of the input Finding ids.
* **Conflict-priority order** (R9.4) and **oscillation handling** (R10.3, R10.4).

Requirements: 6.6, 9.4, 10.1-10.5, 11.6, 12.3.

No environment variables are read; ``orchestrator_logic`` is importable because
``conftest.py`` adds ``shared/scripts`` to ``sys.path`` from this file's location.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import orchestrator_logic as ol


# --------------------------------------------------------------------------
# Finding builders (the recorded-fixture shape the real reviewers emit)
# --------------------------------------------------------------------------


def _finding(
    fid: str,
    source: str,
    target: str,
    category: str,
    severity: str,
    paragraph_key: str,
    proposed,
    *,
    status: str = "open",
    match_text: str | None = None,
    iteration: int = 1,
) -> dict:
    """Build one schema-shaped Finding dict for the harness."""
    anchor: dict = {"paragraph_key": paragraph_key}
    if match_text is not None:
        anchor["match_text"] = match_text
    return {
        "id": fid,
        "source_agent": source,
        "iteration": iteration,
        "target_document": target,
        "category": category,
        "severity": severity,
        "anchor": anchor,
        "proposed": proposed,
        "rationale": f"{category} finding at {paragraph_key}",
        "status": status,
    }


CV = "CV_Working_Copy"
LETTER = "Letter_Working_Copy"
SPELL = "cv-spell-format-reviewer"
LANG = "cv-language-content-reviewer"
JD = "cv-jd-alignment-reviewer"
ATS = "cv-ats-reviewer"
HM = ol.HIRING_MANAGER


# ==========================================================================
# Finding-shape helpers: normalization, dedup keys, edit identity
# ==========================================================================


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ""),
        ("  Alpha   TEXT ", "alpha text"),
        ("Alpha text", "alpha text"),
        ("\tMixed\nWhite   space\r", "mixed white space"),
    ],
)
def test_normalize_proposed_canonicalizes(raw, expected):
    assert ol.normalize_proposed(raw) == expected


def test_dedup_key_uses_normalized_proposed():
    a = _finding("F1", SPELL, CV, "spelling", "high", "p1", "Alpha text")
    b = _finding("F2", ATS, CV, "spelling", "high", "p1", "  alpha   TEXT ")
    # Same target/key/category and proposed-normalizes-equal -> identical dedup key.
    assert ol.dedup_key(a) == ol.dedup_key(b)


def test_anchor_paragraph_key_handles_structural_anchor():
    """A structural anchor (no paragraph_key) still yields a deterministic key."""
    f = {
        "id": "ATS-1",
        "target_document": CV,
        "category": "ats",
        "severity": "blocking",
        "anchor": {"type": "section", "hazard": "multi_column", "section_index": 0},
        "proposed": "single column",
    }
    k1 = ol.anchor_paragraph_key(f)
    k2 = ol.anchor_paragraph_key(dict(f))
    assert k1 == k2 and k1.startswith("anchor::")


# ==========================================================================
# Deduplication (Property 9 component) — design "Deduplication"
# ==========================================================================


def test_dedup_collapses_identical_findings_and_merges_ids():
    """Two agents producing the same edit collapse into one, listing both ids."""
    a = _finding("SF-1", SPELL, CV, "spelling", "high", "p1", "Amazon Q")
    b = _finding("SF-2", ATS, CV, "spelling", "high", "p1", "amazon q")  # normalizes equal
    deduped = ol.dedup_findings([a, b])
    assert len(deduped) == 1
    assert deduped[0]["implements_findings"] == ["SF-1", "SF-2"]


def test_dedup_keeps_distinct_findings_separate():
    a = _finding("SF-1", SPELL, CV, "spelling", "high", "p1", "Amazon Q")
    b = _finding("SF-2", SPELL, CV, "spelling", "high", "p2", "Amazon Q")  # other anchor
    deduped = ol.dedup_findings([a, b])
    assert len(deduped) == 2


# ==========================================================================
# Conflict-priority order (R9.4) — design "Conflict resolution"
# ==========================================================================

# The canonical priority order with each tier's representative severity.
PRIORITY_ORDER = [
    ("ats", "blocking"),
    ("hiring_manager_concern", "blocking"),
    ("jd_gap", "high"),
    ("spelling", "high"),
    ("language", "high"),
    ("length", "medium"),
]


def test_conflict_priority_rank_is_strictly_increasing_down_the_order():
    """Each category in the order outranks every later one (smaller key wins)."""
    ranks = [
        ol.conflict_priority_rank(
            _finding(f"F{i}", SPELL, CV, cat, sev, "p1", f"prop-{i}")
        )
        for i, (cat, sev) in enumerate(PRIORITY_ORDER)
    ]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks), "ranks must be a strict total order"


@pytest.mark.parametrize(
    "hi_idx,lo_idx",
    [(i, j) for i in range(len(PRIORITY_ORDER)) for j in range(len(PRIORITY_ORDER)) if i < j],
)
def test_higher_priority_category_wins_conflict(hi_idx, lo_idx):
    """At one anchor with incompatible proposals, the higher-priority category wins."""
    hi_cat, hi_sev = PRIORITY_ORDER[hi_idx]
    lo_cat, lo_sev = PRIORITY_ORDER[lo_idx]
    hi = _finding("HI", ATS, CV, hi_cat, hi_sev, "p1", "winner proposal")
    lo = _finding("LO", LANG, CV, lo_cat, lo_sev, "p1", "loser proposal")
    result = ol.build_change_list([hi, lo], iteration=1)

    assert len(result.entries) == 1
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.winner_id == "HI"
    assert conflict.winner_category == hi_cat
    assert {loser["id"] for loser in conflict.losers} == {"LO"}
    # The winning proposal is the one emitted to the editor.
    assert result.entries[0].proposed == "winner proposal"


def test_ats_blocking_beats_language_default_rule():
    """R9.4 default: an ATS-blocking hazard wins over a language preference."""
    ats = _finding("ATS-1", ATS, CV, "ats", "blocking", "p1", "Convert to single column")
    lang = _finding("LC-1", LANG, CV, "language", "medium", "p1", "Reword for flow")
    result = ol.build_change_list([ats, lang], iteration=1)
    assert result.entries[0].category == "ats"
    assert result.entries[0].proposed == "Convert to single column"


def test_blocking_loser_is_recorded_and_triggers_synthesis():
    """A losing *blocking* finding is never silently dropped (synthesis preferred)."""
    ats = _finding("ATS-1", ATS, CV, "ats", "blocking", "p1", "Single column rewrite")
    hm = _finding("HM-1", HM, CV, "hiring_manager_concern", "blocking", "p1", "Reconcile dates")
    result = ol.build_change_list([ats, hm], iteration=1)
    conflict = result.conflicts[0]
    assert conflict.winner_id == "ATS-1"
    assert conflict.blocking_loss is True
    assert conflict.synthesis_preferred is True
    # Synthesis is emitted as a whole-paragraph rewrite the next REVIEW validates.
    assert result.entries[0].operation == "replace_paragraph_text"


def test_priority_tiebreak_prefers_earlier_reviewer():
    """Same tier and severity -> the earlier-spawned reviewer outranks (R2.5)."""
    early = _finding("F1", SPELL, CV, "spelling", "high", "p1", "A")  # reviewer index 0
    late = _finding("F2", LANG, CV, "spelling", "high", "p1", "B")  # reviewer index 1
    assert ol.conflict_priority_rank(early) < ol.conflict_priority_rank(late)


# ==========================================================================
# Property 9 — determinism + anchor-safe edits (hypothesis driven)
# ==========================================================================

_TARGETS = [CV, LETTER, "package_coherence"]
_CATEGORIES = [
    "spelling",
    "formatting",
    "language",
    "jd_gap",
    "ats",
    "hiring_manager_concern",
    "length",
]
_SEVERITIES = ["low", "medium", "high", "blocking"]
_PARAGRAPH_KEYS = ["exp.aws.bullet.3", "summary.para.1", "skills.bullet.5", "early.bullet.9"]
# Includes a whitespace/case variant of the first proposal and ``None``.
_PROPOSALS = ["Alpha proposal", "Beta proposal", "  alpha   PROPOSAL ", None]
_SOURCES = list(ol.REVIEWER_ORDER)


@st.composite
def _finding_specs(draw, max_size: int = 12):
    size = draw(st.integers(min_value=1, max_value=max_size))
    return [
        {
            "source_agent": draw(st.sampled_from(_SOURCES)),
            "target_document": draw(st.sampled_from(_TARGETS)),
            "category": draw(st.sampled_from(_CATEGORIES)),
            "severity": draw(st.sampled_from(_SEVERITIES)),
            "paragraph_key": draw(st.sampled_from(_PARAGRAPH_KEYS)),
            "proposed": draw(st.sampled_from(_PROPOSALS)),
        }
        for _ in range(size)
    ]


def _materialize(specs: list[dict]) -> list[dict]:
    """Assign unique ids so dedup/conflict ordering is a strict total order."""
    return [
        _finding(
            f"F{i:03d}",
            spec["source_agent"],
            spec["target_document"],
            spec["category"],
            spec["severity"],
            spec["paragraph_key"],
            spec["proposed"],
        )
        for i, spec in enumerate(specs)
    ]


@settings(max_examples=80, deadline=None)
@given(specs=_finding_specs(), data=st.data())
def test_dedup_and_change_list_invariant_under_permutation(specs, data):
    """Property 9: identical inputs in any order yield the identical Change_List."""
    base = _materialize(specs)
    perm = data.draw(st.permutations(base))

    assert ol.dedup_findings(perm) == ol.dedup_findings(base)

    result_base = ol.build_change_list(base, iteration=3)
    result_perm = ol.build_change_list(perm, iteration=3)
    assert result_base == result_perm
    assert result_base.to_change_list() == result_perm.to_change_list()


@settings(max_examples=80, deadline=None)
@given(specs=_finding_specs())
def test_change_list_entries_are_anchor_safe(specs):
    """Property 9: every entry targets an input anchor and traces to input ids."""
    findings = _materialize(specs)
    input_anchors = {(f["target_document"], f["anchor"]["paragraph_key"]) for f in findings}
    input_ids = {f["id"] for f in findings}

    result = ol.build_change_list(findings, iteration=2)

    entry_ids = [entry.id for entry in result.entries]
    assert len(entry_ids) == len(set(entry_ids)), "entry ids must be unique"

    for entry in result.entries:
        assert (entry.target_document, entry.paragraph_key) in input_anchors
        assert entry.implements_findings, "implements_findings must be non-empty"
        assert set(entry.implements_findings) <= input_ids


@settings(max_examples=60, deadline=None)
@given(specs=_finding_specs())
def test_change_list_dicts_have_required_shape(specs):
    """Every emitted entry carries the schema-required keys (feeds Property 4)."""
    findings = _materialize(specs)
    for entry in ol.build_change_list(findings, iteration=1).to_change_list():
        for key in ("id", "iteration", "target_document", "implements_findings", "operation", "anchor"):
            assert key in entry
        assert "paragraph_key" in entry["anchor"]
        if entry["operation"] == "delete_paragraph":
            assert "new_text" not in entry


# ==========================================================================
# Oscillation handling (R10.3, R10.4) — design "Oscillation handling"
# ==========================================================================


def test_oscillation_ledger_escalates_reapply_alternate_wontfix():
    """applied -> 1st recurrence reapply -> 2nd alternate -> 3rd wont_fix."""
    ledger = ol.OscillationLedger()
    f = _finding("SF-1", SPELL, CV, "spelling", "high", "p1", "Fix typo")

    # Not previously applied -> not an oscillation.
    assert ledger.observe(f, 1) == "none"

    ledger.mark_applied(f, 1)
    assert ledger.observe(f, 2) == "reapply"
    assert ledger.recurrence_count(f) == 1

    assert ledger.observe(f, 3) == "alternate"
    assert ledger.reverse_anchors() == {(CV, "p1")}

    assert ledger.observe(f, 4) == "wont_fix"
    assert ledger.is_wont_fix(f) is True
    # A wont_fix anchor is no longer reversed.
    assert ledger.reverse_anchors() == set()
    assert ledger.wont_fix_keys() == {ol.dedup_key(f)}

    # Stays wont_fix on any later recurrence.
    assert ledger.observe(f, 5) == "wont_fix"


def test_alternate_resolution_flips_winner_at_that_anchor_only():
    """The 2nd-recurrence alternate reverses the conflict winner for one anchor."""
    hi = _finding("ATS-1", ATS, CV, "ats", "high", "p1", "ATS proposal")
    lo = _finding("LC-1", LANG, CV, "language", "high", "p1", "Language proposal")

    normal = ol.build_change_list([hi, lo], iteration=1)
    assert normal.entries[0].proposed == "ATS proposal"
    assert normal.conflicts[0].alternate_applied is False

    reversed_ = ol.build_change_list(
        [hi, lo], iteration=1, reverse_anchors={(CV, "p1")}
    )
    assert reversed_.entries[0].proposed == "Language proposal"
    assert reversed_.conflicts[0].alternate_applied is True


def test_mark_applied_records_only_first_iteration():
    ledger = ol.OscillationLedger()
    f = _finding("SF-1", SPELL, CV, "spelling", "high", "p1", "Fix")
    ledger.mark_applied(f, 1)
    ledger.mark_applied(f, 5)  # later application must not reset the baseline
    ledger.observe(f, 2)
    dumped = ledger.to_dict()
    assert dumped["entries"][0]["first_applied_iteration"] == 1


# ==========================================================================
# Property 8 — one question at a time — design "Phase QA"
# ==========================================================================


def _questions(n: int) -> list[dict]:
    return [
        {"qid": f"q{i}", "finding_ref": f"JD-{i}", "question": f"Question {i}?"}
        for i in range(n)
    ]


def test_one_question_at_a_time_blocks_next_until_answered():
    queue = ol.QuestionQueue(_questions(2))
    first = queue.next_question()
    assert first["qid"] == "q0"
    with pytest.raises(ol.OneAtATimeError):
        queue.next_question()  # cannot present q1 before q0 is answered

    queue.record_answer("answer zero")
    second = queue.next_question()
    assert second["qid"] == "q1"
    queue.record_answer("answer one")

    assert queue.next_question() is None
    assert not queue.has_pending()
    assert {a["qid"]: a["answer"] for a in queue.answered} == {
        "q0": "answer zero",
        "q1": "answer one",
    }


def test_record_answer_without_outstanding_question_raises():
    queue = ol.QuestionQueue(_questions(1))
    with pytest.raises(ol.OneAtATimeError):
        queue.record_answer("nothing outstanding")


def test_qa_relay_presents_exactly_one_question_at_a_time():
    """Property 8 relay invariant over a full queue drain."""
    queue = ol.QuestionQueue(_questions(5))
    presented: list[str] = []
    while queue.has_pending():
        assert queue.outstanding is None  # nothing in flight before presenting
        current = queue.next_question()
        assert queue.outstanding is current
        with pytest.raises(ol.OneAtATimeError):
            queue.next_question()  # the k+1 guard
        presented.append(current["qid"])
        queue.record_answer(f"ans-{current['qid']}")

    assert presented == [f"q{i}" for i in range(5)]
    assert len(queue.answered) == 5


def test_phase2_followup_questions_never_readd_answered():
    """Phase 2 may append follow-ups, but an already-answered qid is never re-asked."""
    queue = ol.QuestionQueue(_questions(1))
    queue.next_question()
    queue.record_answer("answered q0")
    queue.append_questions([{"qid": "q0"}, {"qid": "q9", "question": "new?"}])
    nxt = queue.next_question()
    assert nxt["qid"] == "q9"  # q0 skipped (already answered)


# ==========================================================================
# Property 5 — accepted-gap exclusion and persistence
# ==========================================================================


def test_accepted_gap_records_verbatim_once_and_excludes_from_gate():
    register = ol.AcceptedGapsRegister()
    gap = _finding("JD-9", JD, CV, "jd_gap", "high", "p1", "Add Kubernetes")

    entry = register.accept(
        gap, "I have no Kubernetes experience.", iteration=2, summary="No k8s"
    )
    assert entry["verbatim_response"] == "I have no Kubernetes experience."
    assert register.is_accepted("JD-9")

    # Record-once: a later accept does not overwrite the verbatim response.
    register.accept(gap, "totally different text", iteration=3)
    assert register.entries()[0]["verbatim_response"] == "I have no Kubernetes experience."

    # The accepted finding is forced to accepted_gap and excluded from gates.
    marked = register.mark_findings([gap])
    assert marked[0]["status"] == "accepted_gap"
    assert ol.is_open(marked[0]) is False
    assert ol.reviewer_gate_status(JD, marked) == "PASS"


def test_exclude_accepted_gaps_drops_accepted_and_wont_fix():
    open_f = _finding("A", ATS, CV, "ats", "high", "p1", "x", status="open")
    accepted = _finding("B", JD, CV, "jd_gap", "high", "p2", "y", status="accepted_gap")
    wont_fix = _finding("C", LANG, CV, "language", "low", "p3", "z", status="wont_fix")
    remaining = ol.exclude_accepted_gaps([open_f, accepted, wont_fix])
    assert {f["id"] for f in remaining} == {"A"}


# ==========================================================================
# Gate evaluation + convergence predicate (Property 6, Property 7 boundary)
# ==========================================================================


@pytest.mark.parametrize(
    "status,expected",
    [
        ("open", True),
        ("verification_failed", True),
        ("applied", False),
        ("already_satisfied", False),
        ("accepted_gap", False),
        ("wont_fix", False),
    ],
)
def test_is_open_status_table(status, expected):
    f = _finding("X", ATS, CV, "ats", "high", "p1", "x", status=status)
    assert ol.is_open(f) is expected


def test_reviewer_gate_fails_on_open_finding():
    f = _finding("A", ATS, CV, "ats", "high", "p1", "x", status="open")
    assert ol.reviewer_gate_status(ATS, [f], None) == "FAIL"


def test_reviewer_gate_passes_when_only_excluded_findings_remain():
    f = _finding("A", ATS, CV, "ats", "high", "p1", "x", status="accepted_gap")
    assert ol.reviewer_gate_status(ATS, [f], None) == "PASS"


def test_hiring_manager_gate_requires_invite():
    assert ol.reviewer_gate_status(HM, [], "INVITE") == "PASS"
    assert ol.reviewer_gate_status(HM, [], "DO_NOT_INVITE") == "FAIL"
    assert ol.reviewer_gate_status(HM, [], None) == "FAIL"


def test_all_gates_pass_requires_every_reviewer():
    by_reviewer = {reviewer: [] for reviewer in ol.REVIEWER_ORDER}
    assert ol.all_gates_pass(by_reviewer, "INVITE") is True
    by_reviewer[ATS] = [_finding("A", ATS, CV, "ats", "high", "p1", "x")]
    assert ol.all_gates_pass(by_reviewer, "INVITE") is False


@pytest.mark.parametrize(
    "counts,limits,expected",
    [
        ({}, {}, True),
        ({CV: 2}, {CV: 2}, True),
        ({CV: 3}, {CV: 2}, False),
        ({CV: 1, LETTER: 1}, {CV: 2, LETTER: 1}, True),
        ({CV: 2}, {}, False),  # missing limit -> cannot be within
    ],
)
def test_pages_within_limits(counts, limits, expected):
    assert ol.pages_within_limits(counts, limits) is expected


def test_convergence_predicate_requires_all_three_conditions():
    gates_pass = {reviewer: [] for reviewer in ol.REVIEWER_ORDER}
    counts, limits = {CV: 2}, {CV: 2}

    assert ol.convergence_predicate(gates_pass, "INVITE", counts, limits) is True
    # Missing INVITE.
    assert ol.convergence_predicate(gates_pass, "DO_NOT_INVITE", counts, limits) is False
    # Page over limit.
    assert ol.convergence_predicate(gates_pass, "INVITE", {CV: 3}, limits) is False
    # A failing gate.
    failing = dict(gates_pass)
    failing[ATS] = [_finding("A", ATS, CV, "ats", "high", "p1", "x")]
    assert ol.convergence_predicate(failing, "INVITE", counts, limits) is False


# ==========================================================================
# Property 6 — single success-termination path (EDIT phase only)
# ==========================================================================


def _passing_gates() -> dict:
    return {reviewer: [] for reviewer in ol.REVIEWER_ORDER}


def test_decide_edit_phase_terminates_success_only_when_predicate_holds():
    result = ol.decide_edit_phase(
        open_findings=[],
        findings_by_reviewer=_passing_gates(),
        recommendation="INVITE",
        page_counts={CV: 2},
        page_limits={CV: 2},
        iteration=4,
    )
    assert result.decision == "TERMINATE_SUCCESS"
    assert result.converged is True
    assert result.change_list.entries == ()


def test_decide_edit_phase_advances_when_pages_over_even_with_empty_change_list():
    """Property 7 boundary: a page over limit blocks success despite a clean REVIEW."""
    result = ol.decide_edit_phase(
        open_findings=[],
        findings_by_reviewer=_passing_gates(),
        recommendation="INVITE",
        page_counts={CV: 3},
        page_limits={CV: 2},
        iteration=4,
    )
    assert result.decision == "ADVANCE_REVIEW"
    assert result.converged is False


def test_decide_edit_phase_advances_when_hiring_manager_not_invite():
    result = ol.decide_edit_phase(
        open_findings=[],
        findings_by_reviewer=_passing_gates(),
        recommendation="DO_NOT_INVITE",
        page_counts={CV: 2},
        page_limits={CV: 2},
        iteration=4,
    )
    assert result.decision == "ADVANCE_REVIEW"


def test_decide_edit_phase_edits_when_open_findings_present():
    """Non-empty Change_List -> EDIT, never a success declaration."""
    finding = _finding("A", ATS, CV, "ats", "high", "p1", "fix it")
    by_reviewer = _passing_gates()
    by_reviewer[ATS] = [finding]
    result = ol.decide_edit_phase(
        open_findings=[finding],
        findings_by_reviewer=by_reviewer,
        recommendation="INVITE",
        page_counts={CV: 2},
        page_limits={CV: 2},
        iteration=1,
    )
    assert result.decision == "EDIT"
    assert result.converged is False
    assert result.change_list.entries


def test_evaluate_phase_length_work_advances_never_terminates():
    """Property 6: EVALUATE derives length work and feeds the next REVIEW/EDIT."""
    length = ol.derive_length_findings({CV: 3}, {CV: 2}, iteration=1)
    assert length and length[0]["category"] == "length"
    assert length[0]["id"] == "LEN-1-CV_Working_Copy"
    assert length[0]["status"] == "open"

    by_reviewer = _passing_gates()
    by_reviewer[ol.LENGTH_REVIEWER] = length
    result = ol.decide_edit_phase(
        open_findings=length,
        findings_by_reviewer=by_reviewer,
        recommendation="INVITE",
        page_counts={CV: 3},
        page_limits={CV: 2},
        iteration=1,
    )
    assert result.decision == "EDIT"  # the length edit must be applied, not declared done


def test_derive_length_findings_only_for_over_limit_documents():
    out = ol.derive_length_findings(
        {CV: 3, LETTER: 1}, {CV: 2, LETTER: 1}, iteration=2
    )
    assert {f["target_document"] for f in out} == {CV}


# ==========================================================================
# Whole-run simulation over recorded fixtures (STUBBED subagents)
# ==========================================================================


def _clean_fixture(recommendation: str = "INVITE", pages: int = 2) -> ol.IterationFixture:
    return ol.IterationFixture(findings=(), recommendation=recommendation, page_counts={CV: pages})


def test_run_converges_immediately_on_clean_review():
    """A first REVIEW with no findings, INVITE, pages within limit -> COMPLETED@1."""
    outcome = ol.simulate_run([_clean_fixture()], page_limits={CV: 2})
    assert outcome.outcome == "COMPLETED"
    assert outcome.final_iteration == 1
    assert outcome.records[-1].decision == "TERMINATE_SUCCESS"


def test_run_with_only_accepted_gap_converges():
    """Property 5 + 6: an accepted gap does not block convergence."""
    accepted = _finding("JD-9", JD, CV, "jd_gap", "high", "p1", "Add k8s", status="accepted_gap")
    fixture = ol.IterationFixture(
        findings=(accepted,), recommendation="INVITE", page_counts={CV: 2}
    )
    outcome = ol.simulate_run([fixture], page_limits={CV: 2})
    assert outcome.outcome == "COMPLETED"
    assert outcome.final_iteration == 1


def test_run_oscillating_finding_is_wont_fixed_then_converges():
    """R10.3/R10.4: a finding that recurs after being applied is wont_fixed at the
    3rd recurrence, which unblocks convergence (Property 6)."""
    osc = _finding("SF-1", SPELL, CV, "spelling", "high", "p1", "Amazon Q", match_text="QuickSuite")
    fixtures = [
        ol.IterationFixture(findings=(dict(osc),), recommendation="INVITE", page_counts={CV: 2})
        for _ in range(4)
    ]
    outcome = ol.simulate_run(fixtures, page_limits={CV: 2})

    assert outcome.outcome == "COMPLETED"
    assert outcome.final_iteration == 4
    # The first three iterations edit; success is declared only at iteration 4.
    assert [r.decision for r in outcome.records] == [
        "EDIT",
        "EDIT",
        "EDIT",
        "TERMINATE_SUCCESS",
    ]
    # The wont_fix escalation happened in iteration 4 for this finding's key.
    assert ol.dedup_key(osc) in set(outcome.records[3].wont_fixed)
    ledger_entries = outcome.oscillation_ledger["entries"]
    assert any(e["status"] == "wont_fix" for e in ledger_entries)


def test_run_does_not_converge_within_iteration_cap():
    """R10.2: distinct unresolved findings every iteration -> DID_NOT_CONVERGE@10."""
    fixtures = [
        ol.IterationFixture(
            findings=(_finding(f"F{n}", ATS, CV, "ats", "high", f"p{n}", f"fix-{n}"),),
            recommendation="INVITE",
            page_counts={CV: 2},
        )
        for n in range(12)
    ]
    outcome = ol.simulate_run(fixtures, page_limits={CV: 2})
    assert outcome.outcome == "DID_NOT_CONVERGE"
    assert outcome.final_iteration == 10
    assert len(outcome.records) == 10
    assert all(r.decision == "EDIT" for r in outcome.records)


def test_run_respects_custom_iteration_cap():
    fixtures = [
        ol.IterationFixture(
            findings=(_finding(f"F{n}", ATS, CV, "ats", "high", f"p{n}", f"fix-{n}"),),
            recommendation="INVITE",
            page_counts={CV: 2},
        )
        for n in range(8)
    ]
    outcome = ol.simulate_run(fixtures, page_limits={CV: 2}, iteration_cap=3)
    assert outcome.outcome == "DID_NOT_CONVERGE"
    assert outcome.final_iteration == 3
    assert len(outcome.records) == 3


def test_run_blocked_by_page_limit_never_completes():
    """Property 6/7: clean reviews but a permanently over-limit page never converges."""
    fixtures = [_clean_fixture(pages=3) for _ in range(10)]
    outcome = ol.simulate_run(fixtures, page_limits={CV: 2})
    assert outcome.outcome == "DID_NOT_CONVERGE"
    # Every iteration sees an empty Change_List but the page gate keeps it advancing.
    assert all(r.decision == "ADVANCE_REVIEW" for r in outcome.records)


def test_success_record_is_always_terminal_and_empty():
    """Property 6: TERMINATE_SUCCESS only ever appears as the final record, with an
    empty Change_List and ``converged`` True."""
    osc = _finding("SF-1", SPELL, CV, "spelling", "high", "p1", "Amazon Q")
    fixtures = [
        ol.IterationFixture(findings=(dict(osc),), recommendation="INVITE", page_counts={CV: 2})
        for _ in range(4)
    ]
    outcome = ol.simulate_run(fixtures, page_limits={CV: 2})
    for index, record in enumerate(outcome.records):
        if record.decision == "TERMINATE_SUCCESS":
            assert index == len(outcome.records) - 1
            assert record.change_list == ()
            assert record.converged is True
        else:
            assert record.converged is False


def test_run_is_deterministic():
    """Identical recorded fixtures always yield the identical RunOutcome."""
    osc = _finding("SF-1", SPELL, CV, "spelling", "high", "p1", "Amazon Q")
    fixtures = [
        ol.IterationFixture(findings=(dict(osc),), recommendation="INVITE", page_counts={CV: 2})
        for _ in range(4)
    ]
    first = ol.simulate_run(fixtures, page_limits={CV: 2})
    second = ol.simulate_run(fixtures, page_limits={CV: 2})
    assert first == second
