# -*- coding: utf-8 -*-
"""Unit tests for small utility modules that had low coverage."""

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.utils.base_models import BaseModelWithConfigDict
from mcpgateway.utils.display_name import generate_display_name


def test_generate_display_name_empty_string() -> None:
    assert generate_display_name("") == ""


def test_generate_display_name_normalizes_separators_and_title_cases() -> None:
    assert generate_display_name("mixed_Case-Name.test") == "Mixed Case Name Test"
    assert generate_display_name("multiple___underscores") == "Multiple Underscores"
    assert generate_display_name("__tool--name..") == "Tool Name"
    # Technical name present but results in empty display name after normalization
    assert generate_display_name("___...---") == ""


def test_base_model_to_dict_uses_aliases_when_requested() -> None:
    class Example(BaseModelWithConfigDict):
        stop_reason: str = "endTurn"

    obj = Example()

    assert obj.to_dict(use_alias=False) == {"stop_reason": "endTurn"}
    assert obj.to_dict(use_alias=True) == {"stopReason": "endTurn"}


def test_base_model_to_dict_recurses_like_model_dump() -> None:
    class Child(BaseModel):
        child_field: str

    class Parent(BaseModelWithConfigDict):
        child: Child

    obj = Parent(child=Child(child_field="x"))

    # Ensure we call through to model_dump and preserve nested structure
    assert obj.to_dict(use_alias=False) == {"child": {"child_field": "x"}}
