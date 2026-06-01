"""input_normalize.py — multi-format -> Normalized_Text (task 3).

Part of the deterministic Python core of the CV Customizer Agent Suite. The
orchestrator runs this during the NORMALIZE phase to turn the Job_Description
and Bullet_Point_Database (which arrive in assorted formats) into a uniform
plain-text / Markdown surface that the reviewer agents read:

    Job description -> jd.normalized.md
    Database        -> database.normalized.md

Unlike ``docx_normalize.py`` (which also emits stable anchors for the CV and
letter), JD/DB normalization needs only a readable text surface — no anchors —
so the output is a single Markdown/plain-text string.

Dispatch by file extension (design "Input Normalization Layer")
---------------------------------------------------------------
    .docx          -> python-docx text extraction (reuses docx_normalize)
    .pdf           -> pdfminer.six text extraction
    .html / .htm   -> BeautifulSoup (bs4): strip tags, collapse whitespace
    .md / .txt     -> passthrough with light whitespace normalization

Dependency policy (design "Dependency policy")
----------------------------------------------
The heavy optional libraries (``pdfminer.six`` and ``beautifulsoup4``) and
``python-docx`` are imported **lazily inside the branch that needs them**, so:

* normalizing a ``.txt`` / ``.md`` requires none of them;
* normalizing a ``.docx`` does not require pdfminer or bs4;
* a missing library surfaces as a clear, non-zero exit naming the *pip package*
  (``pdfminer.six`` / ``beautifulsoup4`` / ``python-docx``), never an install
  attempt. The orchestrator relays that as a FATAL setup error [R15.5].

CLI
---
    python input_normalize.py <input> <output.md>

Importable API (so tests and the editor can call directly)
----------------------------------------------------------
    normalize(input_path) -> str        # dispatch by extension
    normalize_docx(path)  -> str
    normalize_pdf(path)   -> str
    normalize_html(path)  -> str
    normalize_text_file(path) -> str
    html_to_text(html_str) -> str       # the bs4 strip+collapse, on a string
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

# Exit codes (distinct so callers/tests can tell failure modes apart).
EXIT_OK = 0
EXIT_INPUT_NOT_FOUND = 2
EXIT_MISSING_DEPENDENCY = 3
EXIT_UNSUPPORTED_FORMAT = 4

SUPPORTED_EXTENSIONS = (".docx", ".pdf", ".html", ".htm", ".md", ".txt")


# --- errors ----------------------------------------------------------------


class MissingDependencyError(RuntimeError):
    """A required third-party library is not installed.

    Carries the *pip package* name (e.g. ``pdfminer.six``), which differs from
    the import name (``pdfminer``), so the user is told exactly what to install.
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


class UnsupportedFormatError(ValueError):
    """The input file extension is not one this normalizer handles."""

    def __init__(self, ext: str, path) -> None:
        self.ext = ext
        super().__init__(
            f"unsupported input format {ext!r} for {path}. "
            f"Supported extensions: {', '.join(SUPPORTED_EXTENSIONS)}."
        )


# --- whitespace helpers ----------------------------------------------------

_BLANK_RUN = re.compile(r"\n{3,}")
_ANY_WS_RUN = re.compile(r"\s+")


