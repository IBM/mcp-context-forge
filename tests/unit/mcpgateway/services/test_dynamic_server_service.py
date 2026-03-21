# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_dynamic_server_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Group 19

Unit tests for DynamicServerService CRUD operations and rule evaluation engine.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException

# First-Party
from mcpgateway.schemas import DynamicRuleCreate, DynamicServerCreate, DynamicServerUpdate
from mcpgateway.services.dynamic_server_service import (
    DynamicServerService,
    get_dynamic_server_service,
)


NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _make_rule(rule_type="tag", entity_type="tool", value="finance"):
    """Return a mock DbDynamicRule."""
    rule = MagicMock()
    rule.id = "rule-1"
    rule.rule_type = rule_type
    rule.entity_type = entity_type
    rule.value = value
    rule.created_at = NOW
    return rule


def _make_server(name="finance-tools", rules=None):
    """Return a mock DbDynamicServer."""
    server = MagicMock()
    server.id = "server-1"
    server.name = name
    server.description = None
    server.refresh_interval = None
    server.visibility = "public"
    server.created_at = NOW
    server.created_by = "admin@example.com"
    server.rules = rules if rules is not None else []
    return server


@pytest.fixture
def service():
    return DynamicServerService()


@pytest.fixture
def db():
    return MagicMock()


class TestCreateDynamicServer:
    def test_create_dynamic_server(self, service, db):
        """Happy path: server with one rule is created and returned."""
        db.execute.return_value.scalar_one_or_none.return_value = None  # no duplicate
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        data = DynamicServerCreate(
            name="finance-tools",
            rules=[DynamicRuleCreate(rule_type="tag", entity_type="tool", value="finance")],
        )
        user_ctx = {"email": "admin@example.com"}

        with patch.object(service, "_convert_to_read", return_value="server_read") as mock_convert:
            result = service.create_dynamic_server(db, data, user_ctx)

        assert result == "server_read"
        db.add.assert_called()
        db.flush.assert_called_once()
        db.commit.assert_called_once()
        mock_convert.assert_called_once()

    def test_create_duplicate_name_raises_400(self, service, db):
        """Duplicate name within same owner raises HTTPException 400."""
        db.execute.return_value.scalar_one_or_none.return_value = _make_server()
        data = DynamicServerCreate(name="finance-tools", rules=[])
        user_ctx = {"email": "admin@example.com"}

        with pytest.raises(HTTPException) as exc_info:
            service.create_dynamic_server(db, data, user_ctx)

        assert exc_info.value.status_code == 400
        assert "finance-tools" in exc_info.value.detail

    def test_create_team_scoped_server_sets_team_id(self, service, db):
        """Creating a team-scoped server passes team_id from the user's token."""
        db.execute.return_value.scalar_one_or_none.return_value = None
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        data = DynamicServerCreate(name="team-server", visibility="team", rules=[])
        user_ctx = {"email": "user@example.com", "teams": ["team-abc"]}

        with patch.object(service, "_convert_to_read", return_value="server_read"):
            service.create_dynamic_server(db, data, user_ctx)

        # The first db.add() call receives the DbDynamicServer instance
        added_server = db.add.call_args_list[0][0][0]
        assert added_server.team_id == "team-abc"
        assert added_server.visibility == "team"

    def test_create_team_scoped_no_team_raises_400(self, service, db):
        """Creating a team-scoped server with no team in token raises HTTPException 400."""
        data = DynamicServerCreate(name="team-server", visibility="team", rules=[])
        user_ctx = {"email": "user@example.com", "teams": []}

        with pytest.raises(HTTPException) as exc_info:
            service.create_dynamic_server(db, data, user_ctx)

        assert exc_info.value.status_code == 400
        assert "team" in exc_info.value.detail.lower()


