"""pytest configuration for the hook suites: make `import hooklib` / `import hooks` work from any cwd.

The hooks live one directory up (`tests/..`); they are installed flat into `.claude/hooks/`, so they import
each other by bare name and the test process must see that directory first on sys.path.
"""

from __future__ import annotations

import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
if str(HOOKS_DIR) in sys.path:
    sys.path.remove(str(HOOKS_DIR))
sys.path.insert(0, str(HOOKS_DIR))