def _light_normalize(text: str) -> str:
    """Light, structure-preserving normalization for ``.txt`` / ``.md`` / PDF.

    Normalizes line endings and form feeds to ``\\n``, strips trailing
    whitespace from each line (preserving leading indentation so Markdown
    structure survives), collapses 3+ consecutive newlines to a single blank
    line, and guarantees exactly one trailing newline. Empty/whitespace-only
    input yields an empty string.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _BLANK_RUN.sub("\n\n", text)
    text = text.strip("\n")
    return f"{text}\n" if text else ""


# --- lazy dependency import points (monkeypatchable in tests) --------------


def _import_docx_document():
    """Import indirection for python-docx (lazy; per-branch)."""
    from docx import Document

    return Document


def _import_pdfminer_extract_text():
    """Import indirection for pdfminer.six (lazy; per-branch)."""
    from pdfminer.high_level import extract_text

    return extract_text


def _import_beautifulsoup():
    """Import indirection for beautifulsoup4 / bs4 (lazy; per-branch)."""
    from bs4 import BeautifulSoup

    return BeautifulSoup


# --- per-format normalizers ------------------------------------------------


def normalize_docx(path) -> str:
    """Extract a ``.docx`` to the normalized Markdown surface.

    Reuses ``docx_normalize.to_markdown`` so the JD/DB docx surface matches the
    CV/letter surface; anchors are intentionally not produced here.
    """
    try:
        Document = _import_docx_document()
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("python-docx", exc) from exc
    # docx import is verified above, so importing docx_normalize (which imports
    # python-docx at module load) is safe and will not trigger its SystemExit.
    import docx_normalize

    return docx_normalize.to_markdown(Document(str(path)))


def normalize_pdf(path) -> str:
    """Extract a ``.pdf`` to normalized text via pdfminer.six."""
    try:
        extract_text = _import_pdfminer_extract_text()
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("pdfminer.six", exc) from exc
    raw = extract_text(str(path))
    return _light_normalize(raw)


def html_to_text(html: str) -> str:
    """Strip tags and collapse whitespace from an HTML *string* via bs4.

    Removes ``script``/``style``/``head`` content, collapses each text node's
    internal whitespace to single spaces (so source line-wrapping inside a
    block does not fragment a sentence), then emits one cleaned line per block,
    dropping blank lines. Tolerant of messy whitespace and newlines.
    """
    try:
        BeautifulSoup = _import_beautifulsoup()
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("beautifulsoup4", exc) from exc

    from bs4 import Comment, Doctype

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    # Drop non-content string nodes (e.g. ``<!DOCTYPE html>`` and HTML comments)
    # which html.parser otherwise surfaces as text.
    for special in soup.find_all(string=lambda s: isinstance(s, (Comment, Doctype))):
        special.extract()
    # Collapse whitespace within each text node first; this joins sentences that
    # were merely line-wrapped in the source HTML.
    for node in list(soup.find_all(string=True)):
        node.replace_with(_ANY_WS_RUN.sub(" ", str(node)))
    raw = soup.get_text(separator="\n")
    lines = [line.strip() for line in raw.split("\n") if line.strip()]
    return ("\n".join(lines) + "\n") if lines else ""


def normalize_html(path) -> str:
    """Extract an ``.html`` / ``.htm`` file to normalized text."""
    return html_to_text(Path(path).read_text(encoding="utf-8"))


def normalize_text_file(path) -> str:
    """Passthrough ``.md`` / ``.txt`` with light whitespace normalization."""
    return _light_normalize(Path(path).read_text(encoding="utf-8"))


# --- dispatch --------------------------------------------------------------

_DISPATCH = {
    ".docx": normalize_docx,
    ".pdf": normalize_pdf,
    ".html": normalize_html,
    ".htm": normalize_html,
    ".md": normalize_text_file,
    ".txt": normalize_text_file,
}


def normalize(input_path) -> str:
    """Normalize ``input_path`` to a text surface, dispatching by extension.

    Raises :class:`UnsupportedFormatError` for unknown extensions and
    :class:`MissingDependencyError` when the format's library is unavailable.
    """
    path = Path(input_path)
    ext = path.suffix.lower()
    handler = _DISPATCH.get(ext)
    if handler is None:
        raise UnsupportedFormatError(ext, path)
    return handler(path)


# --- CLI -------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="input_normalize.py",
        description="Normalize a multi-format input (docx/pdf/html/md/txt) to text.",
    )
    parser.add_argument("input", help="Path to the input file.")
    parser.add_argument("output_md", help="Path to write the normalized text.")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        sys.stderr.write(f"ERROR: input not found: {input_path}\n")
        return EXIT_INPUT_NOT_FOUND

    try:
        text = normalize(input_path)
    except MissingDependencyError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return EXIT_MISSING_DEPENDENCY
    except UnsupportedFormatError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return EXIT_UNSUPPORTED_FORMAT

    out_md = Path(args.output_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(text, encoding="utf-8")
    print(
        json.dumps(
            {
                "input": str(input_path),
                "normalized_md": str(out_md),
                "format": input_path.suffix.lower(),
            }
        )
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
