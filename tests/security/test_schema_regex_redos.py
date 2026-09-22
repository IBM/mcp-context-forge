# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_schema_regex_redos.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

ReDoS regression coverage for JSON Schema validation.

The event-loop measurement below is the load-bearing assertion. A fix that only moves the
match to a thread produces the same stall as no fix at all, because CPython holds the GIL
through a regex match. Only this test tells them apart.

Every assertion here checks content, not presence. An elapsed-time bound plus "some error
happened" cannot tell "the sandbox stopped a runaway" apart from "the pool was broken and
every schema is refused", and the second state is a disabled control that looks like a
working one.
"""

# Standard
import asyncio
import time

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.tool_service import _validate_tool_input_arguments
from mcpgateway.utils.safe_jsonschema import shutdown_validation_pool, start_validation_pool

CATASTROPHIC_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"q": {"type": "string", "pattern": "^(a+)+$"}},
}

# Backtracking doubles per added character, so this length decides how fast a regression
# reports. 28 characters run the match for about 8 seconds, which overruns the 1 second
# sandbox budget by roughly 8x and reports inside the 30 second test timeout.
#
# A longer subject looks stronger and is worse here, because this test runs the validation
# in a worker thread. ``pytest.mark.timeout`` fires on schedule either way, but a Python
# thread cannot be killed, and closing the loop joins its executor. The call therefore does
# not return until the match finishes. Measured: a 3 second timeout on a 30 character match
# reports at 3 seconds and returns after 42. At 40 characters the match runs for hours, so a
# regression would report and then block the run behind that join.
HOSTILE = {"q": "a" * 28 + "b"}

# The phrase the timeout path alone contributes. ``validate_safely`` wraps every sandbox
# fault, this one included, in "schema validation could not be completed safely", so that
# outer text does not discriminate. This inner phrase comes from ``SandboxTimeout`` only, so
# it separates "the budget stopped the match" from a mismatch and from a broken pool.
BOUNDED = "exceeded the execution time limit"

# The heartbeat wakes every 10 ms, and the test lets it run for 200 ms before validating.
# Requiring this many samples stops the loop assertion passing vacuously on an empty list.
MIN_HEARTBEATS = 15

# The loop budget must never be derived solely from the control it measures.
# ``regex_timeout_seconds`` is the sandbox's own budget: an unpinned environment value that
# config.py allows up to 60, and nothing else in the test suite pins it. Deriving the budget
# from it alone lets a deployment raise it and silently disarm this assertion, which is the
# one check that separates a real fix from a thread-only one. Proven: with a thread-only
# sandbox, the default setting fails at "stalled 7.86s; budget is 2.00s" while a setting of
# 5 passes. An inline or thread-only regression stalls the loop for about 8 seconds, so the
# budget is capped here as well and a setting that moves makes the test red, never blind.
MAX_LOOP_STALL_SECONDS = 2.0
MAX_SUPPORTED_REGEX_TIMEOUT_SECONDS = 1.0

# A legitimate subject measured 0.8 ms mean and 3.4 ms worst over ten runs, so this bound
# still leaves about 150x of headroom for a loaded machine. It is half the sandbox budget,
# which is the property worth asserting: valid traffic must not approach the kill budget.
MAX_VALID_SUBJECT_SECONDS = 0.5

_HEARTBEAT_INTERVAL = 0.01


@pytest.fixture(autouse=True)
def _pool():
    """Start and stop the validation pool around each test.

    Yields:
        None.
    """
    start_validation_pool()
    yield
    shutdown_validation_pool()


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_event_loop_stays_responsive_during_hostile_validation():
    """One hostile request must not stall every other request on this worker.

    The validation runs through ``asyncio.to_thread`` on purpose. That is the shape of the
    non-fix this test exists to reject: a thread keeps the GIL through the match, so a
    thread-only fix stalls the loop exactly as much as no fix at all.
    """
    lateness: list[float] = []
    stop = asyncio.Event()

    async def heartbeat() -> None:
        """Wake every 10 ms and record how late each wake-up was."""
        while not stop.is_set():
            start = time.perf_counter()
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            lateness.append(time.perf_counter() - start - _HEARTBEAT_INTERVAL)

    beat = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.2)
    error = await asyncio.to_thread(_validate_tool_input_arguments, HOSTILE, CATASTROPHIC_SCHEMA)
    stop.set()
    await beat

    assert len(lateness) >= MIN_HEARTBEATS, f"heartbeat produced {len(lateness)} samples; the loop assertion would be vacuous"

    assert settings.regex_timeout_seconds <= MAX_SUPPORTED_REGEX_TIMEOUT_SECONDS, (
        f"regex_timeout_seconds is {settings.regex_timeout_seconds}s, above {MAX_SUPPORTED_REGEX_TIMEOUT_SECONDS}s; the loop budget below is derived from this setting and must not silently widen with it"
    )
    budget = min(2 * settings.regex_timeout_seconds, MAX_LOOP_STALL_SECONDS)
    assert max(lateness) < budget, f"event loop stalled {max(lateness):.2f}s; budget is {budget:.2f}s"

    # Without this the loop assertion passes for the wrong reason: a pool that refuses every
    # regex-bearing schema also keeps the loop free, and that state is a disabled control.
    assert error is not None and BOUNDED in error, f"validation must be stopped by the budget, not by an unrelated refusal; got {error!r}"


@pytest.mark.timeout(30)
def test_hostile_validation_fails_closed():
    """A truncated validation must be reported as a failure, never a pass."""
    error = _validate_tool_input_arguments(HOSTILE, CATASTROPHIC_SCHEMA)
    assert error is not None, "a truncated validation must fail closed"
    assert BOUNDED in error, f"the budget must be what stopped it; got {error!r}"


@pytest.mark.timeout(30)
def test_valid_subject_is_unaffected():
    """Backtracking only explodes on a non-matching subject.

    A caller sending valid arguments must see no change, so this asserts the fix costs
    legitimate traffic nothing.
    """
    start = time.perf_counter()
    assert _validate_tool_input_arguments({"q": "a" * 5000}, CATASTROPHIC_SCHEMA) is None
    elapsed = time.perf_counter() - start
    assert elapsed < MAX_VALID_SUBJECT_SECONDS, f"valid subject took {elapsed:.3f}s; budget is {MAX_VALID_SUBJECT_SECONDS}s"
