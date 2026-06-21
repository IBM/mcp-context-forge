# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/test_pii_filter_e2e.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end gateway test for the cpex-pii-filter plugin.

Unlike the blocking plugins, the PII filter does not reject a call: with the
committed config (``block_on_detection: false``, ``default_mask_strategy:
partial``) it *masks* detected PII in place and lets the request through. This
suite drives that behaviour over a live gateway across the plugin's hooks:

* the tool hooks (``tool_pre_invoke`` / ``tool_post_invoke``) via the
  fast-time-server ``echo`` tool - a payload carrying PII is echoed back masked,
  and a clean / whitelisted payload round-trips unchanged, and
* the prompt hooks (``prompt_pre_fetch`` / ``prompt_post_fetch``) via a
  registered prompt rendered over ``prompts/get`` - PII in the prompt arguments
  surfaces masked in the rendered message.

The tool assertions run against **both** enforcement paths, selected by the
``PLUGIN_ENFORCEMENT`` env var (set by the workflow matrix):

* ``static`` - the gateway boots with PIIFilterPlugin in ``enforce`` mode
  (config derived from ``plugins/config.yaml``), and
* ``binding`` - the gateway boots with PIIFilterPlugin ``disabled`` and a
  runtime tool-plugin-binding flips it to ``enforce`` for the test's team+tool.

The prompt assertions run on the **static** path only: tool-plugin-bindings are
tool-scoped, so they cannot reach the prompt hooks - the static path is where
the prompt hooks are enforced.

Both paths bind the identical production config block, so one test body covers
both. The cpex plugin is never imported here - the gateway loads it from
``PLUGINS_CONFIG_FILE``; ``plugin_enforcement`` asserts it actually loaded so a
broken build fails loudly instead of skipping.

