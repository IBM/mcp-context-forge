# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_import_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for import service implementation.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import ToolCreate
from mcpgateway.services.import_service import ImportService, ImportStatus, ImportValidationError
from mcpgateway.services.root_service import RootServiceValidationError


@pytest.fixture
def import_service():
    """Create an import service instance with mocked dependencies."""
    service = ImportService()
    service.tool_service = AsyncMock()
    service.gateway_service = AsyncMock()
    service.server_service = AsyncMock()
    service.prompt_service = AsyncMock()
    service.resource_service = AsyncMock()
    service.root_service = AsyncMock()
    service.root_service.validate_root_input = MagicMock(side_effect=lambda uri, name=None: (uri, name))

    # Setup default return values for bulk registration methods
    service.tool_service.register_tools_bulk.return_value = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}
    service.prompt_service.register_prompts_bulk.return_value = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}
    service.resource_service.register_resources_bulk.return_value = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

    return service


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock()


@pytest.fixture
def valid_import_data():
    """Create valid import data for testing."""
    return {
        "version": "2025-03-26",
        "exported_at": "2025-01-01T00:00:00Z",
        "exported_by": "test_user",
        "entities": {
            "tools": [{"name": "test_tool", "url": "https://api.example.com/tool", "integration_type": "REST", "request_type": "GET", "description": "Test tool", "tags": ["api"]}],
            "gateways": [{"name": "test_gateway", "url": "https://gateway.example.com", "description": "Test gateway", "transport": "SSE"}],
        },
        "metadata": {"entity_counts": {"tools": 1, "gateways": 1}},
    }


@pytest.mark.asyncio
async def test_validate_import_data_success(import_service, valid_import_data):
    """Test successful import data validation."""
    # Should not raise any exception
    import_service.validate_import_data(valid_import_data)


@pytest.mark.asyncio
async def test_validate_import_data_maps_root_policy_error_without_uri(import_service):
    root_uri = "https://sensitive.example/root"
    import_service.root_service.validate_root_input.side_effect = RootServiceValidationError("scheme_not_allowed")
    import_data = {
        "version": "2025-03-26",
        "exported_at": "2025-01-01T00:00:00Z",
        "entities": {"roots": [{"uri": root_uri, "name": "Root"}]},
    }

    with pytest.raises(ImportValidationError) as excinfo:
        import_service.validate_import_data(import_data)

    assert "scheme_not_allowed" in str(excinfo.value)
    assert root_uri not in str(excinfo.value)


@pytest.mark.asyncio
async def test_validate_import_data_propagates_unexpected_root_validation_error(import_service):
    import_service.root_service.validate_root_input.side_effect = RuntimeError("boom")
    import_data = {
        "version": "2025-03-26",
        "exported_at": "2025-01-01T00:00:00Z",
        "entities": {"roots": [{"uri": "https://example.com/root", "name": "Root"}]},
    }

    with pytest.raises(RuntimeError, match="boom"):
        import_service.validate_import_data(import_data)


@pytest.mark.asyncio
async def test_validate_import_data_missing_version(import_service):
    """Test import data validation with missing version."""
    invalid_data = {"exported_at": "2025-01-01T00:00:00Z", "entities": {}}

    with pytest.raises(ImportValidationError) as excinfo:
        import_service.validate_import_data(invalid_data)

    assert "Missing required field: version" in str(excinfo.value)


@pytest.mark.asyncio
async def test_validate_import_data_invalid_entities(import_service):
    """Test import data validation with invalid entities structure."""
    invalid_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": "not_a_dict"}

    with pytest.raises(ImportValidationError) as excinfo:
        import_service.validate_import_data(invalid_data)

    assert "Entities must be a dictionary" in str(excinfo.value)


@pytest.mark.asyncio
async def test_validate_import_data_unknown_entity_type(import_service):
    """Test import data validation with unknown entity type."""
    invalid_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"unknown_type": []}}

    with pytest.raises(ImportValidationError) as excinfo:
        import_service.validate_import_data(invalid_data)

    assert "Unknown entity type: unknown_type" in str(excinfo.value)


@pytest.mark.asyncio
async def test_validate_entity_fields_missing_required(import_service):
    """Test entity field validation with missing required fields."""
    entity_data = {
        "url": "https://example.com"
        # Missing required 'name' field for tools
    }

    with pytest.raises(ImportValidationError) as excinfo:
        import_service._validate_entity_fields("tools", entity_data, 0)

    assert "missing required field: name" in str(excinfo.value)


