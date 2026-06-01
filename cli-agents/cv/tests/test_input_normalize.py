"""Unit tests for ``input_normalize.py`` (task 3 / subtask 3.1).

Covers the multi-format -> Normalized_Text layer from the design's "Input
Normalization Layer":

* each format dispatches and extracts the expected text
  (.docx, .html, .md, .txt with real libraries; .pdf via the dispatch +
  extraction-path wiring and the missing-library exit path);
* messy HTML (irregular whitespace / newlines / tags) collapses to clean text;
* a missing optional library exits non-zero with a message naming the *pip
  package* (monkeypatch the lazy importer to raise ModuleNotFoundError).

Optional-library status is detected at import time so the suite is deterministic
on any host and **never skips/xfails** (per the workspace ``tests-must-not-fail``
steering rule):

* where a library is installed (bs4, python-docx here), the real extraction
  path is asserted directly;
* the missing-library exit path is always exercised by forcing the lazy
  importer to raise ``ModuleNotFoundError`` via monkeypatch, which is
  deterministic regardless of what is actually installed;
* the ``.pdf`` extraction-path wiring (extract_text -> light whitespace
  normalization) is asserted by injecting a deterministic stub extractor
  through the same lazy-import indirection, so it holds whether or not
  ``pdfminer.six`` is installed.

No environment variables are used; ``input_normalize`` is importable via the
path wiring in ``conftest.py``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

import input_normalize as n

# Detected, not used to skip anything: only to choose which assertions are
# "real extraction" vs. which rely on the deterministic monkeypatched importer.
_BS4_AVAILABLE = importlib.util.find_spec("bs4") is not None
_DOCX_AVAILABLE = importlib.util.find_spec("docx") is not None
_PDFMINER_AVAILABLE = importlib.util.find_spec("pdfminer") is not None


# --------------------------------------------------------------------------
# dispatch table
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, handler",
    [
        ("sample.docx", n.normalize_docx),
        ("sample.pdf", n.normalize_pdf),
        ("sample.html", n.normalize_html),
        ("sample.htm", n.normalize_html),
        ("sample.md", n.normalize_text_file),
        ("sample.txt", n.normalize_text_file),
        ("SAMPLE.HTML", n.normalize_html),  # case-insensitive extension
    ],
)
def test_dispatch_routes_by_extension(name, handler, monkeypatch, tmp_path):
    """``normalize`` selects the per-format handler purely from the extension."""
    called = {}

    def spy(path):
        called["path"] = Path(path)
        return "STUB"

    # Patch the handler the dispatch table points at for this extension.
    ext = Path(name).suffix.lower()
    monkeypatch.setitem(n._DISPATCH, ext, spy)

    target = tmp_path / name
    target.write_bytes(b"")  # existence not required by normalize(), but harmless
    assert n.normalize(target) == "STUB"
    assert called["path"] == target


def test_unsupported_extension_raises():
    with pytest.raises(n.UnsupportedFormatError) as excinfo:
        n.normalize("resume.rtf")
    assert ".rtf" in str(excinfo.value)


# --------------------------------------------------------------------------
# .txt / .md passthrough (no optional library required)
# --------------------------------------------------------------------------


def test_txt_passthrough_extracts_expected_text(fixture_path):
    text = n.normalize(fixture_path("sample_jd.txt"))
    assert text.startswith("Senior Backend Engineer")
    assert "Strong Python and SQL skills." in text
    assert "Experience with Kubernetes is a plus." in text
    assert text.endswith("\n")
    # No carriage returns survive normalization.
    assert "\r" not in text


def test_md_passthrough_preserves_markdown_structure(fixture_path):
    text = n.normalize(fixture_path("sample_database.md"))
    assert "# Bullet Point Database - Alex Morgan" in text
    assert "## Skills" in text
    # Bullet indentation / markers are preserved (passthrough, not stripped).
    assert "- Python (5 years), SQL, AWS (EC2, S3, Lambda, RDS)" in text
    assert text.endswith("\n")


def test_light_normalize_collapses_blank_runs_and_trailing_ws():
    raw = "Title\r\n\r\n\r\n\r\nBody line   \r\n\r\n\r\nTail\n\n\n"
    out = n._light_normalize(raw)
    assert out == "Title\n\nBody line\n\nTail\n"
    assert "\r" not in out


def test_light_normalize_empty_input_yields_empty_string():
    assert n._light_normalize("") == ""
    assert n._light_normalize("   \n\n  \n") == ""


# --------------------------------------------------------------------------
# .html extraction + messy-whitespace collapse (bs4 installed here)
# --------------------------------------------------------------------------


def test_html_fixture_strips_tags_and_collapses(fixture_path):
    assert _BS4_AVAILABLE, "bs4 expected installed in this environment"
    text = n.normalize(fixture_path("sample_jd.html"))
    # Tag markup is gone.
    assert "<" not in text and ">" not in text
    # The doctype declaration must not leak into the text surface.
    assert "doctype" not in text.lower()
    # A sentence that was line-wrapped across source lines is rejoined.
    assert (
        "Globex Systems is hiring a Senior Backend Engineer to design and "
        "operate the services behind our data platform." in text
    )
    assert "Strong Python and SQL skills." in text
    assert "Experience with Kubernetes is a plus." in text


def test_html_to_text_collapses_messy_whitespace():
    messy = (
        "<html>\n  <head><title>ignored</title>"
        "<style>.x{color:red}</style></head>\n"
        "  <body>\n"
        "    <h1>   Messy    Heading   </h1>\n\n\n"
        "    <p>This   sentence\n   is   split\tacross\n\nlines\n"
        "       and   tabs.</p>\r\n"
        "    <script>var ignored = 1;</script>\n"
        "    <ul>\n<li>  First   item </li>\n<li>Second\titem</li>\n</ul>\n"
        "  </body>\n</html>"
    )
    out = n.html_to_text(messy)
    lines = out.splitlines()
    # script/style/head/title content is dropped.
    assert "ignored" not in out
    assert "color:red" not in out
    # Each block collapses to a single clean line with single spaces.
    assert "Messy Heading" in lines
    assert "This sentence is split across lines and tabs." in lines
    assert "First item" in lines
    assert "Second item" in lines
    # No blank lines, no leading/trailing whitespace on any line.
    assert all(line == line.strip() and line for line in lines)
    assert out.endswith("\n")


def test_html_empty_body_yields_empty_string():
    assert n.html_to_text("<html><body>   \n\t </body></html>") == ""


# --------------------------------------------------------------------------
# .docx extraction (python-docx installed here)
# --------------------------------------------------------------------------


def test_docx_extracts_markdown_surface(fixture_path):
    assert _DOCX_AVAILABLE, "python-docx expected installed in this environment"
    text = n.normalize(fixture_path("sample_cv.docx"))
    # Reuses docx_normalize.to_markdown -> heading + bullet surface, no anchors.
    assert "# Alex Morgan" in text
    assert "## Professional Experience" in text
    assert "- Designed and shipped a service that processes one million events per day." in text


# --------------------------------------------------------------------------
# .pdf — dispatch + extraction-path wiring + missing-library path
# --------------------------------------------------------------------------


def test_pdf_extraction_path_applies_light_normalization(monkeypatch):
    """normalize_pdf feeds pdfminer output through light whitespace normalization.

    Injects a deterministic stub extractor through the lazy-import indirection
    so this asserts input_normalize's own pdf-branch wiring (the part we own)
    regardless of whether pdfminer.six is installed.
    """
    messy_pdf_text = "Heading line\r\n\r\n\r\n\r\nBody  text here\x0c\n\n\nTail\n"

    def fake_importer():
        def extract_text(path):  # signature matches pdfminer.high_level.extract_text
            return messy_pdf_text

        return extract_text

    monkeypatch.setattr(n, "_import_pdfminer_extract_text", fake_importer)
    out = n.normalize_pdf("anything.pdf")
    # Form feed becomes a newline, blank runs collapse, single trailing newline.
    assert out == "Heading line\n\nBody  text here\n\nTail\n"


def test_pdf_missing_pdfminer_raises_missing_dependency(monkeypatch):
    def boom():
        raise ModuleNotFoundError("No module named 'pdfminer'", name="pdfminer")

    monkeypatch.setattr(n, "_import_pdfminer_extract_text", boom)
    with pytest.raises(n.MissingDependencyError) as excinfo:
        n.normalize_pdf("whatever.pdf")
    assert excinfo.value.package == "pdfminer.six"
    assert "pdfminer.six" in str(excinfo.value)


def test_cli_pdf_missing_library_exits_nonzero_naming_package(monkeypatch, tmp_path, capsys):
    def boom():
        raise ModuleNotFoundError("No module named 'pdfminer'", name="pdfminer")

    monkeypatch.setattr(n, "_import_pdfminer_extract_text", boom)
    pdf = tmp_path / "jd.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")  # must exist to pass the not-found check
    rc = n.main([str(pdf), str(tmp_path / "out.md")])
    assert rc == n.EXIT_MISSING_DEPENDENCY
    err = capsys.readouterr().err
    assert "pdfminer.six" in err
    # The failed normalization must not have written an output file.
    assert not (tmp_path / "out.md").exists()


# --------------------------------------------------------------------------
# missing-library path for the other heavy libs (deterministic via monkeypatch)
# --------------------------------------------------------------------------


def test_html_missing_bs4_raises_missing_dependency(monkeypatch):
    def boom():
        raise ModuleNotFoundError("No module named 'bs4'", name="bs4")

    monkeypatch.setattr(n, "_import_beautifulsoup", boom)
    with pytest.raises(n.MissingDependencyError) as excinfo:
        n.html_to_text("<p>hello</p>")
    assert excinfo.value.package == "beautifulsoup4"
    assert "beautifulsoup4" in str(excinfo.value)


def test_cli_html_missing_library_exits_nonzero(monkeypatch, tmp_path, capsys, fixture_path):
    def boom():
        raise ModuleNotFoundError("No module named 'bs4'", name="bs4")

    monkeypatch.setattr(n, "_import_beautifulsoup", boom)
    rc = n.main([str(fixture_path("sample_jd.html")), str(tmp_path / "out.md")])
    assert rc == n.EXIT_MISSING_DEPENDENCY
    assert "beautifulsoup4" in capsys.readouterr().err


def test_docx_missing_python_docx_raises_missing_dependency(monkeypatch):
    def boom():
        raise ModuleNotFoundError("No module named 'docx'", name="docx")

    monkeypatch.setattr(n, "_import_docx_document", boom)
    with pytest.raises(n.MissingDependencyError) as excinfo:
        n.normalize_docx("whatever.docx")
    assert excinfo.value.package == "python-docx"
    assert "python-docx" in str(excinfo.value)


# --------------------------------------------------------------------------
# CLI happy paths + error exits (real subprocess, real libraries)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_name, must_contain",
    [
        ("sample_jd.txt", "Senior Backend Engineer"),
        ("sample_database.md", "## Skills"),
        ("sample_jd.html", "Strong Python and SQL skills."),
        ("sample_cv.docx", "# Alex Morgan"),
    ],
)
def test_cli_writes_normalized_output(fixture_name, must_contain, fixture_path, tmp_path, scripts_dir):
    out_md = tmp_path / "normalized.md"
    result = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / "input_normalize.py"),
            str(fixture_path(fixture_name)),
            str(out_md),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert Path(payload["normalized_md"]) == out_md
    assert payload["format"] == Path(fixture_name).suffix.lower()
    assert out_md.exists()
    assert must_contain in out_md.read_text(encoding="utf-8")


def test_cli_missing_input_exits_nonzero(tmp_path, scripts_dir):
    result = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / "input_normalize.py"),
            str(tmp_path / "does_not_exist.txt"),
            str(tmp_path / "out.md"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == n.EXIT_INPUT_NOT_FOUND
    assert "not found" in result.stderr.lower()


def test_cli_unsupported_format_exits_nonzero(tmp_path, scripts_dir):
    bad = tmp_path / "resume.rtf"
    bad.write_text("not supported", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / "input_normalize.py"),
            str(bad),
            str(tmp_path / "out.md"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == n.EXIT_UNSUPPORTED_FORMAT
    assert ".rtf" in result.stderr
