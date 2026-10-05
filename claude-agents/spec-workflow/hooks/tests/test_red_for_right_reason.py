"""The red-for-right-reason judge (red_for_right_reason): True = red on a genuine assertion, False otherwise.

The judge reads a captured RED run and must know every assertion vocabulary the project's runners print, or a
genuine red is refused and the implementer is told to "stub the signature" of a symbol that already loads
(measured three times, once per vocabulary added after pytest's). The reverse direction matters as much: a
capture whose failure is a load error, or no failure at all, must stay refused whatever vocabulary it also
happens to contain. Standard library + pytest only; Python 3.9 compatible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import red_for_right_reason as judge_module

PYTEST_ASSERTION = (
    "FAILED test/test_x.py::test_adds - AssertionError: assert 3 == 4\n    assert add(1, 2) == 4\n1 failed in 0.03s\n"
)
#: pytest's short test summary names the node id after `FAILED`; a test that RAN and raised is red on its own
#: logic even when the exception is not an AssertionError.
PYTEST_SHORT_SUMMARY_ONLY = "FAILED test/test_x.py::test_adds - ValueError: bad input\n=== 1 failed in 0.03s ===\n"
HYPOTHESIS_FALSIFICATION = (
    "Falsifying example: test_roundtrip(\n    value=-1,\n)\nhypothesis.errors.Flaky\n1 failed in 0.40s\n"
)
UNITTEST_ASSERTION = "FAIL: test_adds (test_x.TestAdd)\n    self.assertEqual(add(1, 2), 4)\nFAILED (failures=1)\n"
PLAYWRIGHT_WEB_FIRST = (
    "  1) [chromium] › board.spec.ts:12:5 › shows six pieces\n\n"
    "    Error: expect(locator).toHaveCount(expected) failed\n\n"
    "    Locator: getByRole('img')\n    Expected: 6\n    Received: 1\n"
    "    Timeout: 20000ms\n\n  1 failed\n"
)
PLAYWRIGHT_TIMED_OUT = (
    "    Error: Timed out 20000ms waiting for expect(locator).toBeVisible()\n\n"
    "    Locator: getByRole('button', { name: 'Play' })\n    Expected: visible\n    Received: hidden\n  1 failed\n"
)
PLAYWRIGHT_VALUE = (
    "    Error: expect(received).toBe(expected) // Object.is equality\n\n"
    "    Expected: -19\n    Received: -37\n\n  1 failed\n"
)
VITEST_VALUE = (
    " FAIL  test/state/slot.test.ts > take clears the slot\n"
    "AssertionError: expected 2 to be 1 // Object.is equality\n"
    "- Expected\n+ Received\n\n- 1\n+ 2\n\n Test Files  1 failed (1)\n"
)
TESTING_LIBRARY_QUERY = (
    " FAIL  test/routes/editor-view.test.ts > offers the Play control\n"
    'TestingLibraryElementError: Unable to find an accessible element with the role "button" and name '
    '"Play"\n\nHere are the accessible roles:\n  heading:\n\n Test Files  1 failed (1)\n'
)
COLLECTION_ERROR = (
    "==================================== ERRORS ====================================\n"
    "_________________ ERROR collecting test/test_x.py _________________\n"
    "ImportError while importing test module 'test/test_x.py'.\n"
    "ModuleNotFoundError: No module named 'src.adder'\n"
    "=========================== 1 error in 0.20s ===========================\n"
)
COLLECTION_ERROR_WITH_QUERY_TERM = COLLECTION_ERROR + "note: TestingLibraryElementError seen earlier today\n"
ALL_GREEN = "test/test_x.py ....\n4 passed in 0.10s\n"
VITEST_ALL_GREEN = " Test Files  3 passed (3)\n      Tests  41 passed (41)\n"
FAILURE_WITHOUT_VOCABULARY = "Error: the browser crashed before the first test\n  1 failed\n"
TIMEOUT_WITHOUT_ASSERTION = "Test timeout of 30000ms exceeded.\n  1 failed\n"


@pytest.mark.parametrize(
    "capture",
    [
        PYTEST_ASSERTION,
        PYTEST_SHORT_SUMMARY_ONLY,
        HYPOTHESIS_FALSIFICATION,
        UNITTEST_ASSERTION,
        PLAYWRIGHT_WEB_FIRST,
        PLAYWRIGHT_TIMED_OUT,
        PLAYWRIGHT_VALUE,
        VITEST_VALUE,
        TESTING_LIBRARY_QUERY,
    ],
    ids=[
        "pytest-assertion",
        "pytest-short-summary-failed-nodeid",
        "hypothesis-falsifying-example",
        "unittest-self-assert",
        "playwright-web-first-assertion",
        "playwright-timed-out-waiting-for-expect",
        "playwright-value-assertion",
        "vitest-value-assertion",
        "testing-library-query-failure",
    ],
)
def test_a_genuine_falsification_in_each_vocabulary_is_red_for_the_right_reason(capture: str) -> None:
    ok, message = judge_module.judge(capture)
    assert ok, message
    assert "OK" in message


@pytest.mark.parametrize(
    "capture, fragment",
    [
        (COLLECTION_ERROR, "collection/import error dominates"),
        (COLLECTION_ERROR_WITH_QUERY_TERM, "collection/import error dominates"),
        (ALL_GREEN, "no failure detected"),
        (VITEST_ALL_GREEN, "no failure detected"),
        ("", "no failure detected"),
        (FAILURE_WITHOUT_VOCABULARY, "cannot confirm"),
        (TIMEOUT_WITHOUT_ASSERTION, "cannot confirm"),
    ],
    ids=[
        "module-not-found-at-collection",
        "collection-error-is-not-rescued-by-a-query-term",
        "pytest-all-green",
        "vitest-all-green",
        "empty-capture",
        "failure-without-any-assertion-vocabulary",
        "timeout-without-an-assertion",
    ],
)
def test_a_load_error_a_green_run_or_an_unexplained_failure_is_refused(capture: str, fragment: str) -> None:
    ok, message = judge_module.judge(capture)
    assert not ok, message
    assert fragment in message


def test_the_whole_capture_is_read_so_a_late_assertion_counts() -> None:
    """a capture whose first thousand lines are green output and whose assertion comes last is still red"""
    capture = "test/test_x.py::test_ok PASSED\n" * 1000 + PYTEST_ASSERTION
    assert judge_module.judge(capture)[0]


def test_main_exits_0_on_a_right_reason_capture_and_1_otherwise(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    right = tmp_path / "right.txt"
    right.write_bytes(PLAYWRIGHT_VALUE.encode("utf-8"))
    wrong = tmp_path / "wrong.txt"
    wrong.write_bytes(COLLECTION_ERROR.encode("utf-8"))
    assert judge_module.main(["red_for_right_reason.py", str(right)]) == 0
    assert "OK" in capsys.readouterr().out
    assert judge_module.main(["red_for_right_reason.py", str(wrong)]) == 1
    assert "collection/import error dominates" in capsys.readouterr().err


def test_main_exits_1_when_the_capture_file_is_missing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert judge_module.main(["red_for_right_reason.py", str(tmp_path / "absent.txt")]) == 1
    assert "capture file not found" in capsys.readouterr().err
    assert judge_module.main(["red_for_right_reason.py"]) == 1


def test_the_docstring_names_the_four_vocabularies_without_project_specific_wording() -> None:
    docstring = judge_module.__doc__ or ""
    for vocabulary in ("pytest", "Hypothesis", "Playwright", "Vitest", "Testing-Library"):
        assert vocabulary in docstring, vocabulary
    assert "THIS PROJECT" not in docstring and "#" not in docstring.replace("#<", "")