class TestListDynamicServers:
    def test_list_dynamic_servers_public_only(self, service, db):
        """token_teams=[] → only public servers returned."""
        server = _make_server()
        db.execute.return_value.scalars.return_value.all.return_value = [server]

        with patch.object(service, "_convert_to_read", return_value="server_read"):
            result = service.list_dynamic_servers(db, token_teams=[])

        assert result == ["server_read"]

    def test_list_dynamic_servers_admin_bypass(self, service, db):
        """token_teams=None → no visibility filter (admin bypass)."""
        db.execute.return_value.scalars.return_value.all.return_value = []

        result = service.list_dynamic_servers(db, token_teams=None)

        assert result == []


class TestGetDynamicServer:
    def test_get_dynamic_server_not_found(self, service, db):
        """Missing server ID raises HTTPException 404."""
        db.execute.return_value.scalar_one_or_none.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            service.get_dynamic_server(db, "missing-id")

        assert exc_info.value.status_code == 404

    def test_get_dynamic_server_found(self, service, db):
        """Existing server is returned as DynamicServerRead."""
        server = _make_server(rules=[_make_rule()])
        db.execute.return_value.scalar_one_or_none.return_value = server

        with patch.object(service, "_convert_to_read", return_value="server_read"):
            result = service.get_dynamic_server(db, "server-1")

        assert result == "server_read"


class TestUpdateDynamicServer:
    def test_update_replaces_rules(self, service, db):
        """Providing rules in update deletes existing and inserts new ones."""
        old_rule = _make_rule(value="old")
        server = _make_server(rules=[old_rule])
        db.execute.return_value.scalar_one_or_none.return_value = server
        db.refresh = MagicMock(side_effect=lambda s: None)

        data = DynamicServerUpdate(
            rules=[DynamicRuleCreate(rule_type="regex", entity_type="resource", value="^new.*")]
        )

        with patch.object(service, "_convert_to_read", return_value="updated_read"):
            with patch("mcpgateway.services.dynamic_server_service.DbDynamicRule"):
                result = service.update_dynamic_server(db, "server-1", data)

        assert result == "updated_read"
        db.delete.assert_called_once_with(old_rule)
        db.flush.assert_called_once()
        db.commit.assert_called_once()

    def test_update_no_rules_leaves_existing(self, service, db):
        """Omitting rules in update leaves existing rules unchanged."""
        server = _make_server(rules=[_make_rule()])
        db.execute.return_value.scalar_one_or_none.return_value = server
        db.refresh = MagicMock(side_effect=lambda s: None)

        data = DynamicServerUpdate(description="new desc")

        with patch.object(service, "_convert_to_read", return_value="updated_read"):
            service.update_dynamic_server(db, "server-1", data)

        db.delete.assert_not_called()
        assert server.description == "new desc"

    def test_update_not_found_raises_404(self, service, db):
        """Missing server ID raises HTTPException 404."""
        db.execute.return_value.scalar_one_or_none.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            service.update_dynamic_server(db, "missing-id", DynamicServerUpdate())

        assert exc_info.value.status_code == 404

    def test_update_rename_conflict_raises_409(self, service, db):
        """Renaming to an existing server name raises HTTPException 409."""
        existing_server = _make_server(name="finance-tools")
        conflict_server = _make_server(name="risk-tools")
        conflict_server.id = "server-2"

        # First execute() call fetches the server to update;
        # second call is the uniqueness check which finds a conflict.
        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = existing_server
        second_result = MagicMock()
        second_result.scalar_one_or_none.return_value = conflict_server
        db.execute.side_effect = [first_result, second_result]

        data = DynamicServerUpdate(name="risk-tools")

        with pytest.raises(HTTPException) as exc_info:
            service.update_dynamic_server(db, "server-1", data)

        assert exc_info.value.status_code == 409
        assert "risk-tools" in exc_info.value.detail


class TestDeleteDynamicServer:
    def test_delete_cascades_rules(self, service, db):
        """Deleting a server calls db.delete once and commits."""
        server = _make_server(rules=[_make_rule()])
        db.get.return_value = server

        service.delete_dynamic_server(db, "server-1")

        db.delete.assert_called_once_with(server)
        db.commit.assert_called_once()

    def test_delete_not_found_raises_404(self, service, db):
        """Missing server ID raises HTTPException 404."""
        db.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            service.delete_dynamic_server(db, "missing-id")

        assert exc_info.value.status_code == 404


