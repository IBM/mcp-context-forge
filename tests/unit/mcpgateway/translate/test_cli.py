# -*- coding: utf-8 -*-
"""Unit tests for MCP Gateway Transport-Translation Bridge CLI.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

This module tests the CLI argument parsing, validation, and configuration
for the transport-translation bridge.
"""

import pytest
from unittest.mock import patch
import argparse

from mcpgateway.translate.cli import (
    create_parser,
    parse_headers,
    validate_args,
    determine_output_transport,
    setup_logging,
)


class TestCLIParsing:
    """Test CLI argument parsing functionality."""

    def test_create_parser_basic(self):
        """Test basic parser creation."""
        parser = create_parser()
        assert isinstance(parser, argparse.ArgumentParser)
        assert "MCP Gateway Transport-Translation Bridge" in parser.description

    def test_stdio_input_parsing(self):
        """Test parsing stdio input arguments."""
        parser = create_parser()
        args = parser.parse_args(["--stdio", "uvx mcp-server-git", "--port", "9000"])
        
        assert args.stdio == "uvx mcp-server-git"
        assert args.sse is None
        assert args.streamableHttp is None
        assert args.port == 9000

    def test_sse_input_parsing(self):
        """Test parsing SSE input arguments."""
        parser = create_parser()
        args = parser.parse_args(["--sse", "https://corp.example.com/mcp"])
        
        assert args.sse == "https://corp.example.com/mcp"
        assert args.stdio is None
        assert args.streamableHttp is None

    def test_streamable_http_input_parsing(self):
        """Test parsing streamable HTTP input arguments."""
        parser = create_parser()
        args = parser.parse_args(["--streamableHttp", "https://api.example.com/stream"])
        
        assert args.streamableHttp == "https://api.example.com/stream"
        assert args.stdio is None
        assert args.sse is None

    def test_output_transport_parsing(self):
        """Test parsing output transport options."""
        parser = create_parser()
        args = parser.parse_args(["--stdio", "test", "--outputTransport", "sse"])
        
        assert args.outputTransport == "sse"

    def test_header_parsing(self):
        """Test parsing header arguments."""
        parser = create_parser()
        args = parser.parse_args([
            "--stdio", "test",
            "--header", "Authorization:Bearer token123",
            "--header", "Content-Type:application/json"
        ])
        
        assert len(args.header) == 2
        assert "Authorization:Bearer token123" in args.header
        assert "Content-Type:application/json" in args.header

    def test_cors_parsing(self):
        """Test parsing CORS arguments."""
        parser = create_parser()
        args = parser.parse_args([
            "--stdio", "test",
            "--cors", "https://app.example.com", "https://dev.example.com"
        ])
        
        assert args.cors == ["https://app.example.com", "https://dev.example.com"]

    def test_oauth2_bearer_parsing(self):
        """Test parsing OAuth2 bearer token."""
        parser = create_parser()
        args = parser.parse_args(["--stdio", "test", "--oauth2Bearer", "secret123"])
        
        assert args.oauth2Bearer == "secret123"

    def test_health_endpoint_parsing(self):
        """Test parsing health endpoint."""
        parser = create_parser()
        args = parser.parse_args(["--stdio", "test", "--healthEndpoint", "/health"])
        
        assert args.healthEndpoint == "/health"

    def test_invalid_output_transport(self):
        """Test invalid output transport option."""
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--stdio", "test", "--outputTransport", "invalid"])

    def test_missing_required_input(self):
        """Test missing required input transport."""
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--port", "8000"])


class TestHeaderParsing:
    """Test header parsing functionality."""

    def test_parse_headers_valid(self):
        """Test parsing valid headers."""
        headers = ["Authorization:Bearer token", "Content-Type:application/json"]
        result = parse_headers(headers)
        
        assert result == {
            "Authorization": "Bearer token",
            "Content-Type": "application/json"
        }

    def test_parse_headers_with_spaces(self):
        """Test parsing headers with spaces."""
        headers = ["  Authorization  :  Bearer token  "]
        result = parse_headers(headers)
        
        assert result == {"Authorization": "Bearer token"}

    def test_parse_headers_with_colon_in_value(self):
        """Test parsing headers with colon in value."""
        headers = ["X-Custom:key:value:test"]
        result = parse_headers(headers)
        
        assert result == {"X-Custom": "key:value:test"}

    def test_parse_headers_invalid_format(self):
        """Test parsing invalid header format."""
        headers = ["InvalidHeader"]
        
        with pytest.raises(ValueError, match="Invalid header format"):
            parse_headers(headers)

    def test_parse_headers_empty_list(self):
        """Test parsing empty header list."""
        result = parse_headers([])
        assert result == {}


