"""Deterministic, dependency-free source-to-source transpiler framework."""

from .core import TranspileError
from .engine import PAIRS, transpile

__all__ = ["PAIRS", "TranspileError", "transpile"]