# ------------------------------------------------------------------ #
#  Rule evaluation helpers                                             #
# ------------------------------------------------------------------ #

def _make_tagged_entity(name, entity_type):
    """Return a mock TaggedEntity with .name and .type."""
    entity = MagicMock()
    entity.name = name
    entity.type = entity_type
    return entity


def _make_tool_search_result(tool_name, score=0.9):
    """Return a mock ToolSearchResult with .tool_name."""
    result = MagicMock()
    result.tool_name = tool_name
    result.similarity_score = score
    return result


def _make_db_tool(name, enabled=True):
    """Return a mock ORM Tool row."""
    tool = MagicMock()
    tool.original_name = name
    tool.enabled = enabled
    return tool


def _make_db_resource(name, enabled=True):
    """Return a mock ORM Resource row."""
    resource = MagicMock()
    resource.name = name
    resource.enabled = enabled
    return resource


def _make_db_prompt(name, enabled=True):
    """Return a mock ORM Prompt row."""
    prompt = MagicMock()
    prompt.name = name
    prompt.enabled = enabled
    return prompt


# ------------------------------------------------------------------ #
#  TestMatchByTag                                                      #
# ------------------------------------------------------------------ #


class TestMatchByTag:
    @pytest.mark.asyncio
    async def test_match_by_tag_returns_matching_names(self, service, db):
        """Tag rule returns entity names whose tag list contains the given tag."""
        tagged = [
            _make_tagged_entity("calc_tool", "tool"),
            _make_tagged_entity("other_tool", "tool"),
        ]
        with patch(
            "mcpgateway.services.dynamic_server_service._tag_service.get_entities_by_tag",
            new=AsyncMock(return_value=tagged),
        ):
            result = await service._match_by_tag(db, "tool", "finance")

        assert result == {"calc_tool", "other_tool"}

    @pytest.mark.asyncio
    async def test_match_by_tag_filters_by_entity_type(self, service, db):
        """TagService results of the wrong entity_type are excluded."""
        tagged = [
            _make_tagged_entity("my_tool", "tool"),
            _make_tagged_entity("my_resource", "resource"),  # mismatched type
        ]
        with patch(
            "mcpgateway.services.dynamic_server_service._tag_service.get_entities_by_tag",
            new=AsyncMock(return_value=tagged),
        ):
            result = await service._match_by_tag(db, "tool", "finance")

        assert result == {"my_tool"}
        assert "my_resource" not in result

    @pytest.mark.asyncio
    async def test_match_by_tag_empty_results(self, service, db):
        """No matching entities → empty set."""
        with patch(
            "mcpgateway.services.dynamic_server_service._tag_service.get_entities_by_tag",
            new=AsyncMock(return_value=[]),
        ):
            result = await service._match_by_tag(db, "tool", "nonexistent-tag")

        assert result == set()


# ------------------------------------------------------------------ #
#  TestMatchByRegex                                                    #
# ------------------------------------------------------------------ #


class TestMatchByRegex:
    @pytest.mark.asyncio
    async def test_match_by_regex_tools(self, service, db):
        """Regex rule matches tool original_name against pattern."""
        tools = [_make_db_tool("finance_calc"), _make_db_tool("weather_api"), _make_db_tool("finance_report")]
        db.execute.return_value.scalars.return_value.all.return_value = tools

        result = await service._match_by_regex(db, "tool", r"finance_.*")

        assert "finance_calc" in result
        assert "finance_report" in result
        assert "weather_api" not in result

    @pytest.mark.asyncio
    async def test_match_by_regex_resources(self, service, db):
        """Regex rule matches resource name field."""
        resources = [_make_db_resource("doc_finance"), _make_db_resource("doc_hr")]
        db.execute.return_value.scalars.return_value.all.return_value = resources

        result = await service._match_by_regex(db, "resource", r"doc_finance")

        assert result == {"doc_finance"}

    @pytest.mark.asyncio
    async def test_match_by_regex_invalid_pattern_raises(self, service, db):
        """Invalid regex raises ValueError (does not hit the DB)."""
        with pytest.raises(ValueError, match="Invalid regex"):
            await service._match_by_regex(db, "tool", r"[unclosed")

    @pytest.mark.asyncio
    async def test_match_by_regex_no_match(self, service, db):
        """Pattern that matches nothing returns empty set."""
        db.execute.return_value.scalars.return_value.all.return_value = [_make_db_tool("unrelated")]

        result = await service._match_by_regex(db, "tool", r"^finance_.*")

        assert result == set()


