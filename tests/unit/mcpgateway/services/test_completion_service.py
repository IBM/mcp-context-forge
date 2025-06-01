# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

"""

import pytest

from mcpgateway.services.completion_service import (  # :contentReference[oaicite:0]{index=0}:contentReference[oaicite:1]{index=1}
    CompletionError,
    CompletionService,
)
from mcpgateway.types import (
    CompleteResult,  # :contentReference[oaicite:2]{index=2}:contentReference[oaicite:3]{index=3}
)


class FakeScalarOneResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeScalarsAllResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class DummyPrompt:
    def __init__(self, name, argument_schema):
        self.name = name
        self.argument_schema = argument_schema
        self.is_active = True


class DummyResource:
    def __init__(self, uri):
        self.uri = uri
        self.is_active = True


@pytest.mark.asyncio
async def test_handle_completion_missing_ref_or_arg():
    service = CompletionService()
    with pytest.raises(CompletionError) as exc:
        await service.handle_completion(None, {})
    assert "Missing reference type or argument name" in str(exc.value)


@pytest.mark.asyncio
async def test_handle_completion_invalid_ref_type():
    service = CompletionService()
    request = {"ref": {"type": "ref/unknown"}, "argument": {"name": "arg", "value": ""}}
    with pytest.raises(CompletionError) as exc:
        await service.handle_completion(None, request)
    assert "Invalid reference type: ref/unknown" in str(exc.value)


@pytest.mark.asyncio
async def test_complete_prompt_missing_name():
    service = CompletionService()
    with pytest.raises(CompletionError) as exc:
        await service._complete_prompt_argument(None, {}, "arg1", "")
    assert "Missing prompt name" in str(exc.value)


@pytest.mark.asyncio
async def test_complete_prompt_not_found():
    service = CompletionService()

    class DummySession:
        def execute(self, query):
            return FakeScalarOneResult(None)

    with pytest.raises(CompletionError) as exc:
        await service._complete_prompt_argument(DummySession(), {"name": "nonexistent"}, "arg", "")
    assert "Prompt not found: nonexistent" in str(exc.value)


@pytest.mark.asyncio
async def test_complete_prompt_argument_not_found():
    service = CompletionService()
    prompt = DummyPrompt("p1", {"properties": {"p": {"name": "other"}}})

    class DummySession:
        def execute(self, query):
            return FakeScalarOneResult(prompt)

    with pytest.raises(CompletionError) as exc:
        await service._complete_prompt_argument(DummySession(), {"name": "p1"}, "arg", "")
    assert "Argument not found: arg" in str(exc.value)


@pytest.mark.asyncio
async def test_complete_prompt_enum_values():
    service = CompletionService()
    schema = {"properties": {"p": {"name": "arg1", "enum": ["Apple", "Banana", "Cherry"]}}}
    prompt = DummyPrompt("p1", schema)

    class DummySession:
        def execute(self, query):
            return FakeScalarOneResult(prompt)

    result = await service._complete_prompt_argument(DummySession(), {"name": "p1"}, "arg1", "an")
    assert isinstance(result, CompleteResult)
    comp = result.completion
    assert comp["values"] == ["Banana"]
    assert comp["total"] == 1
    assert comp["hasMore"] is False


@pytest.mark.asyncio
async def test_custom_completions_override_enum():
    service = CompletionService()
    service.register_completions("arg1", ["dog", "cat", "ferret"])
    schema = {"properties": {"p": {"name": "arg1"}}}
    prompt = DummyPrompt("p1", schema)

    class DummySession:
        def execute(self, query):
            return FakeScalarOneResult(prompt)

    result = await service._complete_prompt_argument(DummySession(), {"name": "p1"}, "arg1", "er")
    comp = result.completion
    assert comp["values"] == ["ferret"]
    assert comp["total"] == 1
    assert comp["hasMore"] is False


@pytest.mark.asyncio
async def test_complete_resource_missing_uri():
    service = CompletionService()

    class DummySession:
        pass

    with pytest.raises(CompletionError) as exc:
        await service._complete_resource_uri(DummySession(), {}, "arg", "")
    assert "Missing URI template" in str(exc.value)


@pytest.mark.asyncio
async def test_complete_resource_values():
    service = CompletionService()
    resources = [DummyResource("foo"), DummyResource("bar"), DummyResource("bazfoo")]

    class DummySession:
        def execute(self, query):
            return FakeScalarsAllResult(resources)

    result = await service._complete_resource_uri(DummySession(), {"uri": "template"}, "arg", "foo")
    comp = result.completion
    assert set(comp["values"]) == {"foo", "bazfoo"}
    assert comp["total"] == 2
    assert comp["hasMore"] is False


@pytest.mark.asyncio
async def test_unregister_completions():
    service = CompletionService()
    service.register_completions("arg1", ["a", "b"])
    service.unregister_completions("arg1")
    schema = {"properties": {"p": {"name": "arg1"}}}
    prompt = DummyPrompt("p1", schema)

    class DummySession:
        def execute(self, query):
            return FakeScalarOneResult(prompt)

    result = await service._complete_prompt_argument(DummySession(), {"name": "p1"}, "arg1", "a")
    comp = result.completion
    assert comp["values"] == []
    assert comp["total"] == 0
    assert comp["hasMore"] is False
