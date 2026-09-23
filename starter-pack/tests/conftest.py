"""Test configuration.

Puts the starter-pack root on ``sys.path`` so ``import eval_runner`` works no
matter where pytest is invoked from. Mirrors the path handling already used by
``dataverse/provision_schema.py`` and ``verify_package.py``.
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
