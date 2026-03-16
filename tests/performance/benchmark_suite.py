"""Compatibility shim for the self-contained benchmark runner."""

from __future__ import annotations

import sys

from benchmarks.contextforge import runner as _runner

sys.modules[__name__] = _runner
