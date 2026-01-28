# -*- coding: utf-8 -*-
"""Tests for translate_grpc helper conversions."""

# Standard
from types import SimpleNamespace

# First-Party
from mcpgateway import translate_grpc


class DummyField:
    def __init__(self, name, type_id, label=1, message_type=None):
        self.name = name
        self.type = type_id
        self.label = label
        self.message_type = message_type


class DummyDescriptor:
    def __init__(self, fields):
        self.fields = fields


def test_protobuf_field_to_json_schema_array():
    translator = translate_grpc.GrpcToMcpTranslator(endpoint=SimpleNamespace(_services={}, _pool=None))
    field = DummyField("names", type_id=9, label=3)
    schema = translator._protobuf_field_to_json_schema(field)
    assert schema["type"] == "array"


def test_protobuf_to_json_schema_nested():
    translator = translate_grpc.GrpcToMcpTranslator(endpoint=SimpleNamespace(_services={}, _pool=None))
    nested = DummyDescriptor([DummyField("value", type_id=9)])
    field = DummyField("child", type_id=11, message_type=nested)
    schema = translator.protobuf_to_json_schema(DummyDescriptor([field]))
    assert "child" in schema["properties"]