@pytest.mark.asyncio
async def test_validate_import_data_invalid_entity_structure(import_service):
    """Test validation with non-dict entity in list."""
    invalid_data = {
        "version": "2025-03-26",
        "exported_at": "2025-01-01T00:00:00Z",
        "entities": {"tools": ["not_a_dict"]},  # Should be a dictionary
    }

    with pytest.raises(ImportValidationError) as excinfo:
        import_service.validate_import_data(invalid_data)

    assert "must be a dictionary" in str(excinfo.value)


@pytest.mark.asyncio
async def test_import_status_to_dict(import_service):
    """Test ImportStatus initialization and to_dict conversion."""
    # Create import status
    import_id = "test-import-123"
    status = ImportStatus(import_id)

    # Verify initial state
    assert status.import_id == import_id
    assert status.status == "pending"
    assert status.total_entities == 0
    assert status.processed_entities == 0
    assert status.created_entities == 0
    assert status.updated_entities == 0
    assert status.skipped_entities == 0
    assert status.failed_entities == 0
    assert len(status.errors) == 0
    assert len(status.warnings) == 0
    assert status.completed_at is None

    # Test to_dict method
    status_dict = status.to_dict()
    assert status_dict["import_id"] == import_id
    assert status_dict["status"] == "pending"
    assert "progress" in status_dict
    assert "errors" in status_dict
    assert "warnings" in status_dict
    assert "started_at" in status_dict
    assert status_dict["completed_at"] is None


@pytest.mark.asyncio
async def test_import_service_initialize_shutdown(import_service):
    """Test import service initialization and shutdown."""
    # Test initialization
    await import_service.initialize()

    # Test shutdown
    await import_service.shutdown()


@pytest.mark.asyncio
async def test_import_status_tracking(import_service):
    """Test import status tracking functionality."""
    import_id = "test_import_123"
    status = ImportStatus(import_id)
    status.imported_by = "operator@example.com"
    scope = {"imported_by": status.imported_by, "token_teams": None}
    import_service.active_imports[import_id] = status

    # Test status retrieval
    retrieved_status = import_service.get_import_status(import_id, **scope)
    assert retrieved_status == status
    assert retrieved_status.import_id == import_id

    # Test status listing
    all_statuses = import_service.list_import_statuses(**scope)
    assert status in all_statuses

    # Test status cleanup
    status.status = "completed"
    status.completed_at = datetime.now(timezone.utc)

    # Mock datetime to test cleanup
    with patch("mcpgateway.services.import_service.datetime") as mock_datetime:
        # Set current time to 25 hours after completion
        mock_datetime.now.return_value = status.completed_at + timedelta(hours=25)

        removed_count = import_service.cleanup_completed_imports(max_age_hours=24, **scope)
        assert removed_count == 1
        assert import_id not in import_service.active_imports


def test_status_operations_require_actor_and_token_scope(import_service):
    """Reject calls that omit the identity or its scope."""
    with pytest.raises(TypeError, match="imported_by"):
        import_service.get_import_status("known", token_teams=[])
    with pytest.raises(TypeError, match="token_teams"):
        import_service.list_import_statuses(imported_by="operator@example.com")
    with pytest.raises(TypeError, match="imported_by"):
        import_service.cleanup_completed_imports(token_teams=[])


@pytest.mark.parametrize(
    ("actor", "teams", "admin", "visible"),
    [
        (None, None, True, set()),
        ("other@example.com", ["one", "two"], False, set()),
        ("operator@example.com", ["one"], False, {"owned"}),
        ("operator@example.com", None, False, {"owned", "other-team", "unscoped"}),
        ("operator@example.com", None, True, {"owned", "other-team", "unscoped", "platform"}),
    ],
)
def test_status_lookup_list_and_cleanup_apply_same_scope(import_service, actor, teams, admin, visible):
    """Keep status lookup, listing, and cleanup within the caller's scope."""
    for key, request_teams in (("owned", {"one"}), ("other-team", {"two"}), ("unscoped", None), ("platform", None)):
        status = ImportStatus(key)
        status.imported_by = "operator@example.com"
        status.request_team_ids = frozenset(request_teams) if request_teams else None
        status.platform_scope = key == "platform"
        status.status = "completed"
        status.completed_at = datetime.now(timezone.utc) - timedelta(hours=25)
        import_service.active_imports[key] = status
    scope = {"imported_by": actor, "token_teams": teams, "unrestricted_admin": admin}
    assert {key for key in import_service.active_imports if import_service.get_import_status(key, **scope) is not None} == visible
    assert {status.import_id for status in import_service.list_import_statuses(**scope)} == visible
    assert import_service.cleanup_completed_imports(**scope) == len(visible)
    assert set(import_service.active_imports) == {"owned", "other-team", "unscoped", "platform"} - visible