class TestArgumentValidation:
    """Test argument validation functionality."""

    def test_validate_args_valid_stdio(self):
        """Test validating valid stdio arguments."""
        args = argparse.Namespace(
            stdio="uvx mcp-server-git",
            sse=None,
            streamableHttp=None,
            port=8000,
            header=["Authorization:Bearer token"]
        )
        
        # Should not raise
        validate_args(args)

    def test_validate_args_valid_sse(self):
        """Test validating valid SSE arguments."""
        args = argparse.Namespace(
            stdio=None,
            sse="https://example.com/sse",
            streamableHttp=None,
            port=9000,
            header=[]
        )
        
        # Should not raise
        validate_args(args)

    def test_validate_args_multiple_inputs(self):
        """Test validation fails with multiple input transports."""
        args = argparse.Namespace(
            stdio="test",
            sse="https://example.com",
            streamableHttp=None,
            port=8000,
            header=[]
        )
        
        with pytest.raises(ValueError, match="Exactly one input transport"):
            validate_args(args)

    def test_validate_args_no_inputs(self):
        """Test validation fails with no input transports."""
        args = argparse.Namespace(
            stdio=None,
            sse=None,
            streamableHttp=None,
            port=8000,
            header=[]
        )
        
        with pytest.raises(ValueError, match="Exactly one input transport"):
            validate_args(args)

    def test_validate_args_invalid_port_low(self):
        """Test validation fails with port too low."""
        args = argparse.Namespace(
            stdio="test",
            sse=None,
            streamableHttp=None,
            port=0,
            header=[]
        )
        
        with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
            validate_args(args)

    def test_validate_args_invalid_port_high(self):
        """Test validation fails with port too high."""
        args = argparse.Namespace(
            stdio="test",
            sse=None,
            streamableHttp=None,
            port=65536,
            header=[]
        )
        
        with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
            validate_args(args)

    def test_validate_args_invalid_headers(self):
        """Test validation fails with invalid headers."""
        args = argparse.Namespace(
            stdio="test",
            sse=None,
            streamableHttp=None,
            port=8000,
            header=["InvalidHeader"]
        )
        
        with pytest.raises(ValueError, match="Invalid header"):
            validate_args(args)


class TestOutputTransportDetermination:
    """Test output transport determination logic."""

    def test_determine_output_explicit(self):
        """Test explicit output transport setting."""
        args = argparse.Namespace(
            outputTransport="ws",
            stdio="test",
            sse=None,
            streamableHttp=None
        )
        
        result = determine_output_transport(args)
        assert result == "ws"

    def test_determine_output_stdio_input(self):
        """Test output transport for stdio input."""
        args = argparse.Namespace(
            outputTransport=None,
            stdio="test",
            sse=None,
            streamableHttp=None
        )
        
        result = determine_output_transport(args)
        assert result == "sse"

    def test_determine_output_sse_input(self):
        """Test output transport for SSE input."""
        args = argparse.Namespace(
            outputTransport=None,
            stdio=None,
            sse="https://example.com",
            streamableHttp=None
        )
        
        result = determine_output_transport(args)
        assert result == "stdio"

    def test_determine_output_http_input(self):
        """Test output transport for HTTP input."""
        args = argparse.Namespace(
            outputTransport=None,
            stdio=None,
            sse=None,
            streamableHttp="https://example.com"
        )
        
        result = determine_output_transport(args)
        assert result == "stdio"


class TestLoggingSetup:
    """Test logging setup functionality."""

    @patch('mcpgateway.translate.cli.logging.basicConfig')
    def test_setup_logging_info(self, mock_config):
        """Test setting up info level logging."""
        setup_logging("info")
        mock_config.assert_called_once()

    @patch('mcpgateway.translate.cli.logging.basicConfig')
    def test_setup_logging_debug(self, mock_config):
        """Test setting up debug level logging."""
        setup_logging("debug")
        mock_config.assert_called_once()

    @patch('mcpgateway.translate.cli.logging.disable')
    def test_setup_logging_none(self, mock_disable):
        """Test disabling logging."""
        setup_logging("none")
        mock_disable.assert_called_once()
