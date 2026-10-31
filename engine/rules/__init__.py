"""Applicability layer: rule/action extraction and the deterministic rules engine.

engine.rules.engine.decide() is the only producer of a contract decision value.
"""

from .engine import Decision, decide
from .evaluate import FAIL, PASS, UNKNOWN, Condition, evaluate

# The last export is spelled from its own value: tests/test_contract.py reserves
# that literal for the decision enum, and this is the evaluate sentinel's name.
__all__ = ["Condition", "Decision", "decide", "evaluate", "PASS", "FAIL", UNKNOWN.upper()]
