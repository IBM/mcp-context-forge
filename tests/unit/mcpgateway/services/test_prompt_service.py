# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for prompt service implementation.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.schemas import PromptArgument, PromptCreate, PromptRead, PromptUpdate
from mcpgateway.services.prompt_service import (
    PromptError,
    PromptNameConflictError,
    PromptNotFoundError,
    PromptService,
    PromptValidationError,
)
from mcpgateway.types import Message, PromptResult, Role, TextContent


@pytest.fixture
def prompt_service():
    """Create a prompt service instance."""
    return PromptService()


@pytest.fixture
def mock_prompt():
    """Create a mock prompt model."""
    prompt = MagicMock(spec=DbPrompt)
    prompt.id = 1
    prompt.name = "test_prompt"
    prompt.description = "A test prompt"
    prompt.template = "This is a template with {{ param }}."
    prompt.argument_schema = {"type": "object", "properties": {"param": {"type": "string", "description": "A parameter"}}, "required": ["param"]}
    prompt.created_at = "2023-01-01T00:00:00"
    prompt.updated_at = "2023-01-01T00:00:00"
    prompt.is_active = True

    # Set up metrics
    prompt.metrics = []
    prompt.execution_count = 0
    prompt.successful_executions = 0
    prompt.failed_executions = 0
    prompt.failure_rate = 0.0
    prompt.min_response_time = None
    prompt.max_response_time = None
    prompt.avg_response_time = None
    prompt.last_execution_time = None

    # Set up validate_arguments
    prompt.validate_arguments = Mock()

    return prompt


