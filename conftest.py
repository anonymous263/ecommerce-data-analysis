"""Pytest bootstrap: put the project root on sys.path.

Lets tests import the first-party ``src`` package (``from src.extract import
woo_api``) regardless of the directory pytest is invoked from. No src-layout /
editable install is used, so this is the single place that wires the path.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
