"""Shipped enabled: load TokenPlan import from extras/ (portal https://plan.khrey.com/).

Use Path(...).absolute() (not resolve()) so a plugins/ symlink still lands on
this GA root's extras/, not the symlink target's parent tree.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_root = Path(__file__).absolute().parent.parent
if not os.environ.get("GA_ROOT") and (_root / "agentmain.py").is_file():
    os.environ["GA_ROOT"] = str(_root)
_extras = _root / "extras" / "ga-tokenplan-import"
if str(_extras) not in sys.path:
    sys.path.insert(0, str(_extras))
from ga_tokenplan_import.subscription_portal import *  # noqa: E402,F401,F403
