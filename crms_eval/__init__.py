"""Frozen end-to-end evaluation for CRMS.

The scorecard is the instrument of record for capability claims. It drives the
real chat CLI in a clean process, in an isolated workspace, and checks outcomes
with explicit oracles. Unit diagnostics in ``experiments/`` remain the
regression layer; this package measures complete user tasks.
"""

from .schema import Expectation, Task, load_suite

__all__ = ["Expectation", "Task", "load_suite"]