@pytest.mark.asyncio
async def test_get_entity_identifier(import_service):
    """Test entity identifier extraction."""
    # Test tools (uses name)
    tool_entity = {"name": "test_tool", "url": "https://example.com"}
    assert import_service._get_entity_identifier("tools", tool_entity) == "test_tool"

    # Test resources (uses uri)
    resource_entity = {"name": "test_resource", "uri": "/api/data"}
    assert import_service._get_entity_identifier("resources", resource_entity) == "/api/data"

    # Test roots (uses uri)
    root_entity = {"name": "workspace", "uri": "file:///workspace"}
    assert import_service._get_entity_identifier("roots", root_entity) == "file:///workspace"


@pytest.mark.asyncio
async def test_calculate_total_entities(import_service):
    """Test entity count calculation with selection filters."""
    entities = {"tools": [{"name": "tool1"}, {"name": "tool2"}], "gateways": [{"name": "gateway1"}]}

    # Test without selection (should count all)
    total = import_service._calculate_total_entities(entities, None)
    assert total == 3

    # Test with selection
    selected_entities = {"tools": ["tool1"]}  # Only select one tool
    total = import_service._calculate_total_entities(entities, selected_entities)
    assert total == 1

    # Test with empty selection for entity type
    selected_entities = {"tools": []}  # Empty list means include all tools
    total = import_service._calculate_total_entities(entities, selected_entities)
    assert total == 2


@pytest.mark.asyncio
async def test_import_service_initialization(import_service):
    """Test import service initialization and shutdown."""
    # Test initialization
    await import_service.initialize()

    # Test shutdown
    await import_service.shutdown()


@pytest.mark.asyncio
async def test_import_status_tracking_complete_workflow(import_service):
    """Test complete import status tracking workflow."""
    import_id = "test_import_456"
    status = ImportStatus(import_id)
    status.imported_by = "operator@example.com"
    scope = {"imported_by": status.imported_by, "token_teams": None}

    # Test initial state
    assert status.status == "pending"
    assert status.total_entities == 0
    assert status.created_entities == 0

    # Test status updates
    status.status = "running"
    status.total_entities = 10
    status.processed_entities = 5
    status.created_entities = 3
    status.updated_entities = 2
    status.skipped_entities = 0
    status.failed_entities = 0

    # Test to_dict conversion
    status_dict = status.to_dict()
    assert status_dict["import_id"] == import_id
    assert status_dict["status"] == "running"
    assert status_dict["progress"]["total"] == 10
    assert status_dict["progress"]["created"] == 3
    assert status_dict["progress"]["updated"] == 2

    # Add to service tracking
    import_service.active_imports[import_id] = status

    # Test retrieval
    retrieved = import_service.get_import_status(import_id, **scope)
    assert retrieved == status

    # Test listing
    all_statuses = import_service.list_import_statuses(**scope)
    assert status in all_statuses


@pytest.mark.asyncio
async def test_get_entity_identifier_unknown_type(import_service):
    """Test _get_entity_identifier with unknown entity type returns empty string."""
    unknown_entity = {"data": "test"}
    result = import_service._get_entity_identifier("unknown_type", unknown_entity)
    assert result == ""  # Line 385


@pytest.mark.asyncio
async def test_prompt_update_conversion_with_schema(import_service):
    """Test prompt update conversion with input schema."""
    prompt_data = {
        "name": "update_prompt",
        "template": "Updated template: {{name}} {{value}}",
        "description": "Updated prompt description",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Name parameter"}, "value": {"type": "number", "description": "Value parameter"}},
            "required": ["name"],
        },
        "tags": ["prompt", "update"],
    }

    prompt_update = import_service._convert_to_prompt_update(prompt_data)
    assert prompt_update.name == "update_prompt"
    assert prompt_update.template == "Updated template: {{name}} {{value}}"
    assert prompt_update.description == "Updated prompt description"
    assert prompt_update.arguments is not None
    assert len(prompt_update.arguments) == 2
    assert prompt_update.arguments[0].name == "name"
    assert prompt_update.arguments[0].required == True
    assert prompt_update.arguments[1].name == "value"
    assert prompt_update.arguments[1].required == False
    assert prompt_update.tags == [{"id": "prompt", "label": "prompt"}, {"id": "update", "label": "update"}]


