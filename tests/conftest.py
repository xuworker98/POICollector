# -*- coding: utf-8 -*-
"""Test bootstrap for the src-layout application."""
import sys
from pathlib import Path

APP_SOURCE = Path(__file__).resolve().parents[1] / "src" / "poi_collector"
if str(APP_SOURCE) not in sys.path:
    sys.path.insert(0, str(APP_SOURCE))
