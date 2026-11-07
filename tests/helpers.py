"""Shared test setup."""

import os
import sys
from datetime import date

# Let the tests import the project modules no matter where they are run from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def d(day: int) -> date:
    """Shorthand for a November 2026 date."""
    return date(2026, 11, day)