@pytest.mark.asyncio
async def test_prompt_update_conversion_no_schema(import_service):
    """Test prompt update conversion without input schema."""
    prompt_data = {"name": "simple_prompt", "template": "Simple template", "description": "Simple prompt", "tags": ["simple"]}

    prompt_update = import_service._convert_to_prompt_update(prompt_data)
    assert prompt_update.name == "simple_prompt"
    assert prompt_update.template == "Simple template"
    assert prompt_update.description == "Simple prompt"
    assert prompt_update.arguments is None  # No arguments when no schema
    assert prompt_update.tags == [{"id": "simple", "label": "simple"}]


@pytest.mark.asyncio
async def test_resource_update_conversion(import_service):
    """Test resource update schema conversion."""
    resource_data = {"name": "update_resource", "description": "Updated resource description", "mime_type": "application/xml", "content": "<xml>updated content</xml>", "tags": ["resource", "xml"]}

    resource_update = import_service._convert_to_resource_update(resource_data)
    assert resource_update.name == "update_resource"
    assert resource_update.description == "Updated resource description"
    assert resource_update.mime_type == "application/xml"
    assert resource_update.content == "<xml>updated content</xml>"
    assert resource_update.tags == [{"id": "resource", "label": "resource"}, {"id": "xml", "label": "xml"}]


# ============================================================================
# Bulk Registration Tests (from test_bulk_registration.py)
# ============================================================================

_SQLITE_TEST_SESSIONS = []


@pytest.fixture(autouse=True)
def cleanup_make_session_resources():
    """Close sessions/engines created by make_session() to avoid ResourceWarning leaks."""
    yield
    while _SQLITE_TEST_SESSIONS:
        session, engine = _SQLITE_TEST_SESSIONS.pop()
        try:
            session.close()
        except Exception:
            pass
        try:
            engine.dispose()
        except Exception:
            pass


def make_session():
    """Create an in-memory SQLite session for isolated tests."""
    # Third-Party
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # First-Party
    from mcpgateway.db import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    _SQLITE_TEST_SESSIONS.append((session, engine))
    return session


@pytest.mark.asyncio
async def test_register_tools_bulk_creates_and_returns_counts():
    """Test bulk tool registration creates tools and returns correct counts."""
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import Tool as DbTool
    from mcpgateway.services.tool_service import ToolService

    db = make_session()
    service = ToolService()
    service._notify_tool_added = AsyncMock()

    tools = [ToolCreate(name=f"tool{i}", url="http://example.com", integration_type="REST") for i in range(10)]

    result = await service.register_tools_bulk(db=db, tools=tools, created_by="tester", created_via="test", conflict_strategy="skip")

    assert result["created"] == 10
    # verify DB contains the created tools
    rows = db.execute(select(DbTool)).scalars().all()
    assert len(rows) == 10


@pytest.mark.asyncio
async def test_register_tools_bulk_conflict_skip():
    """Test bulk tool registration with skip conflict strategy."""
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import Tool as DbTool
    from mcpgateway.services.tool_service import ToolService

    db = make_session()
    service = ToolService()
    service._notify_tool_added = AsyncMock()

    # Pre-create one tool
    first = ToolCreate(name="dup", url="http://a", integration_type="REST")
    await service.register_tool(db, first)

    # Bulk with a duplicate name should be skipped
    tools = [ToolCreate(name="dup", url="http://b", integration_type="REST"), ToolCreate(name="new", url="http://c", integration_type="REST")]
    result = await service.register_tools_bulk(db=db, tools=tools, created_by="tester", created_via="test", conflict_strategy="skip")

    assert result["skipped"] >= 1
    assert result["created"] >= 1
    rows = db.execute(select(DbTool)).scalars().all()
    # Two or more tools expected (original + new)
    assert any(t.original_name == "dup" for t in rows)
    assert any(t.original_name == "new" for t in rows)


@pytest.mark.asyncio
async def test_register_prompts_bulk_creates_and_returns_counts():
    """Test bulk prompt registration creates prompts and returns correct counts."""
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import Prompt as DbPrompt
    from mcpgateway.services.prompt_service import PromptService
    from mcpgateway.schemas import PromptCreate

    db = make_session()
    service = PromptService()
    service._notify_prompt_added = AsyncMock()

    prompts = [PromptCreate(name=f"prompt{i}", template=f"Hello {{{{name{i}}}}}", description=f"Test prompt {i}") for i in range(10)]

    result = await service.register_prompts_bulk(db=db, prompts=prompts, created_by="tester", created_via="test", conflict_strategy="skip")

    assert result["created"] == 10
    # verify DB contains the created prompts
    rows = db.execute(select(DbPrompt)).scalars().all()
    assert len(rows) == 10


