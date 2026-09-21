# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_regex_reachability.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Prove no validation path reaches an unbounded regex engine in this process.

A grep over first-party code cannot establish this: the escape found in review lived in
site-packages. This module verifies by execution instead, in four layers.

1. A positive routing assertion. It spies on the sandbox pool and asserts each call site
   submits a regex-bearing schema to the sandbox, and submits nothing for a schema without
   one. Only this layer can prove routing happened.
2. An in-process pattern tripwire. It replaces the ``pattern`` and ``patternProperties``
   keyword implementations in every stock draft with a function that raises. Any pattern
   evaluated in this process fails the test by name.
3. A direct-call tripwire. It makes ``jsonschema.validate`` raise. No first-party code
   calls that function, but the vendored SDK does, so this layer is live.
4. A data-guard assertion for the SDK site. The SDK validates ``outputSchema`` in-process
   and cannot be routed, so the gateway withholds a regex-bearing ``outputSchema`` instead.
   Layers 1 to 3 cannot see that guard, because it lives in a different module and submits
   nothing. This layer drives the real SDK handler and asserts the guard held.

The sandbox worker is a separate process, so none of these in-process patches reach it. A
correctly routed validation therefore still succeeds while the tripwires are armed. That
asymmetry is the whole design: a path that validates in-process fails, a path that routes
to the sandbox passes.

Two habits keep this module from proving nothing:

* Every layer has a self-test that proves the layer can fail.
* Every outcome assertion names the content it expects. Asserting only that an error
  occurred passes on every fail-closed branch of ``validate_safely``, which produces the
  same observable outcome entirely in-process and with no worker running at all.