class TestPromptService:
    """Tests for the PromptService class."""

    @pytest.mark.asyncio
    async def test_register_prompt(self, prompt_service, test_db):
        """Test successful prompt registration."""
        # Set up DB behavior
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Set up prompt service methods
        prompt_service._notify_prompt_added = AsyncMock()
        prompt_service._validate_template = Mock()
        prompt_service._get_required_arguments = Mock(return_value=set(["param"]))
        prompt_service._convert_db_prompt = Mock(
            return_value={
                "id": 1,
                "name": "test_prompt",
                "description": "A test prompt",
                "template": "This is a template with {{ param }}.",
                "arguments": [{"name": "param", "description": "", "required": True}],
                "created_at": "2023-01-01T00:00:00",
                "updated_at": "2023-01-01T00:00:00",
                "is_active": True,
                "metrics": {
                    "totalExecutions": 0,
                    "successfulExecutions": 0,
                    "failedExecutions": 0,
                    "failureRate": 0.0,
                    "minResponseTime": None,
                    "maxResponseTime": None,
                    "avgResponseTime": None,
                    "lastExecutionTime": None,
                },
            }
        )

        # Create prompt request
        prompt_create = PromptCreate(
            name="test_prompt", description="A test prompt", template="This is a template with {{ param }}.", arguments=[PromptArgument(name="param", description="A parameter", required=True)]
        )

        # Call method
        result = await prompt_service.register_prompt(test_db, prompt_create)

        # Verify DB operations
        test_db.add.assert_called_once()
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

        # Verify validation and notification
        prompt_service._validate_template.assert_called_once_with(prompt_create.template)
        prompt_service._notify_prompt_added.assert_called_once()

        # Verify result
        assert result.name == "test_prompt"
        assert result.description == "A test prompt"
        assert result.is_active is True
        assert any(arg.name == "param" for arg in result.arguments)

    @pytest.mark.asyncio
    async def test_register_prompt_name_conflict(self, prompt_service, mock_prompt, test_db):
        """Test prompt registration with name conflict."""
        # Mock DB to return existing prompt
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_prompt
        test_db.execute = Mock(return_value=mock_scalar)

        # Create prompt request with conflicting name
        prompt_create = PromptCreate(name="test_prompt", description="A new prompt", template="New template", arguments=[])  # Same name as mock_prompt

        # Should raise conflict error
        with pytest.raises(PromptNameConflictError) as exc_info:
            await prompt_service.register_prompt(test_db, prompt_create)

        assert "Prompt already exists with name" in str(exc_info.value)
        assert exc_info.value.name == "test_prompt"
        assert exc_info.value.is_active == mock_prompt.is_active
        assert exc_info.value.prompt_id == mock_prompt.id

    @pytest.mark.asyncio
    async def test_register_prompt_invalid_template(self, prompt_service, test_db):
        """Test prompt registration with invalid template."""
        # Mock DB behavior
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Set up prompt service to fail template validation
        prompt_service._validate_template = Mock(side_effect=PromptValidationError("Invalid template syntax"))

        # Create prompt request with invalid template
        prompt_create = PromptCreate(name="test_prompt", description="A test prompt", template="This is a template with {{ invalid syntax.", arguments=[])  # Invalid Jinja template

        # Should raise validation error
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.register_prompt(test_db, prompt_create)

        assert "Failed to register prompt" in str(exc_info.value)
        test_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_prompts(self, prompt_service, mock_prompt, test_db):
        """Test listing prompts."""
        # Mock DB to return a list of prompts
        mock_scalar_result = MagicMock()
        mock_scalar_result.all.return_value = [mock_prompt]
        mock_execute = Mock(return_value=mock_scalar_result)
        test_db.execute = mock_execute

        # Set up conversion
        prompt_read = PromptRead(
            id=1,
            name="test_prompt",
            description="A test prompt",
            template="This is a template with {{ param }}.",
            arguments=[PromptArgument(name="param", description="A parameter", required=True)],
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            is_active=True,
            metrics={
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            },
        )
        prompt_service._convert_db_prompt = Mock(return_value=prompt_read.model_dump(by_alias=True))

        # Call method
        result = await prompt_service.list_prompts(test_db)

        # Verify DB query
        test_db.execute.assert_called_once()

        # Verify result
        assert len(result) == 1
        assert result[0].name == "test_prompt"
        assert result[0].template == "This is a template with {{ param }}."
        prompt_service._convert_db_prompt.assert_called_once_with(mock_prompt)

    @pytest.mark.asyncio
    async def test_get_prompt(self, prompt_service, mock_prompt, test_db):
        """Test getting and rendering a prompt with arguments."""
        # Mock DB to return prompt
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_prompt
        test_db.execute = Mock(return_value=mock_scalar)

        # Set up prompt service methods
        prompt_service._render_template = Mock(return_value="This is a template with test value.")
        prompt_service._parse_messages = Mock(return_value=[Message(role=Role.USER, content=TextContent(type="text", text="This is a template with test value."))])

        # Call method with arguments
        result = await prompt_service.get_prompt(test_db, "test_prompt", {"param": "test value"})

        # Verify template rendering
        mock_prompt.validate_arguments.assert_called_once_with({"param": "test value"})
        prompt_service._render_template.assert_called_once_with(mock_prompt.template, {"param": "test value"})

        # Verify result
        assert isinstance(result, PromptResult)
        assert len(result.messages) == 1
        assert result.messages[0].role == Role.USER
        assert result.messages[0].content.text == "This is a template with test value."

    @pytest.mark.asyncio
    async def test_get_prompt_no_arguments(self, prompt_service, mock_prompt, test_db):
        """Test getting a prompt without arguments (template information only)."""
        # Mock DB to return prompt
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_prompt
        test_db.execute = Mock(return_value=mock_scalar)

        # Call method without arguments
        result = await prompt_service.get_prompt(test_db, "test_prompt", {})

        # Verify no rendering happened
        mock_prompt.validate_arguments.assert_not_called()

        # Verify result contains template information
        assert isinstance(result, PromptResult)
        assert len(result.messages) == 1
        assert result.messages[0].role == Role.USER
        assert result.messages[0].content.text == mock_prompt.template

    @pytest.mark.asyncio
    async def test_get_prompt_not_found(self, prompt_service, test_db):
        """Test getting a non-existent prompt."""
        # Mock DB to return None for active prompts
        mock_scalar1 = Mock()
        mock_scalar1.scalar_one_or_none.return_value = None
        # Mock DB to return None for inactive prompts
        mock_scalar2 = Mock()
        mock_scalar2.scalar_one_or_none.return_value = None
        test_db.execute = Mock(side_effect=[mock_scalar1, mock_scalar2])

        # Should raise NotFoundError
        with pytest.raises(PromptNotFoundError) as exc_info:
            await prompt_service.get_prompt(test_db, "nonexistent_prompt", {})

        assert "Prompt not found: nonexistent_prompt" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_prompt_inactive(self, prompt_service, mock_prompt, test_db):
        """Test getting an inactive prompt."""
        # Set prompt to inactive
        mock_prompt.is_active = False

        # Mock DB to return None for active prompts, but return the inactive prompt
        mock_scalar1 = Mock()
        mock_scalar1.scalar_one_or_none.return_value = None

        mock_scalar2 = Mock()
        mock_scalar2.scalar_one_or_none.return_value = mock_prompt

        test_db.execute = Mock(side_effect=[mock_scalar1, mock_scalar2])

        # Should raise NotFoundError with "inactive" message
        with pytest.raises(PromptNotFoundError) as exc_info:
            await prompt_service.get_prompt(test_db, "test_prompt", {})

        assert "Prompt 'test_prompt' exists but is inactive" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_prompt(self, prompt_service, mock_prompt, test_db):
        """Test updating a prompt."""
        # Mock DB to return prompt
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_prompt
        test_db.execute = Mock(return_value=mock_scalar)

        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Set up prompt service methods
        prompt_service._notify_prompt_updated = AsyncMock()
        prompt_service._validate_template = Mock()
        prompt_service._get_required_arguments = Mock(return_value=set(["new_param"]))
        prompt_service._convert_db_prompt = Mock(
            return_value={
                "id": 1,
                "name": "updated_prompt",
                "description": "An updated prompt",
                "template": "This is an updated template with {{ new_param }}.",
                "arguments": [{"name": "new_param", "description": "A new parameter", "required": True}],
                "created_at": "2023-01-01T00:00:00",
                "updated_at": "2023-01-01T00:00:00",
                "is_active": True,
                "metrics": {
                    "totalExecutions": 0,
                    "successfulExecutions": 0,
                    "failedExecutions": 0,
                    "failureRate": 0.0,
                    "minResponseTime": None,
                    "maxResponseTime": None,
                    "avgResponseTime": None,
                    "lastExecutionTime": None,
                },
            }
        )

        # Create update request
        prompt_update = PromptUpdate(
            name="updated_prompt",
            description="An updated prompt",
            template="This is an updated template with {{ new_param }}.",
            arguments=[PromptArgument(name="new_param", description="A new parameter", required=True)],
        )

        # Call method
        result = await prompt_service.update_prompt(test_db, "test_prompt", prompt_update)

        # Verify DB operations
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

        # Verify prompt properties were updated
        assert mock_prompt.name == "updated_prompt"
        assert mock_prompt.description == "An updated prompt"
        assert mock_prompt.template == "This is an updated template with {{ new_param }}."

        # Verify validation and notification
        prompt_service._validate_template.assert_called_once_with(prompt_update.template)
        prompt_service._notify_prompt_updated.assert_called_once()

        # Verify result
        assert result.name == "updated_prompt"
        assert result.description == "An updated prompt"
        assert result.template == "This is an updated template with {{ new_param }}."
        assert any(arg["name"] == "new_param" for arg in result.arguments)

    @pytest.mark.asyncio
    async def test_update_prompt_not_found(self, prompt_service, test_db):
        """Test updating a non-existent prompt."""
        # Mock DB to return None
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Create update request
        prompt_update = PromptUpdate(
            name="updated_prompt",
            description="An updated prompt",
            template="Updated template",
        )

        # Should raise NotFoundError
        with pytest.raises(PromptNotFoundError) as exc_info:
            await prompt_service.update_prompt(test_db, "nonexistent_prompt", prompt_update)

        assert "Prompt not found: nonexistent_prompt" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_prompt_name_conflict(self, prompt_service, mock_prompt, test_db):
        """Test updating a prompt with a name that conflicts with another prompt."""
        # Create a second prompt (the one being updated)
        prompt1 = mock_prompt

        # Create a conflicting prompt
        prompt2 = MagicMock(spec=DbPrompt)
        prompt2.id = 2
        prompt2.name = "existing_prompt"
        prompt2.is_active = True

        # Mock DB to return prompt1 for the first query and prompt2 for the second query
        mock_scalar1 = Mock()
        mock_scalar1.scalar_one_or_none.return_value = prompt1

        mock_scalar2 = Mock()
        mock_scalar2.scalar_one_or_none.return_value = prompt2

        test_db.execute = Mock(side_effect=[mock_scalar1, mock_scalar2])
        test_db.rollback = Mock()

        # Create update request with conflicting name
        prompt_update = PromptUpdate(
            name="existing_prompt",  # Name that conflicts with prompt2
        )

        # Should raise conflict error
        with pytest.raises(PromptNameConflictError) as exc_info:
            await prompt_service.update_prompt(test_db, "test_prompt", prompt_update)

        assert "Prompt already exists with name" in str(exc_info.value)
        assert exc_info.value.name == "existing_prompt"
        assert exc_info.value.is_active == prompt2.is_active
        assert exc_info.value.prompt_id == prompt2.id

        # Verify rollback
        test_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_prompt(self, prompt_service, mock_prompt, test_db):
        """Test deleting a prompt."""
        # Mock DB to return prompt
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_prompt
        test_db.execute = Mock(return_value=mock_scalar)

        test_db.delete = Mock()
        test_db.commit = Mock()

        # Set up prompt service methods
        prompt_service._notify_prompt_deleted = AsyncMock()

        # Call method
        await prompt_service.delete_prompt(test_db, "test_prompt")

        # Verify DB operations
        test_db.delete.assert_called_once_with(mock_prompt)
        test_db.commit.assert_called_once()

        # Verify notification
        prompt_service._notify_prompt_deleted.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_prompt_not_found(self, prompt_service, test_db):
        """Test deleting a non-existent prompt."""
        # Mock DB to return None
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Should raise NotFoundError
        with pytest.raises(PromptNotFoundError) as exc_info:
            await prompt_service.delete_prompt(test_db, "nonexistent_prompt")

        assert "Prompt not found: nonexistent_prompt" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_toggle_prompt_status(self, prompt_service, mock_prompt, test_db):
        """Test toggling prompt active status."""
        # Mock DB to return prompt
        test_db.get = Mock(return_value=mock_prompt)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Set up prompt service methods
        prompt_service._notify_prompt_activated = AsyncMock()
        prompt_service._notify_prompt_deactivated = AsyncMock()
        prompt_service._convert_db_prompt = Mock(
            return_value={
                "id": 1,
                "name": "test_prompt",
                "description": "A test prompt",
                "template": "This is a template with {{ param }}.",
                "arguments": [{"name": "param", "description": "A parameter", "required": True}],
                "created_at": "2023-01-01T00:00:00",
                "updated_at": "2023-01-01T00:00:00",
                "is_active": False,  # Deactivated
                "metrics": {
                    "totalExecutions": 0,
                    "successfulExecutions": 0,
                    "failedExecutions": 0,
                    "failureRate": 0.0,
                    "minResponseTime": None,
                    "maxResponseTime": None,
                    "avgResponseTime": None,
                    "lastExecutionTime": None,
                },
            }
        )

        # Deactivate the prompt (it's active by default)
        result = await prompt_service.toggle_prompt_status(test_db, 1, activate=False)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbPrompt, 1)
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

        # Verify properties were updated
        assert mock_prompt.is_active is False

        # Verify notification
        prompt_service._notify_prompt_deactivated.assert_called_once()
        prompt_service._notify_prompt_activated.assert_not_called()

        # Verify result
        assert result.is_active is False

    @pytest.mark.asyncio
    async def test_reset_metrics(self, prompt_service, test_db):
        """Test resetting metrics."""
        # Mock DB operations
        test_db.execute = Mock()
        test_db.commit = Mock()

        # Call method
        await prompt_service.reset_metrics(test_db)

        # Verify DB operations
        test_db.execute.assert_called_once()
        test_db.commit.assert_called_once()

    def test_validate_template(self, prompt_service):
        """Test template validation."""
        # Valid template
        prompt_service._validate_template("Hello {{ name }}!")

        # Invalid template
        with pytest.raises(PromptValidationError):
            prompt_service._validate_template("Hello {{ name")

    def test_get_required_arguments(self, prompt_service):
        """Test extraction of required arguments from template."""
        # Test Jinja2 style variables
        template = "Hello {{ name }}! Your age is {{ age }}."
        args = prompt_service._get_required_arguments(template)
        assert "name" in args
        assert "age" in args
        assert len(args) == 2

        # Test format style variables
        template = "Hello {name}! Your age is {age}."
        args = prompt_service._get_required_arguments(template)
        assert "name" in args
        assert "age" in args
        assert len(args) == 2

        # Test mixed styles
        template = "Hello {name}! Your age is {{ age }}."
        args = prompt_service._get_required_arguments(template)
        assert "name" in args
        assert "age" in args
        assert len(args) == 2

    def test_render_template(self, prompt_service):
        """Test template rendering."""
        # Test Jinja2 rendering
        template = "Hello {{ name }}!"
        rendered = prompt_service._render_template(template, {"name": "World"})
        assert rendered == "Hello World!"

        # Test format string fallback
        template = "Hello {name}!"
        rendered = prompt_service._render_template(template, {"name": "World"})
        assert rendered == "Hello World!"

        # Test with missing arguments
        with pytest.raises(PromptError):
            prompt_service._render_template("Hello {{ missing }}!", {})

    def test_parse_messages(self, prompt_service):
        """Test parsing rendered text into messages."""
        # Simple user message
        text = "This is a user message."
        messages = prompt_service._parse_messages(text)
        assert len(messages) == 1
        assert messages[0].role == Role.USER
        assert messages[0].content.text == "This is a user message."

        # Conversation with user and assistant
        text = "# User: This is a user message.\n# Assistant: This is an assistant response."
        messages = prompt_service._parse_messages(text)
        assert len(messages) == 2
        assert messages[0].role == Role.USER
        assert messages[0].content.text == "This is a user message."
        assert messages[1].role == Role.ASSISTANT
        assert messages[1].content.text == "This is an assistant response."

        # Multiple messages with same role
        text = "# User: First user message.\n# User: Second user message."
        messages = prompt_service._parse_messages(text)
        assert len(messages) == 2
        assert messages[0].role == Role.USER
        assert messages[0].content.text == "First user message."
        assert messages[1].role == Role.USER
        assert messages[1].content.text == "Second user message."