# ------------------------------------------------------------------ #
#  TestMatchByLlm                                                      #
# ------------------------------------------------------------------ #


class TestMatchByLlm:
    @pytest.mark.asyncio
    async def test_match_by_llm_tool_delegates_to_semantic_service(self, service, db):
        """LLM rule for tools calls SemanticSearchService.search_tools()."""
        mock_semantic = MagicMock()
        mock_semantic.search_tools = AsyncMock(return_value=[
            _make_tool_search_result("vector_tool"),
            _make_tool_search_result("embedding_tool"),
        ])

        with patch(
            "mcpgateway.services.dynamic_server_service.get_semantic_search_service",
            return_value=mock_semantic,
        ):
            result = await service._match_by_llm(db, "tool", "vector search utilities")

        assert result == {"vector_tool", "embedding_tool"}
        mock_semantic.search_tools.assert_called_once_with(query="vector search utilities", db=db, limit=50)

    @pytest.mark.asyncio
    async def test_match_by_llm_resource_uses_ilike_fallback(self, service, db):
        """LLM rule for resources falls back to ilike query (no vector index)."""
        resources = [_make_db_resource("finance_docs")]
        db.execute.return_value.scalars.return_value.all.return_value = resources

        result = await service._match_by_llm(db, "resource", "finance")

        assert "finance_docs" in result

    @pytest.mark.asyncio
    async def test_match_by_llm_prompt_uses_ilike_fallback(self, service, db):
        """LLM rule for prompts falls back to ilike query (no vector index)."""
        prompts = [_make_db_prompt("summarise_finance")]
        db.execute.return_value.scalars.return_value.all.return_value = prompts

        result = await service._match_by_llm(db, "prompt", "finance")

        assert "summarise_finance" in result

    @pytest.mark.asyncio
    async def test_match_by_llm_tool_empty_results(self, service, db):
        """Semantic search returning no results → empty set."""
        mock_semantic = MagicMock()
        mock_semantic.search_tools = AsyncMock(return_value=[])

        with patch(
            "mcpgateway.services.dynamic_server_service.get_semantic_search_service",
            return_value=mock_semantic,
        ):
            result = await service._match_by_llm(db, "tool", "obscure query")

        assert result == set()


# ------------------------------------------------------------------ #
#  TestEvaluateRules                                                   #
# ------------------------------------------------------------------ #


class TestEvaluateRules:
    @pytest.mark.asyncio
    async def test_evaluate_empty_rules(self, service, db):
        """No rules → all buckets empty."""
        result = await service._evaluate_rules(db, [])

        assert result == {"tools": [], "resources": [], "prompts": []}

    @pytest.mark.asyncio
    async def test_evaluate_mixed_rules(self, service, db):
        """Tag rule for tools + regex rule for resources both contribute."""
        tag_rule = DynamicRuleCreate(rule_type="tag", entity_type="tool", value="finance")
        regex_rule = DynamicRuleCreate(rule_type="regex", entity_type="resource", value=r"doc_finance")

        with (
            patch.object(service, "_match_by_tag", new=AsyncMock(return_value={"calc_tool"})),
            patch.object(service, "_match_by_regex", new=AsyncMock(return_value={"doc_finance"})),
        ):
            result = await service._evaluate_rules(db, [tag_rule, regex_rule])

        assert result["tools"] == ["calc_tool"]
        assert result["resources"] == ["doc_finance"]
        assert result["prompts"] == []

    @pytest.mark.asyncio
    async def test_evaluate_union_semantics_same_entity_type(self, service, db):
        """Two rules for the same entity_type are unioned (OR semantics)."""
        rule_a = DynamicRuleCreate(rule_type="tag", entity_type="tool", value="finance")
        rule_b = DynamicRuleCreate(rule_type="tag", entity_type="tool", value="analytics")

        with patch.object(
            service,
            "_match_by_tag",
            new=AsyncMock(side_effect=[{"tool_a"}, {"tool_b"}]),
        ):
            result = await service._evaluate_rules(db, [rule_a, rule_b])

        assert set(result["tools"]) == {"tool_a", "tool_b"}

    @pytest.mark.asyncio
    async def test_evaluate_unknown_rule_type_skipped(self, service, db):
        """Unknown rule_type is skipped without raising."""
        rule = MagicMock()
        rule.entity_type = "tool"
        rule.rule_type = "jsonpath"
        rule.value = "$.name"

        result = await service._evaluate_rules(db, [rule])

        assert result == {"tools": [], "resources": [], "prompts": []}