"""

# Standard
from contextlib import ExitStack
from inspect import getclosurevars
from types import SimpleNamespace
from unittest.mock import patch

# Third-Party
import jsonschema
import mcp.types as types
from mcp.server.lowlevel import Server
import pytest

# First-Party
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.services.tool_service import _validate_tool_input_arguments, _validate_with_cached_schema
from mcpgateway.transports.streamablehttp_transport import _guard_proxied_tools, _to_mcp_tool, mcp_app
from mcpgateway.utils import safe_jsonschema
from mcpgateway.utils.safe_jsonschema import schema_uses_regex, shutdown_validation_pool, start_validation_pool

# No schema here may carry ``$anchor`` or ``$dynamicAnchor``. The 2020-12 metaschema checks
# both with its own ``pattern`` keyword, so adding one makes ``check_schema`` evaluate a
# pattern in-process. That evaluation is correct by design, but the tripwire cannot tell it
# apart from a routing failure, and the test would fail for the wrong reason.
PLAIN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"q": {"type": "string"}},
}

# ``pattern`` reached through a plain object chain.
REGEX_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"q": {"type": "string", "pattern": "^[a-z]+$"}},
}

# ``pattern`` reached only by recursing through a JSON array node. A router that walks
# mappings but not lists reports this schema as regex-free and validates it inline.
ANYOF_REGEX_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"q": {"anyOf": [{"type": "string", "pattern": "^[a-z]+$"}]}},
}

# The other regex keyword. Each key of ``patternProperties`` is a regex, and the keyword has
# its own implementation, so ``pattern`` coverage alone never exercises it.
PATTERN_PROPERTIES_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "patternProperties": {"^q$": {"type": "integer"}},
}

# Each shape carries the exact message fragment its own rejection produces. No fail-closed
# branch of ``validate_safely`` can produce any of these strings, so a test that asserts one
# cannot pass on a sandbox that never ran.
SHAPES = [
    pytest.param(REGEX_SCHEMA, {"q": "abc"}, {"q": "ABC"}, "does not match '^[a-z]+$'", id="pattern-under-properties"),
    pytest.param(ANYOF_REGEX_SCHEMA, {"q": "abc"}, {"q": "ABC"}, "does not match '^[a-z]+$'", id="pattern-under-anyOf"),
    pytest.param(PATTERN_PROPERTIES_SCHEMA, {"q": 1}, {"q": "ABC"}, "is not of type 'integer'", id="patternProperties"),
]

# Every stock draft the sandbox can reproduce. Each one holds its own keyword table.
_DRAFTS = (
    jsonschema.Draft4Validator,
    jsonschema.Draft6Validator,
    jsonschema.Draft7Validator,
    jsonschema.Draft201909Validator,
    jsonschema.Draft202012Validator,
)

# Both keywords whose values are regular expressions, matching the router in
# ``safe_jsonschema._REGEX_KEYWORDS``.
_REGEX_KEYWORDS = ("pattern", "patternProperties")


class _Tripwire(Exception):
    """Raised when a guarded entry point is reached in-process."""


def _boom(*args, **kwargs):
    """Raise when called.

    Args:
        *args: Ignored.
        **kwargs: Ignored.

    Raises:
        _Tripwire: Always.
    """
    raise _Tripwire("unbounded validation reached in-process")


def _tool_record(output_schema):
    """Build the internal tool record shape that ``_to_mcp_tool`` reads.

    Args:
        output_schema: The schema the tool advertises as its output contract.

    Returns:
        SimpleNamespace: A stand-in for the ORM tool row.
    """
    return SimpleNamespace(
        name="probe_tool",
        title=None,
        description="probe",
        input_schema={"type": "object"},
        output_schema=output_schema,
        annotations=None,
        extension_metadata=None,
    )


async def _drive_sdk_call_tool(advertised):
    """Run the vendored SDK ``CallToolRequest`` handler against an advertised tool.

    The SDK validates ``outputSchema`` at ``mcp/server/lowlevel/server.py:573`` with stock
    ``jsonschema``, in-process and unbounded. ``validate_input=False`` does not gate that
    branch, so the only defense is withholding a regex-bearing schema before the SDK sees it.

    The registration mirrors production, which uses ``validate_input=False`` at
    ``streamablehttp_transport.py:1775``. That flag is load-bearing here: the SDK's input
    branch calls ``jsonschema.validate`` for every call, and ``inputSchema`` carries no
    guard, so ``validate_input=True`` would open a second unbounded site.
    :func:`test_production_call_tool_handler_does_not_validate_input` holds that flag in place.

    Args:
        advertised: The SDK tool model the gateway advertises, after its guards ran.

    Returns:
        mcp.types.ServerResult: The handler result, carrying ``isError`` and the message.
    """
    server = Server("regex-reachability-probe")

    @server.call_tool(validate_input=False)
    async def _call(name, arguments):  # pylint: disable=unused-argument
        """Return structured content so the SDK reaches its output-validation branch.

        Args:
            name: Ignored.
            arguments: Ignored.

        Returns:
            tuple: Unstructured content and the structured payload.
        """
        return ([types.TextContent(type="text", text="{}")], {"q": "abc"})

    server._tool_cache[advertised.name] = advertised  # pylint: disable=protected-access
    request = types.CallToolRequest(method="tools/call", params=types.CallToolRequestParams(name=advertised.name, arguments={}))
    return await server.request_handlers[types.CallToolRequest](request)


@pytest.fixture(autouse=True)
def _pool():
    """Start and stop the validation pool around each test.

    Yields:
        None.
    """
    start_validation_pool()
    yield
    shutdown_validation_pool()


@pytest.fixture(name="tripwire")
def _tripwire():
    """Make every in-process unbounded validation entry point raise.

    Patching ``jsonschema._keywords.pattern`` does not work: each draft's ``VALIDATORS``
    table captured the function object at import time, so the module attribute is never
    read again. The keyword tables are patched instead, which was verified to fire.

    The ``jsonschema.validate`` patch has the same structural limit in a milder form. It
    rebinds the module attribute, so it reaches every caller that writes
    ``jsonschema.validate(...)``, including the vendored SDK. A caller that instead writes
    ``from jsonschema import validate`` at import time holds the original function and slips
    past. ``jsonschema.validators.validate`` is patched as well, which closes the
    ``from jsonschema.validators import validate`` form, but the plain
    ``from jsonschema import validate`` form remains uncovered by construction.

    The sandbox worker is a separate process and is unaffected by these patches, so a
    correctly routed validation still succeeds.

    Yields:
        None.
    """
    with ExitStack() as stack:
        for draft in _DRAFTS:
            stack.enter_context(patch.dict(draft.VALIDATORS, {keyword: _boom for keyword in _REGEX_KEYWORDS}))
        stack.enter_context(patch("jsonschema.validate", side_effect=_boom))
        stack.enter_context(patch("jsonschema.validators.validate", side_effect=_boom))
        yield


@pytest.fixture(name="submit")
def _submit():
    """Spy on the validation sandbox without changing what it does.

    Yields:
        unittest.mock.MagicMock: The wrapped ``SandboxPool.submit``, carrying the call count.
    """
    original = safe_jsonschema._SANDBOX.submit  # pylint: disable=protected-access
    with patch.object(safe_jsonschema._SANDBOX, "submit", wraps=original) as spy:  # pylint: disable=protected-access
        yield spy


# --------------------------------------------------------------------------------------
# Layer self-tests. A tripwire that cannot fire is indistinguishable from one that proves
# everything, so each layer proves it can fail before it is trusted below.
# --------------------------------------------------------------------------------------


@pytest.mark.timeout(30)
@pytest.mark.parametrize("draft", _DRAFTS, ids=[draft.__name__ for draft in _DRAFTS])
def test_pattern_tripwire_fires_for_every_draft(draft):
    """Layer 2 self-test: the patched keyword table must actually be consulted.

    Args:
        draft: A stock jsonschema draft validator class.
    """
    with patch.dict(draft.VALIDATORS, {"pattern": _boom}):
        with pytest.raises(_Tripwire):
            draft({"type": "object", "properties": {"q": {"type": "string", "pattern": "^[a-z]+$"}}}).validate({"q": "abc"})


@pytest.mark.timeout(30)
@pytest.mark.parametrize("draft", _DRAFTS, ids=[draft.__name__ for draft in _DRAFTS])
def test_pattern_properties_tripwire_fires_for_every_draft(draft):
    """Layer 2 self-test: the other regex keyword must be armed too.

    Args:
        draft: A stock jsonschema draft validator class.
    """
    with patch.dict(draft.VALIDATORS, {"patternProperties": _boom}):
        with pytest.raises(_Tripwire):
            draft({"type": "object", "patternProperties": {"^q$": {"type": "integer"}}}).validate({"q": 1})


@pytest.mark.timeout(30)
def test_direct_call_tripwire_fires():
    """Layer 3 self-test: the ``jsonschema.validate`` patch must be capable of failing."""
    with patch("jsonschema.validate", side_effect=_boom):
        with pytest.raises(_Tripwire):
            jsonschema.validate(instance={}, schema={})


@pytest.mark.timeout(30)
def test_routing_spy_fires(submit):
    """Layer 1 self-test: the spy must count a real submission.

    A spy that never records would make every routing assertion below vacuous.

    Args:
        submit: The sandbox submission spy.
    """
    safe_jsonschema.validate_safely({"q": "abc"}, REGEX_SCHEMA, jsonschema.Draft202012Validator)
    assert submit.call_count == 1


@pytest.mark.timeout(30)
async def test_sdk_output_validation_tripwire_fires():
    """Layer 4 self-test: an unguarded ``outputSchema`` must reach the SDK's validator.

    This proves the SDK site is live. If it were not, the guard assertions below would
    prove nothing, because a withheld schema and an unreachable validator look the same.
    """
    unguarded = types.Tool(name="probe_tool", inputSchema={"type": "object"}, outputSchema=REGEX_SCHEMA)
    with patch("jsonschema.validate", side_effect=_boom):
        result = await _drive_sdk_call_tool(unguarded)
    assert result.root.isError is True
    assert "unbounded validation reached in-process" in result.root.content[0].text


@pytest.mark.timeout(30)
def test_production_call_tool_handler_does_not_validate_input():
    """Layer 4 premise: the gateway must keep the SDK's input validator switched off.

    ``inputSchema`` reaches the SDK unguarded, so ``validate_input=True`` would send every
    advertised input schema through stock ``jsonschema`` in-process. The output guard does
    not cover that branch. This holds the flag in place.
    """
    handler = mcp_app.request_handlers[types.CallToolRequest]
    assert getclosurevars(handler).nonlocals["validate_input"] is False


# --------------------------------------------------------------------------------------
# Layer 1: positive routing assertion, per call site and per schema shape.
# --------------------------------------------------------------------------------------


@pytest.mark.timeout(30)
@pytest.mark.parametrize("schema,valid,invalid,fragment", SHAPES)
def test_tool_input_path_routes_regex_schema_to_the_sandbox(submit, schema, valid, invalid, fragment):
    """Site 1 must submit a regex-bearing schema to the sandbox.

    Args:
        submit: The sandbox submission spy.
        schema: The regex-bearing schema shape under test.
        valid: An instance the schema accepts.
        invalid: Unused here.
        fragment: Unused here.
    """
    assert _validate_tool_input_arguments(valid, schema) is None
    assert submit.call_count == 1, "the tool input path validated a regex-bearing schema in-process"


@pytest.mark.timeout(30)
@pytest.mark.parametrize("schema,valid,invalid,fragment", SHAPES)
def test_tool_output_path_routes_regex_schema_to_the_sandbox(submit, schema, valid, invalid, fragment):
    """Site 2 must submit a regex-bearing schema to the sandbox.

    Args:
        submit: The sandbox submission spy.
        schema: The regex-bearing schema shape under test.
        valid: An instance the schema accepts.
        invalid: Unused here.
        fragment: Unused here.
    """
    _validate_with_cached_schema(valid, schema)
    assert submit.call_count == 1, "the tool output path validated a regex-bearing schema in-process"


@pytest.mark.timeout(30)
@pytest.mark.parametrize("schema,valid,invalid,fragment", SHAPES)
def test_prompt_path_routes_regex_schema_to_the_sandbox(submit, schema, valid, invalid, fragment):
    """Site 3 must submit a regex-bearing schema to the sandbox.

    Args:
        submit: The sandbox submission spy.
        schema: The regex-bearing schema shape under test.
        valid: An instance the schema accepts.
        invalid: Unused here.
        fragment: Unused here.
    """
    DbPrompt(name="p", template="hi {q}", argument_schema=schema).validate_arguments(valid)
    assert submit.call_count == 1, "the prompt path validated a regex-bearing schema in-process"


@pytest.mark.timeout(30)
def test_schema_without_a_regex_keyword_never_reaches_the_sandbox(submit):
    """No call site may pay for the sandbox when the schema carries no regex keyword.

    Args:
        submit: The sandbox submission spy.
    """
    assert _validate_tool_input_arguments({"q": "abc"}, PLAIN_SCHEMA) is None
    _validate_with_cached_schema({"q": "abc"}, PLAIN_SCHEMA)
    DbPrompt(name="p", template="hi {q}", argument_schema=PLAIN_SCHEMA).validate_arguments({"q": "abc"})
    assert submit.call_count == 0, "a schema with no regex keyword must be validated inline"


# --------------------------------------------------------------------------------------
# Layers 2 and 3: tripwires armed, per call site and per schema shape.
# --------------------------------------------------------------------------------------


@pytest.mark.timeout(30)
@pytest.mark.parametrize("schema,valid,invalid,fragment", SHAPES)
def test_tool_input_path_does_not_validate_in_process(tripwire, schema, valid, invalid, fragment):
    """Site 1 must reach no unbounded regex engine in this process.

    Args:
        tripwire: The armed in-process tripwires.
        schema: The regex-bearing schema shape under test.
        valid: An instance the schema accepts.
        invalid: Unused here.
        fragment: Unused here.
    """
    assert _validate_tool_input_arguments(valid, schema) is None


@pytest.mark.timeout(30)
@pytest.mark.parametrize("schema,valid,invalid,fragment", SHAPES)
def test_tool_output_path_does_not_validate_in_process(tripwire, schema, valid, invalid, fragment):
    """Site 2 shares the same helper and must behave the same.

    Args:
        tripwire: The armed in-process tripwires.
        schema: The regex-bearing schema shape under test.
        valid: An instance the schema accepts.
        invalid: Unused here.
        fragment: Unused here.
    """
    _validate_with_cached_schema(valid, schema)


@pytest.mark.timeout(30)
@pytest.mark.parametrize("schema,valid,invalid,fragment", SHAPES)
def test_prompt_path_does_not_validate_in_process(tripwire, schema, valid, invalid, fragment):
    """Site 3 previously called stock ``jsonschema.validate`` directly.

    Args:
        tripwire: The armed in-process tripwires.
        schema: The regex-bearing schema shape under test.
        valid: An instance the schema accepts.
        invalid: Unused here.
        fragment: Unused here.
    """
    DbPrompt(name="p", template="hi {q}", argument_schema=schema).validate_arguments(valid)


# --------------------------------------------------------------------------------------
# Layer 4: the SDK output-schema site, which no spy and no tripwire can route.
# --------------------------------------------------------------------------------------


@pytest.mark.timeout(30)
@pytest.mark.parametrize("schema,valid,invalid,fragment", SHAPES)
def test_to_mcp_tool_withholds_a_regex_bearing_output_schema(schema, valid, invalid, fragment):
    """The advertised tool model must carry no regex keyword the SDK could evaluate.

    Args:
        schema: The regex-bearing schema shape under test.
        valid: Unused here.
        invalid: Unused here.
        fragment: Unused here.
    """
    advertised = _to_mcp_tool(_tool_record(schema))
    assert advertised.outputSchema is None
    assert schema_uses_regex(advertised.model_dump()) is False


@pytest.mark.timeout(30)
@pytest.mark.parametrize("schema,valid,invalid,fragment", SHAPES)
def test_guard_proxied_tools_withholds_a_regex_bearing_output_schema(schema, valid, invalid, fragment):
    """Direct-proxy tools bypass ``_to_mcp_tool``, so they need the guard applied again.

    Args:
        schema: The regex-bearing schema shape under test.
        valid: Unused here.
        invalid: Unused here.
        fragment: Unused here.
    """
    proxied = types.Tool(name="probe_tool", inputSchema={"type": "object"}, outputSchema=schema)
    guarded = _guard_proxied_tools([proxied])[0]
    assert guarded.outputSchema is None
    assert schema_uses_regex(guarded.model_dump()) is False


@pytest.mark.timeout(30)
@pytest.mark.parametrize("schema,valid,invalid,fragment", SHAPES)
async def test_sdk_output_validation_sees_no_regex_keyword(tripwire, schema, valid, invalid, fragment):
    """The real SDK handler must evaluate no regex, for a tool the gateway advertises.

    The tool model is built by the production guard, so removing the guard makes this fail.

    Args:
        tripwire: The armed in-process tripwires.
        schema: The regex-bearing schema shape under test.
        valid: Unused here.
        invalid: Unused here.
        fragment: Unused here.
    """
    result = await _drive_sdk_call_tool(_to_mcp_tool(_tool_record(schema)))
    assert result.root.isError is False, result.root.content[0].text


@pytest.mark.timeout(30)
@pytest.mark.parametrize("schema,valid,invalid,fragment", SHAPES)
async def test_sdk_output_validation_sees_no_regex_keyword_from_a_proxied_tool(tripwire, schema, valid, invalid, fragment):
    """The same must hold for a tool proxied straight from a remote gateway.

    Args:
        tripwire: The armed in-process tripwires.
        schema: The regex-bearing schema shape under test.
        valid: Unused here.
        invalid: Unused here.
        fragment: Unused here.
    """
    proxied = types.Tool(name="probe_tool", inputSchema={"type": "object"}, outputSchema=schema)
    result = await _drive_sdk_call_tool(_guard_proxied_tools([proxied])[0])
    assert result.root.isError is False, result.root.content[0].text


# --------------------------------------------------------------------------------------
# Anti-vacuity: the sandbox must reject on the schema's own terms.
#
# Asserting only that an error occurred is not enough. Every fail-closed branch of
# ``validate_safely`` (no sandbox, non-stock draft, unserializable input, oversized
# instance, sandbox error) raises the same exception type entirely in-process, with no
# worker running. Naming the message fragment each schema produces excludes all of them.
# --------------------------------------------------------------------------------------


@pytest.mark.timeout(30)
@pytest.mark.parametrize("schema,valid,invalid,fragment", SHAPES)
def test_sandbox_rejects_on_the_schema_own_terms(tripwire, schema, valid, invalid, fragment):
    """A rejected instance must be reported with the message the schema itself produces.

    Args:
        tripwire: The armed in-process tripwires.
        schema: The regex-bearing schema shape under test.
        valid: Unused here.
        invalid: An instance the schema rejects.
        fragment: The message fragment only a real evaluation of this schema can produce.
    """
    message = _validate_tool_input_arguments(invalid, schema)
    assert message is not None and fragment in message, f"site 1 reported {message!r}, which no evaluation of this schema produces"

    with pytest.raises(jsonschema.exceptions.ValidationError) as tool_output:
        _validate_with_cached_schema(invalid, schema)
    assert fragment in str(tool_output.value)

    with pytest.raises(ValueError) as prompt:
        DbPrompt(name="p", template="hi {q}", argument_schema=schema).validate_arguments(invalid)
    assert fragment in str(prompt.value)
