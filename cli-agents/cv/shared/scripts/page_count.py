"""page_count.py — render-based, reliable page counting (task 4).

Part of the deterministic Python core of the CV Customizer Agent Suite. The
orchestrator runs this during the EVALUATE phase to measure the rendered page
count of each Working Copy, because the Page_Constraint is a *hard* convergence
gate [R11.1, R11.6, Property 7] and a `.docx` does not store soft (rendered)
page breaks — only a renderer can report the true count (design "Page-Counting
Layer").

Why render, not parse
---------------------
``python-docx`` cannot report page count: Word computes soft page breaks at
layout time from fonts, margins, and the rendering engine. Counting only hard
page breaks would massively undercount, which is unacceptable for a gate that
can silently pass an over-length CV. So we render, then count.

Engines (in priority order)
---------------------------
1. **Microsoft Word automation (primary, ``method": "word-com"``).** Via
   ``win32com.client.Dispatch("Word.Application")``: open the document, call
   ``Document.Repaginate()`` and let pagination settle, read
   ``ComputeStatistics(wdStatisticPages)`` (``wdStatisticPages = 2``), then close
   the document WITHOUT saving and quit Word. Word is authoritative because the
   candidate edits the document in Word downstream, so the gated count matches
   exactly what the candidate sees. ``Repaginate()`` before ``ComputeStatistics``
   avoids a stale/background-computed count on a hard gate [D-11].
2. **LibreOffice + pypdf (fallback, ``method": "libreoffice+pypdf"``).** When
   Word automation is unavailable, convert headless with
   ``soffice --headless --convert-to pdf --outdir <tmp> <docx>`` (``soffice``
   discovered on PATH via ``shutil.which`` — never via environment variables),
   then count PDF pages with ``pypdf``.
3. **Neither available → fail fast.** If neither renderer can run, the script
   exits non-zero (``EXIT_NO_RENDERER``) with a clear message. The page count is
   NEVER guessed for the hard gate; the orchestrator surfaces this as a FATAL
   setup error telling the user to install Word or LibreOffice.

Monkeypatchable indirection points (for deterministic tests)
------------------------------------------------------------
The optional, host-specific dependencies are reached only through small
indirection functions, imported lazily inside the branch that needs them, so
the module imports cleanly on a host with no Word, pywin32, LibreOffice, or
pypdf, and so tests can simulate every renderer-present / renderer-absent
combination without touching a real renderer:

    _import_win32com()       -> the win32com.client module
    _dispatch_word()         -> a live Word.Application COM object
    _discover_soffice()      -> path to the soffice executable, or None
    _run_soffice_convert(...) -> path to the produced PDF
    _import_pypdf()          -> the pypdf.PdfReader class
    _count_pdf_pages(pdf)    -> page count of a PDF

NOTE: monkeypatched tests validate this script's control flow and output shape
ONLY. They do NOT validate the real page number — that depends on a renderer
actually laying out the document, and is covered by the calibrated-fixture
check on a Word-equipped host (task 18) [C4].

CLI
---
    python page_count.py <docx> [<docx> ...] --out <page_counts.json>

Prints one JSON line per document to stdout and writes the aggregated list to
``page_counts.json``. Per-document shape:

    {"document": <path>, "pages": N, "method": "word-com" | "libreoffice+pypdf"}

Importable API (so the orchestrator and tests can call directly)
----------------------------------------------------------------
    count_pages(docx_path) -> dict     # tries Word, then LibreOffice; or raises
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

# Exit codes (distinct so callers/tests can tell failure modes apart). These
# mirror input_normalize.py's convention: 0 ok, 2 input-not-found, 3
# missing-dependency, and add 5/6 for the render-specific failure modes.
EXIT_OK = 0
EXIT_INPUT_NOT_FOUND = 2
EXIT_MISSING_DEPENDENCY = 3
EXIT_NO_RENDERER = 5
EXIT_RENDER_FAILED = 6

# Method labels emitted in the per-document result (design "render then count").
METHOD_WORD = "word-com"
METHOD_LIBREOFFICE = "libreoffice+pypdf"

# Microsoft Word enumeration constants we rely on (avoids needing the generated
# COM constants module, which is not present until Word is dispatched once).
WD_STATISTIC_PAGES = 2  # wdStatisticPages
WD_DO_NOT_SAVE_CHANGES = 0  # wdDoNotSaveChanges

# Transient Word-COM fault handling. Word automation is an out-of-process RPC
# server; when several documents are measured in quick succession a prior Word
# instance may still be tearing down, and ``win32com`` then surfaces a transient
# RPC fault (e.g. "The server threw an exception" / "call was rejected by
# callee" — HRESULTs 0x800706be / 0x800706ba, or an ``AttributeError`` while the
# COM object's type info is still unavailable). These are NOT "Word is
# unavailable"; a fresh dispatch a moment later succeeds. Because the page count
# is a hard convergence gate [R11.6, Property 7], we retry the WHOLE Word
# open→repaginate→count cycle on a fresh dispatch a small, bounded number of
# times before concluding anything. A clean "cannot start Word at all" still
# falls back to LibreOffice immediately (see ``_count_pages_word``).
WORD_TRANSIENT_RETRIES = 3  # attempts AFTER the first (so up to 4 total)
WORD_TRANSIENT_BACKOFF_SECONDS = 0.75  # base delay, multiplied by the attempt #

# Candidate executable names for the LibreOffice headless converter.
_SOFFICE_NAMES = ("soffice", "soffice.exe")


# --- errors ----------------------------------------------------------------


class PageCountError(RuntimeError):
    """Base class for page-count failures surfaced to the CLI."""


class WordUnavailableError(PageCountError):
    """Microsoft Word automation could not be started.

    Internal control-flow signal only: it triggers the LibreOffice fallback and
    is never surfaced to the user on its own (the user sees NoRendererError only
    when *both* engines are unavailable).
    """


class WordTransientError(PageCountError):
    """A dispatched Word instance threw a transient COM/RPC fault mid-operation.

    Internal control-flow signal only: Word *did* start, but a call against it
    failed in a way that a fresh dispatch a moment later is expected to recover
    from (e.g. a still-tearing-down prior instance). ``_count_pages_word``
    retries on a fresh dispatch a bounded number of times; it never reaches the
    user or the fallback selector directly.
    """


class NoRendererError(PageCountError):
    """Neither Microsoft Word nor LibreOffice is available to render the document.

    This is fatal: the page count is a hard gate and must never be guessed.
    """


class RenderError(PageCountError):
    """A renderer was available but failed to produce a paginated artifact."""


class MissingDependencyError(PageCountError):
    """A required third-party library is not installed.

    Carries the *pip package* name (``pypdf``) so the user is told exactly what
    to install. Mirrors the analogous error in ``input_normalize.py``.
    """

    def __init__(self, package: str, cause: Optional[BaseException] = None) -> None:
        self.package = package
        message = (
            f"required package not installed: {package}. "
            f"Install '{package}' in this Python environment and re-run. "
            "This script does not install packages."
        )
        super().__init__(message)
        if cause is not None:
            self.__cause__ = cause


# --- lazy dependency / renderer indirection points (monkeypatchable) -------


def _import_win32com():
    """Import indirection for pywin32's ``win32com.client`` (lazy)."""
    import win32com.client as client  # noqa: WPS433 (intentional local import)

    return client


