"""Unit tests for ``page_count.py`` (task 4 / subtask 4.1) — CONTROL FLOW ONLY.

Covers the render-based page-counting layer from the design's "Page-Counting
Layer". Per the design's testing note [C4] and the task brief, these tests
validate the script's *control flow and output shape only* — they do NOT assert
real page numbers. The true page count is exercised by the calibrated-fixture
check on a Word-equipped host (task 18), because it depends on a renderer
actually laying out the document.

The optional, host-specific dependencies (Microsoft Word via win32com,
LibreOffice via ``soffice`` on PATH, ``pypdf``) are reached only through small
indirection functions in ``page_count``:

    _import_win32com / _dispatch_word   -> Word automation
    _discover_soffice / _run_soffice_convert -> LibreOffice headless conversion
    _import_pypdf / _count_pdf_pages    -> PDF page counting

Every test monkeypatches these indirection points, so the suite is fully
deterministic on a host WITHOUT Word, pywin32, LibreOffice, or pypdf and
**never skips/xfails** (per the workspace ``tests-must-not-fail`` rule). No real
renderer is ever invoked; no environment variables are used.

``page_count`` is importable via the path wiring in ``conftest.py``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import page_count as pc


# --------------------------------------------------------------------------
# Fakes for the Word COM object graph (app -> Documents -> Document)
# --------------------------------------------------------------------------


class FakeWordDoc:
    """A fake ``Document`` recording the order of pagination calls."""

    def __init__(self, pages: int, events: list) -> None:
        self._pages = pages
        self.events = events
        self.closed_with = None

    def Repaginate(self) -> None:  # noqa: N802 - mirrors the COM API name
        self.events.append("repaginate")

    def ComputeStatistics(self, which):  # noqa: N802 - mirrors the COM API name
        self.events.append(("compute", which))
        return self._pages

    def Close(self, save_changes):  # noqa: N802 - mirrors the COM API name
        self.events.append(("close", save_changes))
        self.closed_with = save_changes


class FakeDocuments:
    """A fake ``Application.Documents`` collection."""

    def __init__(self, doc: FakeWordDoc, events: list) -> None:
        self._doc = doc
        self.events = events
        self.opened: list[str] = []

    def Open(self, path):  # noqa: N802 - mirrors the COM API name
        self.events.append(("open", str(path)))
        self.opened.append(str(path))
        return self._doc


class FakeWordApp:
    """A fake ``Word.Application`` COM object."""

    def __init__(self, doc: FakeWordDoc, events: list) -> None:
        self.Documents = FakeDocuments(doc, events)
        self.events = events
        self.quit_called = False
        # Settable cosmetic properties the script may assign to.
        self.Visible = None
        self.DisplayAlerts = None

    def Quit(self):  # noqa: N802 - mirrors the COM API name
        self.events.append("quit")
        self.quit_called = True


def _make_word_app(pages: int):
    """Build a fake Word app + its shared event log, returning (app, doc, events)."""
    events: list = []
    doc = FakeWordDoc(pages, events)
    app = FakeWordApp(doc, events)
    return app, doc, events


def _write_dummy_docx(tmp_path: Path, name: str = "cv.working.docx") -> Path:
    """Create a placeholder .docx so the CLI existence check passes.

    The bytes are never parsed (the Word dispatch is faked), so any content is
    fine; this only needs to exist on disk.
    """
    path = tmp_path / name
    path.write_bytes(b"PK\x03\x04 not-a-real-docx")
    return path


# --------------------------------------------------------------------------
# 1) Renderer-absent path exits non-zero with a clear message
# --------------------------------------------------------------------------


def test_count_pages_raises_when_no_renderer(monkeypatch):
    """Word dispatch raising + soffice absent -> NoRendererError (never guesses)."""

    def boom():
        raise RuntimeError("Word not installed")

    monkeypatch.setattr(pc, "_dispatch_word", boom)
    # Exercise the real _discover_soffice with shutil.which forced to find nothing.
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(pc.NoRendererError) as excinfo:
        pc.count_pages("whatever.docx")
    msg = str(excinfo.value).lower()
    assert "no page renderer" in msg
    assert "never be guessed" in msg


def test_cli_no_renderer_exits_with_documented_code(monkeypatch, tmp_path, capsys):
    """The CLI exits EXIT_NO_RENDERER with a clear stderr message and writes no file."""

    def boom():
        raise RuntimeError("Word not installed")

    monkeypatch.setattr(pc, "_dispatch_word", boom)
    monkeypatch.setattr(shutil, "which", lambda name: None)

    docx = _write_dummy_docx(tmp_path)
    out = tmp_path / "page_counts.json"
    rc = pc.main([str(docx), "--out", str(out)])

    assert rc == pc.EXIT_NO_RENDERER
    err = capsys.readouterr().err
    assert "no page renderer" in err.lower()
    assert "word" in err.lower() and "libreoffice" in err.lower()
    # A fatal "cannot measure" must not leave a (misleading) results file behind.
    assert not out.exists()


def test_cli_no_renderer_via_discover_indirection(monkeypatch, tmp_path, capsys):
    """Same outcome when the higher-level soffice-discovery indirection is faked."""

    def boom():
        raise RuntimeError("Word not installed")

    monkeypatch.setattr(pc, "_dispatch_word", boom)
    monkeypatch.setattr(pc, "_discover_soffice", lambda: None)

    docx = _write_dummy_docx(tmp_path)
    out = tmp_path / "page_counts.json"
    rc = pc.main([str(docx), "--out", str(out)])

    assert rc == pc.EXIT_NO_RENDERER
    assert "no page renderer" in capsys.readouterr().err.lower()


# --------------------------------------------------------------------------
# 2) Word path: JSON output shape + Repaginate-before-ComputeStatistics +
#    close-without-saving
# --------------------------------------------------------------------------


def test_word_count_pages_shape_and_call_order(monkeypatch):
    """count_pages returns the documented shape and drives Word correctly."""
    app, doc, events = _make_word_app(pages=2)
    monkeypatch.setattr(pc, "_dispatch_word", lambda: app)

    result = pc.count_pages("cv.working.docx")

    # Documented per-document shape/fields/method.
    assert result == {
        "document": "cv.working.docx",
        "pages": 2,
        "method": pc.METHOD_WORD,
    }
    assert set(result) == {"document", "pages", "method"}
    assert isinstance(result["pages"], int)

    # Repaginate() ran before ComputeStatistics(...).
    assert "repaginate" in events
    compute_event = ("compute", pc.WD_STATISTIC_PAGES)
    assert compute_event in events
    assert events.index("repaginate") < events.index(compute_event)

    # ComputeStatistics was asked for the *pages* statistic specifically.
    assert any(e == ("compute", pc.WD_STATISTIC_PAGES) for e in events)

    # Closed WITHOUT saving, and Word was quit.
    assert ("close", pc.WD_DO_NOT_SAVE_CHANGES) in events
    assert doc.closed_with == pc.WD_DO_NOT_SAVE_CHANGES
    assert app.quit_called is True


def test_cli_word_path_writes_json_line_and_file(monkeypatch, tmp_path, capsys):
    """The CLI prints one JSON line per doc and writes page_counts.json (list)."""
    app, doc, events = _make_word_app(pages=2)
    monkeypatch.setattr(pc, "_dispatch_word", lambda: app)

    docx = _write_dummy_docx(tmp_path)
    out = tmp_path / "page_counts.json"
    rc = pc.main([str(docx), "--out", str(out)])
    assert rc == pc.EXIT_OK

    # stdout: exactly one JSON line, with the documented shape.
    stdout_lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(stdout_lines) == 1
    line = json.loads(stdout_lines[0])
    assert line == {"document": str(docx), "pages": 2, "method": pc.METHOD_WORD}

    # page_counts.json: a JSON list whose single entry matches the line.
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert payload == [{"document": str(docx), "pages": 2, "method": pc.METHOD_WORD}]

    # Pagination contract still holds end-to-end through the CLI.
    assert events.index("repaginate") < events.index(("compute", pc.WD_STATISTIC_PAGES))
    assert ("close", pc.WD_DO_NOT_SAVE_CHANGES) in events
    assert app.quit_called is True


def test_cli_word_path_multiple_documents(monkeypatch, tmp_path, capsys):
    """Multiple docx inputs -> one JSON line each and a multi-entry results file."""
    # A fresh fake app per dispatch so each document opens cleanly.
    apps = [_make_word_app(pages=2)[0], _make_word_app(pages=1)[0]]
    calls = {"n": 0}

    def dispatch():
        app = apps[calls["n"]]
        calls["n"] += 1
        return app

    monkeypatch.setattr(pc, "_dispatch_word", dispatch)

    cv = _write_dummy_docx(tmp_path, "cv.working.docx")
    letter = _write_dummy_docx(tmp_path, "letter.working.docx")
    out = tmp_path / "page_counts.json"
    rc = pc.main([str(cv), str(letter), "--out", str(out)])
    assert rc == pc.EXIT_OK

    stdout_lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(stdout_lines) == 2

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload == [
        {"document": str(cv), "pages": 2, "method": pc.METHOD_WORD},
        {"document": str(letter), "pages": 1, "method": pc.METHOD_WORD},
    ]


def test_word_quit_runs_even_when_open_fails(monkeypatch):
    """If opening the document raises, Word is still quit (no orphaned process)."""
    events: list = []

    class ExplodingDocuments:
        def Open(self, path):  # noqa: N802 - mirrors the COM API name
            events.append(("open", str(path)))
            raise RuntimeError("cannot open document")

    class App:
        def __init__(self):
            self.Documents = ExplodingDocuments()
            self.Visible = None
            self.DisplayAlerts = None
            self.quit_called = False

        def Quit(self):  # noqa: N802 - mirrors the COM API name
            events.append("quit")
            self.quit_called = True

    app = App()
    monkeypatch.setattr(pc, "_dispatch_word", lambda: app)

    with pytest.raises(RuntimeError, match="cannot open document"):
        pc.count_pages("cv.working.docx")
    # The finally-block cleanup must have quit Word despite the failure.
    assert app.quit_called is True
    assert "quit" in events


# --------------------------------------------------------------------------
# 3) LibreOffice fallback path: shape + method == "libreoffice+pypdf"
# --------------------------------------------------------------------------


def test_libreoffice_fallback_shape(monkeypatch, tmp_path):
    """Word absent + fake soffice/pypdf -> method libreoffice+pypdf with right shape."""

    def boom():
        raise RuntimeError("Word not installed")

    monkeypatch.setattr(pc, "_dispatch_word", boom)
    monkeypatch.setattr(pc, "_discover_soffice", lambda: "soffice-fake")

    def fake_convert(soffice, docx_path, outdir):
        # Mimic LibreOffice producing <stem>.pdf in the (real, temp) outdir so
        # the existence check in _count_pages_libreoffice passes.
        assert soffice == "soffice-fake"
        pdf = Path(outdir) / f"{Path(docx_path).stem}.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        return pdf

    monkeypatch.setattr(pc, "_run_soffice_convert", fake_convert)

    class FakePdfReader:
        def __init__(self, path):
            self.path = path
            self.pages = [object(), object(), object()]  # 3 pages

    # Fake the pypdf import so _count_pdf_pages' real wiring (len(reader.pages))
    # is exercised without pypdf installed.
    monkeypatch.setattr(pc, "_import_pypdf", lambda: FakePdfReader)

    result = pc.count_pages("letter.working.docx")
    assert result == {
        "document": "letter.working.docx",
        "pages": 3,
        "method": pc.METHOD_LIBREOFFICE,
    }
    assert set(result) == {"document", "pages", "method"}


def test_cli_libreoffice_fallback_writes_results(monkeypatch, tmp_path, capsys):
    """End-to-end CLI through the fallback path emits the libreoffice+pypdf shape."""

    monkeypatch.setattr(pc, "_dispatch_word", lambda: (_ for _ in ()).throw(RuntimeError("no word")))
    monkeypatch.setattr(pc, "_discover_soffice", lambda: "soffice-fake")

    def fake_convert(soffice, docx_path, outdir):
        pdf = Path(outdir) / f"{Path(docx_path).stem}.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        return pdf

    monkeypatch.setattr(pc, "_run_soffice_convert", fake_convert)

    class FakePdfReader:
        def __init__(self, path):
            self.pages = [object(), object()]  # 2 pages

    monkeypatch.setattr(pc, "_import_pypdf", lambda: FakePdfReader)

    docx = _write_dummy_docx(tmp_path)
    out = tmp_path / "page_counts.json"
    rc = pc.main([str(docx), "--out", str(out)])
    assert rc == pc.EXIT_OK

    line = json.loads(capsys.readouterr().out.strip())
    assert line == {"document": str(docx), "pages": 2, "method": pc.METHOD_LIBREOFFICE}
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload == [{"document": str(docx), "pages": 2, "method": pc.METHOD_LIBREOFFICE}]


def test_cli_fallback_missing_pypdf_exits_naming_package(monkeypatch, tmp_path, capsys):
    """Fallback chosen but pypdf missing -> EXIT_MISSING_DEPENDENCY naming pypdf."""

    monkeypatch.setattr(pc, "_dispatch_word", lambda: (_ for _ in ()).throw(RuntimeError("no word")))
    monkeypatch.setattr(pc, "_discover_soffice", lambda: "soffice-fake")

    def fake_convert(soffice, docx_path, outdir):
        pdf = Path(outdir) / f"{Path(docx_path).stem}.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        return pdf

    monkeypatch.setattr(pc, "_run_soffice_convert", fake_convert)

    def boom_import():
        raise ModuleNotFoundError("No module named 'pypdf'", name="pypdf")

    monkeypatch.setattr(pc, "_import_pypdf", boom_import)

    docx = _write_dummy_docx(tmp_path)
    out = tmp_path / "page_counts.json"
    rc = pc.main([str(docx), "--out", str(out)])
    assert rc == pc.EXIT_MISSING_DEPENDENCY
    assert "pypdf" in capsys.readouterr().err
    assert not out.exists()


# --------------------------------------------------------------------------
# CLI argument / input validation (control flow)
# --------------------------------------------------------------------------


def test_cli_missing_input_exits_nonzero(monkeypatch, tmp_path, capsys):
    """A non-existent input docx exits EXIT_INPUT_NOT_FOUND before any renderer runs."""
    # Guard: the renderer must never be touched for a missing input.
    def fail():
        raise AssertionError("renderer must not be invoked for a missing input")

    monkeypatch.setattr(pc, "_dispatch_word", fail)

    out = tmp_path / "page_counts.json"
    rc = pc.main([str(tmp_path / "does_not_exist.docx"), "--out", str(out)])
    assert rc == pc.EXIT_INPUT_NOT_FOUND
    assert "not found" in capsys.readouterr().err.lower()
    assert not out.exists()
