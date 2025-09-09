# -*- coding: utf-8 -*-
"""Tests for configuration management."""

# Standard
import os
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from agent_runtimes.langchain_agent.config import _parse_tools_list, get_settings, validate_environment


class TestParseToolsList:
    """Test tools list parsing function."""

    def test_parse_empty_string(self):
        """Test parsing empty string."""
        assert _parse_tools_list("") is None
        assert _parse_tools_list("   ") is None

    def test_parse_single_tool(self):
        """Test parsing single tool."""
        result = _parse_tools_list("tool1")
        assert result == ["tool1"]

    def test_parse_multiple_tools(self):
        """Test parsing multiple tools."""
        result = _parse_tools_list("tool1,tool2,tool3")
        assert result == ["tool1", "tool2", "tool3"]

    def test_parse_with_whitespace(self):
        """Test parsing with whitespace."""
        result = _parse_tools_list(" tool1 , tool2 , tool3 ")
        assert result == ["tool1", "tool2", "tool3"]

    def test_parse_with_empty_elements(self):
        """Test parsing with empty elements."""
        result = _parse_tools_list("tool1,,tool2,")
        assert result == ["tool1", "tool2"]


class TestGetSettings:
    """Test settings configuration."""

    def test_default_settings(self):
        """Test default settings values."""
        with patch.dict(os.environ, {}, clear=True):
            settings = get_settings()
            assert settings.mcp_gateway_url == "http://localhost:4444"
            assert settings.default_model == "gpt-4o-mini"
            assert settings.max_iterations == 10
            assert settings.temperature == 0.7
            assert settings.streaming_enabled is True

    def test_custom_settings(self):
        """Test custom settings from environment."""
        env_vars = {
            "MCP_GATEWAY_URL": "http://example.com:5555",
            "DEFAULT_MODEL": "gpt-4",
            "MAX_ITERATIONS": "5",
            "TEMPERATURE": "0.5",
            "STREAMING_ENABLED": "false",
            "TOOLS": "tool1,tool2"
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings = get_settings()
            assert settings.mcp_gateway_url == "http://example.com:5555"
            assert settings.default_model == "gpt-4"
            assert settings.max_iterations == 5
            assert settings.temperature == 0.5
            assert settings.streaming_enabled is False
            assert settings.tools_allowlist == ["tool1", "tool2"]


class TestValidateEnvironment:
    """Test environment validation."""

    def test_valid_environment(self):
        """Test validation with valid environment."""
        env_vars = {
            "OPENAI_API_KEY": "test-key",
            "MCPGATEWAY_BEARER_TOKEN": "test-token"
        }

        with patch.dict(os.environ, env_vars, clear=True):
            result = validate_environment()
            assert result["valid"] is True
            assert len(result["issues"]) == 0

    def test_missing_openai_key(self):
        """Test validation with missing OpenAI key."""
        with patch.dict(os.environ, {}, clear=True):
            result = validate_environment()
            assert result["valid"] is False
            assert any("OPENAI_API_KEY" in issue for issue in result["issues"])

    def test_missing_gateway_token(self):
        """Test validation with missing gateway token."""
        env_vars = {"OPENAI_API_KEY": "test-key"}

        with patch.dict(os.environ, env_vars, clear=True):
            result = validate_environment()
            assert any("MCPGATEWAY_BEARER_TOKEN" in warning for warning in result["warnings"])

    def test_invalid_numeric_values(self):
        """Test validation with invalid numeric values."""
        env_vars = {
            "OPENAI_API_KEY": "test-key",
            "MAX_ITERATIONS": "invalid",
            "TEMPERATURE": "not-a-number"
        }

        with patch.dict(os.environ, env_vars, clear=True):
            result = validate_environment()
            assert len(result["warnings"]) >= 2
