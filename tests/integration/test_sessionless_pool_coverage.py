"""
Integration tests for sessionless connection pool coverage.

These tests achieve coverage of the sessionless pool integration paths in:
- prompt_service.py lines 434-435 (exception handling)

Note: Additional coverage for resource_service.py and tool_service.py sessionless
pool paths is achieved through the existing unit tests in test_sessionless_pool_paths.py
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcpgateway.services.sessionless_connection_pool import SessionlessConnectionPoolNotInitializedError


@pytest.mark.asyncio
@pytest.mark.integration
async def test_prompt_service_sessionless_pool_not_initialized_exception():
    """
    Test prompt_service.py lines 434-435: SessionlessConnectionPoolNotInitializedError exception handling.

    When get_sessionless_connection_pool() raises SessionlessConnectionPoolNotInitializedError,
    the code should catch it and fall back to per-request client behavior.
    """
    from mcpgateway.services.prompt_service import PromptService
    from mcpgateway.db import Gateway, Prompt as DBPrompt
    from sqlalchemy.orm import Session

    # Create mock database session
    db = MagicMock(spec=Session)

    # Mock database query results
    mock_prompt = MagicMock(spec=DBPrompt)
    mock_prompt.id = "test-prompt-1"
    mock_prompt.name = "test_prompt"
    mock_prompt.gateway_id = "test-gw-1"
    mock_prompt.server_id = "test-srv-1"
    mock_prompt.is_active = True
    mock_prompt.visibility = "public"
    mock_prompt.team_id = "public"
    mock_prompt.description = "Test prompt"
    mock_prompt.arguments = []

    mock_gateway = MagicMock(spec=Gateway)
    mock_gateway.id = "test-gw-1"
    mock_gateway.url = "http://localhost:9000"
    mock_gateway.transport_type = "sse"
    mock_gateway.is_active = True

    # Setup query chain
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.options.return_value = mock_query
    mock_query.first.return_value = mock_prompt
    mock_query.one.return_value = mock_gateway

    db.query.return_value = mock_query
    db.commit = MagicMock()
    db.close = MagicMock()

    service = PromptService()

    # Mock _downstream_session_id_from_request to return None (triggers sessionless pool path)
    with patch("mcpgateway.services.prompt_service._downstream_session_id_from_request", return_value=None):
        # Mock _should_fetch_gateway_prompt to return True (remote fetch path)
        with patch.object(service, '_should_fetch_gateway_prompt', return_value=True):
            # Mock get_sessionless_connection_pool to raise the exception (lines 434-435)
            with patch("mcpgateway.services.sessionless_connection_pool.get_sessionless_connection_pool") as mock_get_pool:
                mock_get_pool.side_effect = SessionlessConnectionPoolNotInitializedError("Pool not initialized")

                # Mock the fallback per-request client path
                with patch("mcpgateway.services.prompt_service.sse_client") as mock_sse_client:
                    mock_read_stream = AsyncMock()
                    mock_write_stream = AsyncMock()
                    mock_sse_client.return_value.__aenter__.return_value = (mock_read_stream, mock_write_stream)

                    with patch("mcpgateway.services.prompt_service.ClientSession") as mock_client_session:
                        mock_session = AsyncMock()

                        # Mock the prompt result
                        from mcp.types import PromptMessage, TextContent
                        mock_prompt_result = MagicMock()
                        mock_prompt_result.messages = [
                            PromptMessage(role="user", content=TextContent(type="text", text="Test message"))
                        ]
                        mock_prompt_result.description = "Test description"

                        mock_session.get_prompt = AsyncMock(return_value=mock_prompt_result)
                        mock_client_session.return_value.__aenter__.return_value = mock_session

                        # This triggers lines 434-435 (exception handling)
                        result = await service.get_prompt(
                            db=db,
                            prompt_id="test-prompt-1",
                            arguments={},
                            user="test@example.com",
                            token_teams=["public"],
                        )

                    # Verify the exception was caught
                    assert mock_get_pool.called
                    assert result is not None
