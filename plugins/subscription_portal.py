"""Shipped enabled: load TokenPlan import from extras/ (portal https://plan.khrey.com/)."""
from __future__ import annotations

import sys
from pathlib import Path

_extras = Path(__file__).resolve().parent.parent / "extras" / "ga-tokenplan-import"
if str(_extras) not in sys.path:
    sys.path.insert(0, str(_extras))
from ga_tokenplan_import.subscription_portal import *  # noqa: E402,F401,F403
