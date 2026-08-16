#!/usr/bin/env python3
"""Repo-root helper: python3 extras/ga-tokenplan-import/install.py install --copy"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ga_tokenplan_import.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