# ------------------------------------------------------------------ #
#  TestEvaluateCatalog                                                 #
# ------------------------------------------------------------------ #


class TestEvaluateCatalog:
    @pytest.mark.asyncio
    async def test_evaluate_catalog_returns_response(self, service, db):
        """evaluate_catalog loads server and delegates to _evaluate_rules."""
        server = _make_server(rules=[_make_rule()])
        db.execute.return_value.scalar_one_or_none.return_value = server

        with patch.object(
            service,
            "_evaluate_rules",
            new=AsyncMock(return_value={"tools": ["calc_tool"], "resources": [], "prompts": []}),
        ):
            response = await service.evaluate_catalog(db, "server-1")

        assert response.server_id == "server-1"
        assert response.server_name == "finance-tools"
        assert response.tools == ["calc_tool"]
        assert response.resources == []
        assert response.prompts == []

    @pytest.mark.asyncio
    async def test_evaluate_catalog_not_found_raises_404(self, service, db):
        """Missing server ID raises HTTPException 404."""
        db.execute.return_value.scalar_one_or_none.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await service.evaluate_catalog(db, "missing-id")

        assert exc_info.value.status_code == 404


# ------------------------------------------------------------------ #
#  TestPreviewCatalog                                                  #
# ------------------------------------------------------------------ #


class TestPreviewCatalog:
    @pytest.mark.asyncio
    async def test_preview_catalog_no_db_write(self, service, db):
        """preview_catalog never calls db.add, flush, or commit."""
        rules = [DynamicRuleCreate(rule_type="tag", entity_type="tool", value="finance")]

        with patch.object(
            service,
            "_evaluate_rules",
            new=AsyncMock(return_value={"tools": ["calc_tool"], "resources": [], "prompts": []}),
        ):
            response = await service.preview_catalog(db, rules)

        db.add.assert_not_called()
        db.flush.assert_not_called()
        db.commit.assert_not_called()
        assert response.server_id == "preview"
        assert response.tools == ["calc_tool"]

    @pytest.mark.asyncio
    async def test_preview_catalog_empty_rules(self, service, db):
        """Empty rule list → empty catalog."""
        with patch.object(
            service,
            "_evaluate_rules",
            new=AsyncMock(return_value={"tools": [], "resources": [], "prompts": []}),
        ):
            response = await service.preview_catalog(db, [])

        assert response.tools == []
        assert response.resources == []
        assert response.prompts == []


# ------------------------------------------------------------------ #
#  TestGetDynamicServerService                                         #
# ------------------------------------------------------------------ #


class TestGetDynamicServerService:
    def test_returns_dynamic_server_service_instance(self):
        """get_dynamic_server_service() returns a DynamicServerService."""
        svc = get_dynamic_server_service()
        assert isinstance(svc, DynamicServerService)

    def test_returns_singleton(self):
        """Repeated calls return the same object."""
        svc1 = get_dynamic_server_service()
        svc2 = get_dynamic_server_service()
        assert svc1 is svc2