def _dispatch_word():
    """Return a live ``Word.Application`` COM object.

    Separated from :func:`_import_win32com` so tests can simulate "pywin32
    present but Word not installed" (dispatch raises) vs. "pywin32 absent"
    (import raises) — and so the happy path can be faked deterministically.
    """
    client = _import_win32com()
    return client.Dispatch("Word.Application")


def _discover_soffice() -> Optional[str]:
    """Locate the LibreOffice ``soffice`` executable on PATH.

    Uses :func:`shutil.which` only — a PATH lookup, never an environment
    variable read for configuration (per the no-env-vars rule). Returns the
    resolved path string, or ``None`` when LibreOffice is not on PATH.
    """
    import shutil

    for name in _SOFFICE_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def _run_soffice_convert(soffice: str, docx_path: Path, outdir: Path) -> Path:
    """Convert ``docx_path`` to PDF headlessly with LibreOffice; return the PDF path.

    Indirection point so tests can simulate the conversion deterministically
    without a LibreOffice install.
    """
    cmd = [
        str(soffice),
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(outdir),
        str(docx_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RenderError(
            f"LibreOffice conversion failed (exit {proc.returncode}) for {docx_path}: "
            f"{proc.stderr.strip()}"
        )
    return Path(outdir) / f"{Path(docx_path).stem}.pdf"


def _import_pypdf():
    """Import indirection for ``pypdf`` (lazy; only the fallback path needs it)."""
    from pypdf import PdfReader

    return PdfReader


def _count_pdf_pages(pdf_path) -> int:
    """Count pages in a PDF via pypdf.

    Raises :class:`MissingDependencyError` naming ``pypdf`` when the library is
    not installed.
    """
    try:
        PdfReader = _import_pypdf()
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("pypdf", exc) from exc
    reader = PdfReader(str(pdf_path))
    return len(reader.pages)


# --- per-engine page counting ----------------------------------------------


def _is_transient_com_fault(exc: BaseException) -> bool:
    """True for Word COM/RPC faults a fresh dispatch is likely to recover from.

    Two fault shapes are observed when several documents are measured in quick
    succession against a single Word automation server:

    * ``AttributeError`` from ``win32com`` dynamic dispatch (e.g.
      ``Word.Application.Documents``) — raised while the COM object's type info
      is momentarily unavailable on a still-initializing / tearing-down server.
    * ``pywintypes.com_error`` — an RPC-level fault such as "the server threw an
      exception" / "call was rejected by callee" (HRESULTs 0x800706be /
      0x800706ba). Matched by class name so ``pywintypes`` need not be imported
      at module load (it is absent on non-Windows hosts).

    A genuine non-COM error (e.g. a plain ``RuntimeError`` from a bad document)
    is NOT transient and is allowed to propagate.
    """
    if isinstance(exc, AttributeError):
        return True
    cls = type(exc)
    return cls.__name__ == "com_error" and "pywintypes" in getattr(cls, "__module__", "")


def _count_pages_word_once(docx_path) -> int:
    """One Microsoft Word automation attempt: open → repaginate → count.

    Opens the document, repaginates so the count is fresh (not stale or
    background-computed), reads ``ComputeStatistics(wdStatisticPages)``, then
    always closes the document WITHOUT saving and quits Word — even on error.

    Failure classification:

    * Raises :class:`WordUnavailableError` when Word automation cannot be
      *started* (pywin32 missing or Word not installed) — a clean signal to fall
      back to LibreOffice.
    * Raises :class:`WordTransientError` when Word started but a subsequent COM
      call faulted transiently (see :func:`_is_transient_com_fault`) — a signal
      to retry on a fresh dispatch.
    * Lets any other mid-operation exception propagate unchanged.
    """
    try:
        app = _dispatch_word()
    except Exception as exc:  # noqa: BLE001 - any dispatch failure means "no Word"
        raise WordUnavailableError(
            "Microsoft Word automation is unavailable "
            "(pywin32 missing or Word not installed)"
        ) from exc

    doc = None
    try:
        # Keep Word silent and non-blocking; harmless if a property is absent.
        try:
            app.Visible = False
            app.DisplayAlerts = False
        except Exception:  # noqa: BLE001 - cosmetic only; never fail the count on this
            pass

        doc = app.Documents.Open(str(Path(docx_path).resolve()))
        # Repaginate BEFORE reading statistics so the count reflects the current
        # layout, then read the authoritative page count.
        doc.Repaginate()
        pages = int(doc.ComputeStatistics(WD_STATISTIC_PAGES))
        return pages
    except Exception as exc:  # noqa: BLE001 - classify; Word already started
        # Word was dispatched (we got past _dispatch_word), so a transient COM
        # fault here is NOT "Word unavailable" — surface it as transient so the
        # caller retries on a fresh dispatch rather than guessing. Non-COM errors
        # propagate unchanged.
        if _is_transient_com_fault(exc):
            raise WordTransientError(
                f"Microsoft Word automation faulted transiently for {docx_path}: {exc}"
            ) from exc
        raise
    finally:
        # Close without saving and quit, regardless of success/failure, so we
        # never leave an orphaned Word process or mutate the document.
        if doc is not None:
            try:
                doc.Close(WD_DO_NOT_SAVE_CHANGES)
            except Exception:  # noqa: BLE001
                pass
        try:
            app.Quit()
        except Exception:  # noqa: BLE001
            pass


def _count_pages_word(docx_path) -> int:
    """Count pages via Microsoft Word automation, retrying transient COM faults.

    Wraps :func:`_count_pages_word_once`. A :class:`WordUnavailableError`
    (Word cannot start) propagates immediately so the caller falls back to
    LibreOffice without delay. A :class:`WordTransientError` (Word started but a
    call faulted transiently) is retried on a FRESH dispatch up to
    :data:`WORD_TRANSIENT_RETRIES` extra times with a short, increasing backoff,
    because the page count is a hard convergence gate and a busy / tearing-down
    Word instance must not be mistaken for a real failure. If every attempt hits
    a transient fault, the last one is converted to :class:`WordUnavailableError`
    so the LibreOffice fallback still gets a chance before the gate fails fast.
    """
    last_exc: Optional[WordTransientError] = None
    for attempt in range(WORD_TRANSIENT_RETRIES + 1):
        try:
            return _count_pages_word_once(docx_path)
        except WordTransientError as exc:
            last_exc = exc
            if attempt < WORD_TRANSIENT_RETRIES:
                # Let a prior Word instance finish tearing down before retrying.
                time.sleep(WORD_TRANSIENT_BACKOFF_SECONDS * (attempt + 1))
    # Exhausted retries: treat as "Word effectively unavailable" so the caller
    # tries LibreOffice next rather than crashing the gate on a transient fault.
    raise WordUnavailableError(
        "Microsoft Word automation kept faulting after "
        f"{WORD_TRANSIENT_RETRIES + 1} attempts"
    ) from last_exc


def _count_pages_libreoffice(docx_path, soffice: str) -> int:
    """Count pages via headless LibreOffice conversion + pypdf."""
    with tempfile.TemporaryDirectory(prefix="cv-pagecount-") as tmp:
        pdf_path = _run_soffice_convert(soffice, Path(docx_path), Path(tmp))
        if pdf_path is None or not Path(pdf_path).exists():
            raise RenderError(
                f"LibreOffice did not produce a PDF for {docx_path}"
            )
        return _count_pdf_pages(pdf_path)


# --- public API ------------------------------------------------------------


def count_pages(docx_path) -> dict:
    """Measure the rendered page count of ``docx_path``.

    Tries Microsoft Word first, then LibreOffice. Returns a per-document result
    dict ``{"document": <path>, "pages": N, "method": ...}``. Raises
    :class:`NoRendererError` when neither engine is available (the hard gate is
    never guessed), or :class:`RenderError` / :class:`MissingDependencyError`
    when the fallback engine is present but cannot complete.
    """
    document = str(docx_path)

    try:
        pages = _count_pages_word(docx_path)
        return {"document": document, "pages": int(pages), "method": METHOD_WORD}
    except WordUnavailableError:
        pass  # fall through to the LibreOffice fallback

    soffice = _discover_soffice()
    if soffice is None:
        raise NoRendererError(
            "no page renderer available: Microsoft Word automation could not "
            "start and 'soffice' (LibreOffice) was not found on PATH. The page "
            "count is a hard gate and must never be guessed — install Microsoft "
            "Word or LibreOffice in this environment and re-run."
        )

    pages = _count_pages_libreoffice(docx_path, soffice)
    return {"document": document, "pages": int(pages), "method": METHOD_LIBREOFFICE}


# --- CLI -------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="page_count.py",
        description=(
            "Render-based page counting for .docx Working Copies "
            "(Microsoft Word primary, LibreOffice fallback)."
        ),
    )
    parser.add_argument(
        "docx",
        nargs="+",
        help="One or more .docx paths to measure.",
    )
    parser.add_argument(
        "-o",
        "--out",
        required=True,
        help="Path to write the aggregated page_counts.json.",
    )
    args = parser.parse_args(argv)

    missing = [d for d in args.docx if not Path(d).exists()]
    if missing:
        for d in missing:
            sys.stderr.write(f"ERROR: input .docx not found: {d}\n")
        return EXIT_INPUT_NOT_FOUND

    results: list[dict] = []
    try:
        for d in args.docx:
            result = count_pages(d)
            # One JSON line per document on stdout.
            print(json.dumps(result))
            results.append(result)
    except NoRendererError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return EXIT_NO_RENDERER
    except MissingDependencyError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return EXIT_MISSING_DEPENDENCY
    except RenderError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return EXIT_RENDER_FAILED

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
