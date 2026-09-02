# -*- coding: utf-8 -*-
"""Location: ./tests/unit/loadtest/conftest.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Importing locust runs gevent.monkey.patch_all() at module import time, which
deadlocks a pytest process that has already imported the standard library and
the gateway's own modules. The tests in this package only exercise pure helper
functions, so the patch is neither needed nor safe here.

pytest imports this conftest before any test module in this directory, so the
variable is set before locust is first imported.
"""

# Standard
import os

os.environ.setdefault("LOCUST_SKIP_MONKEY_PATCH", "1")