The committed config detects email, SSN and credit-card (phone and IP are off)
and whitelists ``test@example.com`` and ``555-555-5555``; the fixtures and cases
below use non-whitelisted values so detection actually fires, and include
whitelisted / detector-off controls that must pass through untouched.
"""

from __future__ import annotations

# Standard
from contextlib import suppress
from typing import Generator

# Third-Party
import httpx
import pytest

# First-Party
from tests.live_gateway.helpers.mcp_test_helpers import skip_no_gateway
from tests.live_gateway.plugins import _helpers

pytestmark = [pytest.mark.e2e, skip_no_gateway]

PLUGIN_NAME = "PIIFilterPlugin"

# Prompt hooks are unreachable on the bindings path (bindings are tool-scoped),
# so the prompt cases are exercised on the static path only.
_static_only = pytest.mark.skipif(
    _helpers.PLUGIN_ENFORCEMENT == "binding",
    reason="prompt hooks are not reachable via tool-plugin-bindings (tool-scoped); enforced on the static path",
)

# (label, raw input, expected masked output) for the enabled detectors under the
# committed ``partial`` masking strategy. Masked forms are exact:
#   email john@example.com -> j******@example.com (first char of local + mask)
#   ssn   123-45-6789      -> ***-**-6789       (last 4)
#   cc    4111111111111111 -> ****-****-****-1111 (last 4 digits; Luhn-valid)
PII_CASES = [
    ("email", "Reach me at john@example.com please", "Reach me at j******@example.com please"),
    ("ssn", "My number is 123-45-6789 thanks", "My number is ***-**-6789 thanks"),
    ("credit_card", "Card 4111111111111111 charged", "Card ****-****-****-1111 charged"),
    (
        "combined",
        "Email john@example.com num 123-45-6789 cc 4111111111111111",
        "Email j******@example.com num ***-**-6789 cc ****-****-****-1111",
    ),
]

# Inputs the filter must leave byte-for-byte unchanged: no PII, a whitelisted
# value, and a phone number (``detect_phone`` is off in the committed config).
PASSTHROUGH_CASES = [
    ("clean", "Hello world, nothing private here"),
    ("whitelisted_email", "Contact test@example.com for details"),
    ("phone_detection_off", "Call me at 212-555-0143 tomorrow"),
]


@pytest.fixture(scope="module", autouse=True)
def _enforcement(admin_client: httpx.Client, fast_time_server: dict[str, str]):
    """Activate the enforcement path under test (static config or DB binding).

    Fails fast unless PIIFilterPlugin loaded on the gateway, and - on the
    bindings path - creates the runtime binding (scoped to the suite's
    team+echo-tool) that makes the tool hooks enforce, removing it on teardown.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.

    Yields:
        ``None`` once the enforcement path is active.
    """
    with _helpers.plugin_enforcement(
        admin_client,
        fast_time_server=fast_time_server,
        plugin_name=PLUGIN_NAME,
    ):
        yield


@pytest.fixture(scope="module")
def pii_prompt(admin_client: httpx.Client, fast_time_server: dict[str, str]) -> Generator[dict[str, str], None, None]:
    """Register a prompt and expose it on its own virtual server.

    The gateway scopes prompt rendering to a virtual server, so the prompt is
    associated with a dedicated server the suite can address over ``prompts/get``
    to drive the prompt hooks. Torn down on exit.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value (for its team).

    Yields:
        Mapping with ``server_id`` and the slugified ``prompt_name``.
    """
    suffix = _helpers.unique_suffix()
    prompt = _helpers.register_prompt(
        admin_client,
        name=f"pii_e2e_{suffix}",
        template="User said: {{ text }}",
        arguments=[{"name": "text", "description": "user-supplied text", "required": True}],
        team_id=fast_time_server["team_id"],
        visibility="public",
    )
    server_id = _helpers.create_virtual_server(
        admin_client,
        name=f"pii_e2e_prompt_server_{suffix}",
        tool_ids=[],
        prompt_ids=[prompt["id"]],
    )
    try:
        yield {"server_id": server_id, "prompt_name": prompt["name"]}
    finally:
        with suppress(Exception):
            admin_client.delete(f"/servers/{server_id}")
        with suppress(Exception):
            _helpers.delete_prompt(admin_client, prompt_id=prompt["id"])


def _echo(admin_client: httpx.Client, fast_time_server: dict[str, str], message: str) -> dict:
    """Echo ``message`` through the gateway, driving the tool PII hooks.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
        message: Text to echo through the gateway (and its plugin hooks).

    Returns:
        The JSON-RPC ``result`` payload from ``tools/call``.
    """
    server_id = fast_time_server["server_id"]
    token = fast_time_server["token"]
    session_id = _helpers.initialize_session(admin_client, server_id=server_id, token=token)
    return _helpers.call_tool(
        admin_client,
        server_id=server_id,
        token=token,
        tool_name=fast_time_server["echo_tool"],
        arguments={"message": message},
        session_id=session_id,
        request_id=1,
    )


@pytest.mark.parametrize("label, raw, masked", PII_CASES, ids=[c[0] for c in PII_CASES])
def test_tool_pii_is_masked(admin_client: httpx.Client, fast_time_server: dict[str, str], label: str, raw: str, masked: str) -> None:
    """PII echoed through a tool surfaces masked, not blocked.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
        label: Case label (for test ids).
        raw: Input text containing PII.
        masked: Expected echoed text with PII partially masked.
    """
    result = _echo(admin_client, fast_time_server, raw)

    assert result == {"content": [{"type": "text", "text": masked}], "isError": False}


@pytest.mark.parametrize("label, payload", PASSTHROUGH_CASES, ids=[c[0] for c in PASSTHROUGH_CASES])
def test_tool_passthrough_is_unchanged(admin_client: httpx.Client, fast_time_server: dict[str, str], label: str, payload: str) -> None:
    """Clean, whitelisted and detector-off inputs round-trip unchanged.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
        label: Case label (for test ids).
        payload: Input text the filter must leave untouched.
    """
    result = _echo(admin_client, fast_time_server, payload)

    assert result == {"content": [{"type": "text", "text": payload}], "isError": False}


@_static_only
@pytest.mark.parametrize("label, raw, masked", PII_CASES, ids=[c[0] for c in PII_CASES])
def test_prompt_pii_is_masked(admin_client: httpx.Client, fast_time_server: dict[str, str], pii_prompt: dict[str, str], label: str, raw: str, masked: str) -> None:
    """PII in prompt arguments surfaces masked in the rendered prompt.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value (for its token).
        pii_prompt: Registered-prompt fixture value.
        label: Case label (for test ids).
        raw: Prompt argument text containing PII.
        masked: Expected rendered text with PII partially masked.
    """
    server_id = pii_prompt["server_id"]
    token = fast_time_server["token"]
    session_id = _helpers.initialize_session(admin_client, server_id=server_id, token=token)
    result = _helpers.get_prompt(
        admin_client,
        server_id=server_id,
        token=token,
        prompt_name=pii_prompt["prompt_name"],
        arguments={"text": raw},
        session_id=session_id,
        request_id=1,
    )

    assert _helpers.prompt_text(result) == f"User said: {masked}"


@_static_only
@pytest.mark.parametrize("label, payload", PASSTHROUGH_CASES, ids=[c[0] for c in PASSTHROUGH_CASES])
def test_prompt_passthrough_is_unchanged(admin_client: httpx.Client, fast_time_server: dict[str, str], pii_prompt: dict[str, str], label: str, payload: str) -> None:
    """Clean, whitelisted and detector-off prompt arguments render unchanged.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value (for its token).
        pii_prompt: Registered-prompt fixture value.
        label: Case label (for test ids).
        payload: Prompt argument text the filter must leave untouched.
    """
    server_id = pii_prompt["server_id"]
    token = fast_time_server["token"]
    session_id = _helpers.initialize_session(admin_client, server_id=server_id, token=token)
    result = _helpers.get_prompt(
        admin_client,
        server_id=server_id,
        token=token,
        prompt_name=pii_prompt["prompt_name"],
        arguments={"text": payload},
        session_id=session_id,
        request_id=1,
    )

    assert _helpers.prompt_text(result) == f"User said: {payload}"
