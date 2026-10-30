"""Errors reported to the user without a traceback."""

from __future__ import annotations


class BenchForgeError(Exception):
    """A problem with the suite file, a result file, a path or the command line."""