@pytest.mark.asyncio
async def test_register_prompts_bulk_conflict_skip():
    """Test bulk prompt registration with skip conflict strategy."""
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import Prompt as DbPrompt
    from mcpgateway.services.prompt_service import PromptService
    from mcpgateway.schemas import PromptCreate

    db = make_session()
    service = PromptService()
    service._notify_prompt_added = AsyncMock()

    # Pre-create one prompt
    first = PromptCreate(name="dup_prompt", template="Hello {{name}}", description="Duplicate prompt")
    await service.register_prompt(db, first)

    # Bulk with a duplicate name should be skipped
    prompts = [PromptCreate(name="dup_prompt", template="Updated {{name}}", description="Duplicate prompt updated"), PromptCreate(name="new_prompt", template="New {{user}}", description="New prompt")]
    result = await service.register_prompts_bulk(db=db, prompts=prompts, created_by="tester", created_via="test", conflict_strategy="skip")

    assert result["skipped"] >= 1
    assert result["created"] >= 1
    rows = db.execute(select(DbPrompt)).scalars().all()
    # Two or more prompts expected (original + new)
    assert any(p.original_name == "dup_prompt" for p in rows)
    assert any(p.original_name == "new_prompt" for p in rows)


@pytest.mark.asyncio
async def test_register_resources_bulk_creates_and_returns_counts():
    """Test bulk resource registration creates resources and returns correct counts."""
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import Resource as DbResource
    from mcpgateway.services.resource_service import ResourceService
    from mcpgateway.schemas import ResourceCreate

    db = make_session()
    service = ResourceService()
    service._notify_resource_added = AsyncMock()

    resources = [ResourceCreate(name=f"resource{i}", uri=f"file:///resource{i}.txt", description=f"Test resource {i}", mime_type="text/plain", content=f"Content for resource {i}") for i in range(10)]

    result = await service.register_resources_bulk(db=db, resources=resources, created_by="tester", created_via="test", conflict_strategy="skip")

    assert result["created"] == 10
    # verify DB contains the created resources
    rows = db.execute(select(DbResource)).scalars().all()
    assert len(rows) == 10


@pytest.mark.asyncio
async def test_register_resources_bulk_conflict_skip():
    """Test bulk resource registration with skip conflict strategy."""
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import Resource as DbResource
    from mcpgateway.services.resource_service import ResourceService
    from mcpgateway.schemas import ResourceCreate

    db = make_session()
    service = ResourceService()
    service._notify_resource_added = AsyncMock()

    # Pre-create one resource
    first = ResourceCreate(name="dup_resource", uri="file:///duplicate.txt", description="Duplicate resource", mime_type="text/plain", content="Original content")
    await service.register_resource(db, first)

    # Bulk with a duplicate URI should be skipped
    resources = [
        ResourceCreate(name="dup_resource_updated", uri="file:///duplicate.txt", description="Duplicate resource updated", mime_type="text/plain", content="Updated content"),
        ResourceCreate(name="new_resource", uri="file:///new.txt", description="New resource", mime_type="text/plain", content="New content"),
    ]
    result = await service.register_resources_bulk(db=db, resources=resources, created_by="tester", created_via="test", conflict_strategy="skip")

    assert result["skipped"] >= 1
    assert result["created"] >= 1
    rows = db.execute(select(DbResource)).scalars().all()
    # Two or more resources expected (original + new)
    assert any(r.uri == "file:///duplicate.txt" for r in rows)
    assert any(r.uri == "file:///new.txt" for r in rows)


# ---------- Individual entity conflict resolution paths ----------


# ============================================================================
# Coverage Gap Tests (mcpgateway/services/import_service.py)
# ============================================================================


@pytest.mark.asyncio
async def test_find_gateway_bundles_returns_empty_when_no_gateways(import_service):
    assert import_service._find_gateway_bundles({"tools": []}) == {}


@pytest.mark.asyncio
async def test_find_server_dependencies_returns_empty_when_no_servers(import_service):
    assert import_service._find_server_dependencies({"tools": []}) == {}
