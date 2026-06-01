"""Shared pytest fixtures for the CV Customizer Agent Suite tests.

Provides path helpers to the versioned fixture documents under
``tests/fixtures/`` and makes the deterministic Python core under
``shared/scripts/`` importable by test modules (e.g. ``import docx_normalize``).
No environment variables are read; all paths are derived from this file's
location so tests work regardless of the invocation cwd.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
SCRIPTS_DIR = TESTS_DIR.parent / "shared" / "scripts"

# Make the shared deterministic scripts importable by their module name without
# environment variables or install steps. Derived purely from this file's
# location so it holds regardless of the pytest invocation cwd.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(scope="session")
def scripts_dir() -> Path:
    """Absolute path to the shared deterministic scripts directory."""
    return SCRIPTS_DIR


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Absolute path to the versioned fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def fixture_path(fixtures_dir: Path):
    """Return a callable that resolves a fixture file name to an absolute path."""

    def _resolve(name: str) -> Path:
        path = fixtures_dir / name
        if not path.exists():
            raise FileNotFoundError(
                f"Fixture '{name}' not found at {path}. "
                "Regenerate .docx fixtures with: "
                "python cli-agents/cv/tests/fixtures/make_fixtures.py"
            )
        return path

    return _resolve
