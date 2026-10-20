"""Offline evaluation of scope extraction, session history, custom SCP isolation, and scan packaging.

Scores saved artifacts. It does not call a model. A live run is scored the same way once scope.json,
session.json, and the scan reports exist.
"""

from .score import run_suite, score_run

__all__ = ["run_suite", "score_run"]
