"""Plugin Administration Router.

This module provides REST API endpoints for managing plugin routing rules
and bulk plugin operations on tools, resources, and prompts.

Endpoints:
- /admin/plugin-routing/rules - Manage global routing rules
- /admin/tools/bulk/plugins - Bulk plugin operations on tools
- /admin/resources/bulk/plugins - Bulk plugin operations on resources
- /admin/prompts/bulk/plugins - Bulk plugin operations on prompts
"""

# Standard
# Standard Library
import json
import logging
from typing import Callable, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.admin import get_user_email
from mcpgateway.admin_helpers import (
    build_bulk_operation_response,
    parse_bulk_plugin_form_data,
    parse_plugin_config,
    parse_remove_plugin_form_data,
    validate_bulk_plugin_inputs,
    validate_remove_plugin_inputs,
)
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Tool as DbTool
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.services.plugin_service import get_plugin_service

LOGGER = logging.getLogger(__name__)

# Create router with /admin prefix to match existing admin endpoints
plugin_admin_router = APIRouter(prefix="/admin", tags=["plugin-admin"])


@plugin_admin_router.get("/plugin-routing/rules", response_class=HTMLResponse)
async def get_routing_rules(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Get the list of plugin routing rules.

    Returns HTML fragment showing all routing rules from the plugin routing config.

    Args:
        request: FastAPI request object.
        db: Database session.
        user: Authenticated user.

    Returns:
        TemplateResponse with routing rules list HTML or HTMLResponse with error.
    """
    try:
        # Check if plugins are enabled
        if not settings.plugins_enabled:
            root_path = request.scope.get("root_path", "")
            context = {
                "request": request,
                "root_path": root_path,
                "rules": [],
                "rules_by_type": {
                    "global": [],
                    "entity-type": [],
                    "tag-based": [],
                    "entity-specific": [],
                    "mixed": [],
                },
                "available_plugins": [],
                "rule_indices": [],
            }
            return request.app.state.templates.TemplateResponse("routing_rules_list.html", context)

        # First-Party
        from mcpgateway.plugins.framework import get_plugin_manager
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Reload config to ensure we have fresh data from disk
        plugin_manager = get_plugin_manager()
        if plugin_manager:
            plugin_manager.reload_config()
            LOGGER.info("Reloaded plugin config for get_routing_rules")

        route_service = get_plugin_route_service()

        # Get all routing rules from the config
        rules = []
        if route_service.config and route_service.config.routes:
            for idx, route in enumerate(route_service.config.routes):
                # Try to get display name from metadata, fallback to entity name filter, then to index
                display_name = route.metadata.get("display_name") if route.metadata else None
                if not display_name:
                    if isinstance(route.name, str):
                        display_name = route.name
                    elif isinstance(route.name, list) and route.name:
                        display_name = ", ".join(route.name)
                    else:
                        display_name = f"Rule {idx + 1}"

                # Determine rule type and specificity using constants
                # First-Party
                from mcpgateway.plugins.framework.constants import (
                    SPECIFICITY_SCORE_HOOK_FILTER,
                    SPECIFICITY_SCORE_NAME_MATCH,
                    SPECIFICITY_SCORE_TAG_MATCH,
                    SPECIFICITY_SCORE_WHEN_EXPRESSION,
                )

                rule_type = "global"  # Default to global
                specificity_score = 0
                entity_type_filters = []
                name_filters = []
                has_entity_types = False
                has_tags = False
                has_names = False

                # Check for entity type filtering
                if route.entities:
                    entity_type_filters = [str(e) for e in route.entities]
                    has_entity_types = True
                    # Entity type filtering doesn't add score (it's the baseline)

                # Check for tag-based matching
                if route.tags:
                    has_tags = True
                    specificity_score += SPECIFICITY_SCORE_TAG_MATCH

                # Check for specific entity name matches (highest specificity)
                if route.name:
                    if isinstance(route.name, str):
                        name_filters = [route.name]
                    elif isinstance(route.name, list):
                        name_filters = route.name
                    if name_filters:
                        has_names = True
                        specificity_score += SPECIFICITY_SCORE_NAME_MATCH

                # Check for hook type filtering
                if route.hooks:
                    specificity_score += SPECIFICITY_SCORE_HOOK_FILTER

                # Check for conditional (adds specificity)
                if route.when:
                    specificity_score += SPECIFICITY_SCORE_WHEN_EXPRESSION

                # Determine rule type based on most specific filter present
                # Entity type is treated as a baseline constraint, not a distinct filter type
                # Prioritize: name (most specific) → tags → entity type → global
                # Only mark as "mixed" when combining tags + names (rare case)

                if has_names and has_tags:
                    # Truly combining multiple semantic filters (unusual)
                    rule_type = "mixed"
                elif has_names:
                    # Most specific: targets specific named entities
                    rule_type = "entity-specific"
                elif has_tags:
                    # Medium specificity: matches by tags
                    rule_type = "tag-based"
                elif has_entity_types:
                    # Baseline specificity: filters by entity type
                    rule_type = "entity-type"
                else:
                    # No filters: applies globally
                    rule_type = "global"

                # Fetch matching entities for entity-type filters
                matching_entities = []
                name_filters_with_types = []

                if entity_type_filters and not name_filters:
                    # Only fetch preview if filtering by type but not by specific names
                    for entity_type in entity_type_filters:
                        if entity_type == "tool":
                            tools = db.query(DbTool).filter(DbTool.enabled).limit(10).all()
                            matching_entities.extend([{"type": "tool", "name": t.name, "id": str(t.id)} for t in tools])
                        elif entity_type == "prompt":
                            prompts = db.query(DbPrompt).filter(DbPrompt.enabled).limit(10).all()
                            matching_entities.extend([{"type": "prompt", "name": p.name, "id": str(p.id)} for p in prompts])
                        elif entity_type == "resource":
                            resources = db.query(DbResource).filter(DbResource.enabled).limit(10).all()
                            matching_entities.extend([{"type": "resource", "name": r.name, "id": str(r.id)} for r in resources])

                # When we have specific name filters, look up their types
                if name_filters and entity_type_filters:
                    for entity_type in entity_type_filters:
                        if entity_type == "tool":
                            for name in name_filters:
                                tool = db.query(DbTool).filter(DbTool.name == name).first()
                                if tool:
                                    name_filters_with_types.append({"type": "tool", "name": name})
                        elif entity_type == "prompt":
                            for name in name_filters:
                                prompt = db.query(DbPrompt).filter(DbPrompt.name == name).first()
                                if prompt:
                                    name_filters_with_types.append({"type": "prompt", "name": name})
                        elif entity_type == "resource":
                            for name in name_filters:
                                resource = db.query(DbResource).filter(DbResource.name == name).first()
                                if resource:
                                    name_filters_with_types.append({"type": "resource", "name": name})

                rule_data = {
                    "index": idx,
                    "name": display_name,
                    "rule_type": rule_type,
                    "specificity_score": specificity_score,
                    "entity_type_filters": entity_type_filters,
                    "name_filters": name_filters,
                    "name_filters_with_types": name_filters_with_types,  # Entity names with their types
                    "entities": [str(e) for e in (route.entities or [])],
                    "tags": route.tags or [],
                    "hooks": route.hooks or [],
                    "plugins": [
                        {
                            "name": p.name,
                            "priority": p.priority or 0,
                        }
                        for p in (route.plugins or [])
                    ],
                    "reverse_order_on_post": route.reverse_order_on_post or False,
                    "when": route.when or None,
                    "matching_entities": matching_entities,
                }
                rules.append(rule_data)

        # Group rules by type for better organization
        # Order matters: Global → Entity Type → Tag-based → Entity-specific → Mixed
        rules_by_type = {
            "global": [],
            "entity-type": [],
            "tag-based": [],
            "entity-specific": [],
            "mixed": [],
        }

        for rule in rules:
            rule_type = rule.get("rule_type", "global")
            if rule_type in rules_by_type:
                rules_by_type[rule_type].append(rule)
            else:
                rules_by_type["global"].append(rule)  # Fallback

        # Get available plugins for the modal
        plugin_service = get_plugin_service()
        available_plugins = plugin_service.get_all_plugins()

        # Get root_path for URL generation
        root_path = request.scope.get("root_path", "")

        # Get all rule indices for bulk operations
        rule_indices = [rule["index"] for rule in rules]

        context = {
            "request": request,
            "root_path": root_path,
            "rules": rules,
            "rules_by_type": rules_by_type,
            "available_plugins": available_plugins,
            "rule_indices": rule_indices,
        }

        return request.app.state.templates.TemplateResponse("routing_rules_list.html", context)

    except Exception as e:
        LOGGER.error(f"Error getting routing rules: {e}", exc_info=True)
        # Return error HTML instead of raising exception
        error_html = f"""
        <div class="p-8 text-center">
          <svg class="mx-auto h-12 w-12 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <h3 class="mt-2 text-sm font-medium text-gray-900 dark:text-gray-100">Error loading rules</h3>
          <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{str(e)}</p>
        </div>
        """
        return HTMLResponse(content=error_html)


@plugin_admin_router.get("/plugin-routing/entities")
async def get_entities_by_type(
    request: Request,
    entity_types: str = "",  # Comma-separated list of entity types
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Get entities filtered by type for plugin routing.

    Args:
        request: FastAPI request object.
        entity_types: Comma-separated list of entity types (tool, prompt, resource, agent, virtual_server, mcp_server).
        db: Database session.
        user: Authenticated user.

    Returns:
        JSON response with entities grouped by type.

    Raises:
        HTTPException: If there's an error fetching entities from the database.
    """
    try:
        # First-Party
        from mcpgateway.db import A2AAgent, Gateway, Prompt, Resource, Server, Tool

        result = {}
        types = [t.strip() for t in entity_types.split(",") if t.strip()]

        for entity_type in types:
            entities = []
            if entity_type == "tool":
                tools = db.query(Tool).filter(Tool.enabled).all()
                entities = [{"id": t.id, "name": t.name, "display_name": t.original_name} for t in tools]
            elif entity_type == "prompt":
                prompts = db.query(Prompt).filter(Prompt.enabled).all()
                entities = [{"id": p.id, "name": p.name, "display_name": p.name} for p in prompts]
            elif entity_type == "resource":
                resources = db.query(Resource).filter(Resource.enabled).all()
                entities = [{"id": r.id, "name": r.name, "display_name": r.name} for r in resources]
            elif entity_type == "agent":
                agents = db.query(A2AAgent).filter(A2AAgent.enabled).all()
                entities = [{"id": a.id, "name": a.name, "display_name": a.name} for a in agents]
            elif entity_type == "virtual_server":
                servers = db.query(Server).filter(Server.enabled).all()
                entities = [{"id": s.id, "name": s.name, "display_name": s.name} for s in servers]
            elif entity_type == "mcp_server":
                gateways = db.query(Gateway).filter(Gateway.enabled).all()
                entities = [{"id": g.id, "name": g.name, "display_name": g.name} for g in gateways]

            result[entity_type] = entities

        return result

    except Exception as e:
        LOGGER.error(f"Error fetching entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plugin_admin_router.get("/plugin-routing/tags")
async def get_all_entity_tags(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Get all unique tags from all entities for plugin routing autocomplete.

    Args:
        request: FastAPI request object.
        db: Database session.
        user: Authenticated user.

    Raises:
        HTTPException: If there's an error fetching entities from the database.

    Returns:
        JSON response with sorted list of unique tags.
    """
    try:
        # First-Party
        from mcpgateway.db import A2AAgent, Gateway, Prompt, Resource, Server, Tool

        all_tags = set()

        def add_tags_safely(entity_type, tags):
            """Safely add tags to set, handling various formats.

            Args:
                entity_type: Type of entity for logging purposes.
                tags: Tags to add (can be list of strings or list of dicts with id/label fields).
            """
            if not tags:
                LOGGER.info(f"{entity_type}: No tags (tags is None or empty)")
                return
            # Handle list (both strings and tag objects)
            if isinstance(tags, list):
                LOGGER.info(f"{entity_type}: Found tag list: {tags}")
                for tag in tags:
                    if isinstance(tag, str):
                        # Simple string tag
                        all_tags.add(tag)
                    elif isinstance(tag, dict):
                        # Tag object with 'id' or 'label' field
                        tag_value = tag.get("id") or tag.get("label")
                        if tag_value and isinstance(tag_value, str):
                            all_tags.add(tag_value)
            # Handle dict (unexpected but defensive)
            elif isinstance(tags, dict):
                # Skip dicts, log warning
                LOGGER.warning(f"{entity_type}: Tags stored as dict instead of list: {tags}")
            # Handle single string (edge case)
            elif isinstance(tags, str):
                LOGGER.info(f"{entity_type}: Found single tag string: {tags}")
                all_tags.add(tags)

        # Collect tags from all entity types
        tools = db.query(Tool).filter(Tool.enabled).all()
        for tool in tools:
            add_tags_safely(f"Tool[{tool.name}]", tool.tags)

        prompts = db.query(Prompt).filter(Prompt.enabled).all()
        for prompt in prompts:
            add_tags_safely(f"Prompt[{prompt.name}]", prompt.tags)

        resources = db.query(Resource).filter(Resource.enabled).all()
        for resource in resources:
            add_tags_safely(f"Resource[{resource.name}]", resource.tags)

        agents = db.query(A2AAgent).filter(A2AAgent.enabled).all()
        for agent in agents:
            add_tags_safely(f"A2AAgent[{agent.name}]", agent.tags)

        servers = db.query(Server).filter(Server.enabled).all()
        for server in servers:
            add_tags_safely(f"Server[{server.name}]", server.tags)

        gateways = db.query(Gateway).filter(Gateway.enabled).all()
        for gateway in gateways:
            add_tags_safely(f"Gateway[{gateway.name}]", gateway.tags)

        # Return sorted list
        result = sorted(list(all_tags))
        LOGGER.info(f"Returning {len(result)} unique tags: {result}")
        return result

    except Exception as e:
        LOGGER.error(f"Error fetching entity tags: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plugin_admin_router.get("/plugin-routing/rules/{rule_index}")
async def get_routing_rule(
    request: Request,
    rule_index: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Get a single routing rule by index.

    Args:
        request: FastAPI request object.
        rule_index: Index of the rule to retrieve.
        db: Database session.
        user: Authenticated user.

    Returns:
        JSON response with the rule data.
    """
    try:
        # First-Party
        from mcpgateway.plugins.framework import get_plugin_manager
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Reload config to ensure we have fresh data from disk
        plugin_manager = get_plugin_manager()
        if plugin_manager:
            plugin_manager.reload_config()
            LOGGER.info("Reloaded plugin config for get_routing_rule")

        route_service = get_plugin_route_service()
        rule = await route_service.get_rule(rule_index)

        if not rule:
            return JSONResponse(content={"error": f"Rule at index {rule_index} not found"}, status_code=404)

        # Get display name from metadata or fallback
        display_name = rule.metadata.get("display_name") if rule.metadata else None
        if not display_name:
            if isinstance(rule.name, str):
                display_name = rule.name
            elif isinstance(rule.name, list) and rule.name:
                display_name = ", ".join(rule.name)
            else:
                display_name = f"Rule {rule_index + 1}"

        # Convert entity name filter to string for the name_filter field
        name_filter = ""
        if isinstance(rule.name, str):
            name_filter = rule.name
        elif isinstance(rule.name, list):
            name_filter = ", ".join(rule.name)

        # Convert rule to dict for JSON serialization
        rule_data = {
            "index": rule_index,
            "display_name": display_name,  # Rule display name for UI
            "name_filter": name_filter,  # Entity name filter
            "entities": [str(e) for e in (rule.entities or [])],
            "tags": rule.tags or [],
            "hooks": rule.hooks or [],
            "plugins": [{"name": p.name, "priority": p.priority or 0} for p in (rule.plugins or [])],
            "reverse_order_on_post": rule.reverse_order_on_post or False,
            "when": rule.when or "",
        }

        return JSONResponse(content=rule_data)

    except Exception as e:
        LOGGER.error(f"Error getting routing rule {rule_index}: {e}", exc_info=True)
        return JSONResponse(content={"error": str(e)}, status_code=500)


@plugin_admin_router.post("/plugin-routing/rules/bulk-delete")
async def bulk_delete_routing_rules(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Bulk delete routing rules by indices.

    Args:
        request: FastAPI request object with JSON body containing 'indices' array.
        db: Database session.
        user: Authenticated user.

    Returns:
        HTML response with the updated rules list.
    """
    try:
        # Standard
        import json

        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Parse request body
        body = await request.body()
        data = json.loads(body)
        indices = [int(idx) for idx in data.get("indices", [])]

        if not indices:
            return HTMLResponse(content="No rules selected for deletion", status_code=400)

        route_service = get_plugin_route_service()

        # Sort indices in descending order to delete from end to start
        # This prevents index shifting issues
        sorted_indices = sorted(indices, reverse=True)

        deleted_count = 0
        failed_indices = []

        for rule_index in sorted_indices:
            try:
                success = await route_service.delete_rule(rule_index)
                if success:
                    deleted_count += 1
                else:
                    failed_indices.append(rule_index)
            except Exception as e:
                LOGGER.error(f"Error deleting rule at index {rule_index}: {e}")
                failed_indices.append(rule_index)

        # Log the bulk operation
        LOGGER.info(f"User {get_user_email(user)} bulk deleted {deleted_count} routing rules")

        if failed_indices:
            LOGGER.warning(f"Failed to delete rules at indices: {failed_indices}")

        # Return updated rules list (HTMX will replace the content)
        return await get_routing_rules(request, db, user)

    except json.JSONDecodeError as e:
        LOGGER.error(f"Invalid JSON in bulk delete request: {e}")
        return HTMLResponse(content="Invalid request format", status_code=400)
    except Exception as e:
        LOGGER.error(f"Error in bulk delete: {e}", exc_info=True)
        return HTMLResponse(content=f"Error: {str(e)}", status_code=500)


@plugin_admin_router.post("/plugin-routing/rules")
@plugin_admin_router.post("/plugin-routing/rules/{rule_index}")
async def create_or_update_routing_rule(
    request: Request,
    rule_index: Optional[int] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Create a new routing rule or update an existing one.

    Args:
        request: FastAPI request object.
        rule_index: Optional index of the rule to update (from path).
        db: Database session.
        user: Authenticated user.

    Returns:
        HTML response with the updated rules list.
    """
    try:
        # First-Party
        from mcpgateway.plugins.framework.models import EntityType, PluginAttachment, PluginHookRule
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Parse form data
        form_data = await request.form()

        # Extract form fields
        rule_name = form_data.get("rule_name", "").strip()
        if not rule_name:
            return HTMLResponse(content="Rule name is required", status_code=400)

        # Check if this is a global rule
        is_global = form_data.get("is_global", "false").lower() == "true"

        # Parse entities
        entities = form_data.getlist("entities")
        if is_global:
            # For global rules, always set entity_types to None
            entity_types = None
        else:
            entity_types = [EntityType(e) for e in entities] if entities else []
            entity_types = entity_types or None  # Convert empty list to None

        # Parse name filter (can be comma-separated)
        name_filter = form_data.get("name_filter", "").strip()
        name_list = None
        if name_filter:
            names = [n.strip() for n in name_filter.split(",") if n.strip()]
            name_list = names[0] if len(names) == 1 else names if names else None

        # Parse tags - filter empty strings and convert empty list to None
        tags = form_data.getlist("tags")
        tags = [t.strip() for t in tags if t.strip()] or None

        # Parse hooks - filter empty strings and convert empty list to None
        hooks = form_data.getlist("hooks")
        hooks = [h.strip() for h in hooks if h.strip()] or None

        # Parse when expression
        when_expression = form_data.get("when_expression", "").strip()
        when_expression = when_expression if when_expression else None

        # Parse reverse order flag
        reverse_order_on_post = form_data.get("reverse_order_on_post") == "true"

        # Debug logging to see what we received
        LOGGER.info(f"Parsed routing rule data: entities={entity_types}, name_list={name_list}, " f"tags={tags}, hooks={hooks}, when={when_expression}")

        # Global rules support: Allow rules with no matching criteria
        # Empty rules (no filters) will match ALL entities and hooks globally
        # This enables baseline/default plugin configurations that apply everywhere
        # The rule_resolver.py matching logic handles empty rules correctly

        # Parse plugins JSON
        # Standard
        import json

        plugins_json = form_data.get("plugins", "[]")
        plugins_data = json.loads(plugins_json)

        if not plugins_data:
            return HTMLResponse(content="At least one plugin is required", status_code=400)

        # Create PluginAttachment objects with advanced configuration
        plugin_attachments = []
        for p in plugins_data:
            if not p.get("name"):
                continue

            # Parse config JSON if present
            config = {}
            config_str = p.get("config", "").strip()
            if config_str:
                try:
                    config = json.loads(config_str)
                except json.JSONDecodeError as e:
                    LOGGER.warning(f"Invalid JSON in plugin config for {p['name']}: {e}")
                    # Continue with empty dict rather than failing

            # Parse when expression
            when = p.get("when", "").strip() or None

            # Parse override flag
            override = p.get("override", False)
            if isinstance(override, str):
                override = override.lower() in ("true", "1", "yes")

            # Parse mode (convert empty string to None)
            mode = p.get("mode", "").strip() or None

            plugin_attachments.append(
                PluginAttachment(
                    name=p["name"],
                    priority=int(p.get("priority", 10)),
                    config=config,
                    when=when,
                    override=override,
                    mode=mode,
                )
            )

        # Check if rule_index is also in form data (for update)
        form_rule_index = form_data.get("rule_index")
        if form_rule_index is not None and form_rule_index != "":
            rule_index = int(form_rule_index)

        # Create PluginHookRule
        # Note: 'name' field is for entity name filtering, not rule display name
        # We'll store the display name in metadata
        rule = PluginHookRule(
            name=name_list,  # Entity name filter
            entities=entity_types,
            tags=tags,
            hooks=hooks,
            when=when_expression,
            reverse_order_on_post=reverse_order_on_post,
            plugins=plugin_attachments,
            metadata={"display_name": rule_name},  # Store friendly name in metadata
        )

        # Save to config (add_or_update_rule saves internally with file locking)
        route_service = get_plugin_route_service()
        index = await route_service.add_or_update_rule(rule, rule_index)

        LOGGER.info(f"User {get_user_email(user)} {'updated' if rule_index is not None else 'created'} routing rule at index {index}")

        # Return updated rules list (HTMX will replace the content)
        return await get_routing_rules(request, db, user)

    except Exception as e:
        LOGGER.error(f"Error creating/updating routing rule: {e}", exc_info=True)
        return HTMLResponse(content=f"Error: {str(e)}", status_code=500)


@plugin_admin_router.delete("/plugin-routing/rules/{rule_index}")
async def delete_routing_rule(
    request: Request,
    rule_index: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Delete a routing rule by index.

    Args:
        request: FastAPI request object.
        rule_index: Index of the rule to delete.
        db: Database session.
        user: Authenticated user.

    Returns:
        HTML response with the updated rules list.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        route_service = get_plugin_route_service()
        success = await route_service.delete_rule(rule_index)

        if not success:
            return HTMLResponse(content=f"Rule at index {rule_index} not found", status_code=404)

        # Note: delete_rule saves internally with file locking

        LOGGER.info(f"User {get_user_email(user)} deleted routing rule at index {rule_index}")

        # Return updated rules list (HTMX will replace the content)
        return await get_routing_rules(request, db, user)

    except ValueError as e:
        LOGGER.error(f"Error deleting routing rule {rule_index}: {e}")
        return HTMLResponse(content=str(e), status_code=400)
    except Exception as e:
        LOGGER.error(f"Error deleting routing rule {rule_index}: {e}", exc_info=True)
        return HTMLResponse(content=f"Error: {str(e)}", status_code=500)


async def _get_entity_by_id(db: Session, entity_type: str, entity_id: str):
    """Helper to get an entity by ID and type.

    Args:
        db: Database session.
        entity_type: Type of entity (tool, prompt, resource).
        entity_id: Entity ID (UUID string).

    Returns:
        The entity model object.

    Raises:
        HTTPException: If entity not found.
    """
    if entity_type == "tool":
        entity = db.query(DbTool).filter(DbTool.id == entity_id).first()
        entity_name = "Tool"
    elif entity_type == "prompt":
        entity = db.query(DbPrompt).filter(DbPrompt.id == entity_id).first()
        entity_name = "Prompt"
    elif entity_type == "resource":
        entity = db.query(DbResource).filter(DbResource.id == entity_id).first()
        entity_name = "Resource"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported entity type: {entity_type}")

    if not entity:
        raise HTTPException(status_code=404, detail=f"{entity_name} {entity_id} not found")

    return entity


async def _get_plugins_for_entity_and_hook(
    route_service,
    entity_type: str,
    entity_name: str,
    entity_id: str,
    tags: list[str],
    server_name: Optional[str],
    server_id: Optional[str],
    hook_type: str,
):
    """Helper to get plugins for a specific entity and hook type.

    This calls the route service with a specific hook_type so the resolver
    applies proper ordering (including post-hook reversal if configured).

    Args:
        route_service: PluginRouteService instance.
        entity_type: Type of entity.
        entity_name: Name of entity.
        entity_id: Entity ID.
        tags: Entity tags.
        server_name: Server name.
        server_id: Server ID.
        hook_type: Specific hook type to resolve plugins for.

    Returns:
        List of plugin data dicts with name, priority, and config.
    """
    plugins = await route_service.get_routes_for_entity(
        entity_type=entity_type,
        entity_name=entity_name,
        entity_id=entity_id,
        tags=tags,
        server_name=server_name,
        server_id=server_id,
        hook_type=hook_type,
    )

    return [{"name": p.name, "priority": p.priority, "config": p.config} for p in plugins]


async def _get_entity_plugins_ui_context(
    request: Request,
    entity_type: str,
    entity_id: str,
    db: Session,
) -> dict:
    """Generic helper to get plugin UI context for any entity type.

    This function extracts the common logic for displaying plugin management UI
    across tools, resources, and prompts.

    Args:
        request: FastAPI request object.
        entity_type: Type of entity (tool, resource, prompt).
        entity_id: Entity ID (UUID string).
        db: Database session.

    Returns:
        Context dict for rendering the entity_plugins_partial.html template.

    Raises:
        HTTPException: If entity not found or other errors occur.
    """
    # First-Party
    from mcpgateway.plugins.framework import get_plugin_manager
    from mcpgateway.plugins.framework.hooks.registry import get_hook_registry, HookPhase
    from mcpgateway.services.plugin_route_service import get_plugin_route_service

    # Get entity from database
    entity = await _get_entity_by_id(db, entity_type, entity_id)

    # Get services
    route_service = get_plugin_route_service()
    hook_registry = get_hook_registry()

    # Reload config from disk to see changes from other workers
    plugin_manager = get_plugin_manager()
    if plugin_manager:
        plugin_manager.reload_config()

    # Get pre and post hook types for this entity using the registry
    pre_hook_types = hook_registry.get_hooks_for_entity_type(entity_type, HookPhase.PRE)
    post_hook_types = hook_registry.get_hooks_for_entity_type(entity_type, HookPhase.POST)

    # Get plugins for each hook type (resolver applies correct ordering)
    pre_hooks = []
    post_hooks = []

    # Get first server if entity has server relationship
    first_server = entity.servers[0] if hasattr(entity, "servers") and entity.servers else None

    # Use first pre-hook type (typically {entity}_pre_invoke)
    if pre_hook_types:
        pre_hook_value = pre_hook_types[0].value if hasattr(pre_hook_types[0], "value") else pre_hook_types[0]
        pre_hooks = await _get_plugins_for_entity_and_hook(
            route_service,
            entity_type=entity_type,
            entity_name=entity.name,
            entity_id=str(entity.id),
            tags=entity.tags or [],
            server_name=first_server.name if first_server else None,
            server_id=str(first_server.id) if first_server else None,
            hook_type=str(pre_hook_value),
        )

    # Use first post-hook type (typically {entity}_post_invoke)
    if post_hook_types:
        post_hook_value = post_hook_types[0].value if hasattr(post_hook_types[0], "value") else post_hook_types[0]
        post_hooks = await _get_plugins_for_entity_and_hook(
            route_service,
            entity_type=entity_type,
            entity_name=entity.name,
            entity_id=str(entity.id),
            tags=entity.tags or [],
            server_name=first_server.name if first_server else None,
            server_id=str(first_server.id) if first_server else None,
            hook_type=str(post_hook_value),
        )

    # Get available plugins from plugin manager
    available_plugins = []
    if plugin_manager:
        available_plugins = [{"name": name} for name in plugin_manager.get_plugin_names()]

    # Get reverse post-hooks state for this entity
    reverse_post_hooks = route_service.get_reverse_post_hooks_state(
        entity_type=entity_type,
        entity_name=entity.name,
    )

    # Calculate next suggested priority (max existing + 10, or 10 if none)
    all_plugins = pre_hooks + post_hooks
    max_priority = max((p.get("priority", 0) or 0 for p in all_plugins), default=0)
    next_priority = max_priority + 10 if max_priority > 0 else 10

    # Get root_path for URL generation
    root_path = request.scope.get("root_path", "")

    # Get hook type names for display (convert enums to string values)
    if pre_hook_types:
        pre_hook_name = str(pre_hook_types[0].value if hasattr(pre_hook_types[0], "value") else pre_hook_types[0])
    else:
        pre_hook_name = f"{entity_type}_pre_invoke"

    if post_hook_types:
        post_hook_name = str(post_hook_types[0].value if hasattr(post_hook_types[0], "value") else post_hook_types[0])
    else:
        post_hook_name = f"{entity_type}_post_invoke"

    return {
        "request": request,
        "root_path": root_path,
        "entity_type": entity_type,
        "entity_id": entity.id,
        "entity_name": entity.name,
        "pre_hooks": pre_hooks,
        "post_hooks": post_hooks,
        "pre_hook_name": pre_hook_name,
        "post_hook_name": post_hook_name,
        "available_plugins": available_plugins,
        "reverse_post_hooks": reverse_post_hooks,
        "next_priority": next_priority,
    }


async def _add_entity_plugin_handler(
    request: Request,
    entity_type: str,
    entity_id: str,
    db: Session,
    plugins_ui_getter: Callable,
):
    """Generic handler to add a plugin to any entity type.

    Args:
        request: The HTTP request object.
        entity_type: The type of entity: prompt, tool, resource, etc.
        entity_id: The entity id.
        db: The database session, which stores metadata about the entity.
        plugins_ui_getter: The specific function that returns the proper plugin modal depending on the entity type.

    Returns:
        Updated plugins UI HTML response from plugins_ui_getter.

    Raises:
        HTTPException: if there is no plugin name provided or the plugin configuration is not valid.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Parse form data
        form_data = await request.form()
        plugin_name = form_data.get("plugin_name")
        priority = int(form_data.get("priority", 10))
        hooks = form_data.getlist("hooks") if "hooks" in form_data else None
        reverse_order_on_post = form_data.get("reverse_order_on_post") == "true"

        # Parse advanced fields
        config_str = form_data.get("config", "").strip()
        config = None
        if config_str:
            try:
                config = json.loads(config_str)
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON in config: {e}")

        override = form_data.get("override") == "true"
        mode = form_data.get("mode") or None

        if not plugin_name:
            raise HTTPException(status_code=400, detail="Plugin name is required")

        # Get entity from database
        entity = await _get_entity_by_id(db, entity_type, entity_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Add simple route
        await route_service.add_simple_route(
            entity_type=entity_type,
            entity_name=entity.name,
            plugin_name=plugin_name,
            priority=priority,
            hooks=hooks if hooks else None,
            reverse_order_on_post=reverse_order_on_post,
            config=config,
            override=override,
            mode=mode,
        )

        # Save configuration
        await route_service.save_config()

        LOGGER.info(f"Added plugin {plugin_name} to {entity_type} {entity.name}")

        # Return updated plugins UI
        return await plugins_ui_getter(request, entity_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error adding {entity_type} plugin: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _remove_entity_plugin_handler(
    request: Request,
    entity_type: str,
    entity_id: str,
    plugin_name: str,
    hook: Optional[str],
    db: Session,
    plugins_ui_getter: Callable,
):
    """Generic handler to remove a plugin from any entity type.

    Args:
        request: The HTTP request object.
        entity_type: The type of entity: prompt, tool, resource, etc.
        entity_id: The entity id.
        plugin_name: The name of the plugin to remove.
        hook: The hook on which to remove the plugin (optional).
        db: The database session, which stores metadata about the entity.
        plugins_ui_getter: The specific function that returns the proper plugin modal depending on the entity type.

    Returns:
        Updated plugins UI HTML response from plugins_ui_getter.

    Raises:
        HTTPException: If unable to remove the plugin.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Get entity from database
        entity = await _get_entity_by_id(db, entity_type, entity_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Remove plugin from entity
        removed = await route_service.remove_plugin_from_entity(
            entity_type=entity_type,
            entity_name=entity.name,
            plugin_name=plugin_name,
            hook=hook,
        )

        if not removed:
            hook_msg = f" for hook {hook}" if hook else ""
            raise HTTPException(
                status_code=404,
                detail=f"Plugin {plugin_name} not found in simple rules for {entity_type} {entity.name}{hook_msg}",
            )

        # Save configuration
        await route_service.save_config()

        hook_msg = f" from {hook}" if hook else ""
        LOGGER.info(f"Removed plugin {plugin_name}{hook_msg} from {entity_type} {entity.name}")

        # Return updated plugins UI
        return await plugins_ui_getter(request, entity_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error removing {entity_type} plugin: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _toggle_entity_reverse_post_hooks_handler(
    request: Request,
    entity_type: str,
    entity_id: str,
    db: Session,
    plugins_ui_getter: Callable,
):
    """Generic handler to toggle reverse_order_on_post for any entity type.

    Args:
        request: The HTTP request object.
        entity_type: The type of entity: prompt, tool, resource, etc.
        entity_id: The entity id.
        db: The database session, which stores metadata about the entity.
        plugins_ui_getter: The specific function that returns the proper plugin modal depending on the entity type.

    Returns:
        Updated plugins UI HTML response from plugins_ui_getter.

    Raises:
        HTTPException: If unable to toggle reverse order on a plugin.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Get entity from database
        entity = await _get_entity_by_id(db, entity_type, entity_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Toggle reverse_order_on_post
        new_state = await route_service.toggle_reverse_post_hooks(
            entity_type=entity_type,
            entity_name=entity.name,
        )

        LOGGER.info(f"Toggled reverse_order_on_post to {new_state} for {entity_type} {entity.name}")

        # Return updated plugins UI
        return await plugins_ui_getter(request, entity_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error toggling reverse post hooks for {entity_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _change_entity_plugin_priority_handler(
    request: Request,
    entity_type: str,
    entity_id: str,
    plugin_name: str,
    hook: str,
    direction: str,
    db: Session,
    plugins_ui_getter: Callable,
):
    """Generic handler to change plugin priority (up/down) for any entity type.

    Args:
        request: The HTTP request object.
        entity_type: The type of entity: prompt, tool, resource, etc.
        entity_id: The entity id.
        plugin_name: The name of the plugin to change priority for.
        hook: The name of the hook to which the priority is being changed.
        direction: Up or down.
        db: The database session, which stores metadata about the entity.
        plugins_ui_getter: The specific function that returns the proper plugin modal depending on the entity type.

    Returns:
        Updated plugins UI HTML response from plugins_ui_getter.

    Raises:
        HTTPException: If unable to change the priority on a plugin.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Get entity from database
        entity = await _get_entity_by_id(db, entity_type, entity_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Change priority
        success = await route_service.change_plugin_priority(
            entity_type=entity_type,
            entity_name=entity.name,
            plugin_name=plugin_name,
            hook=hook,
            direction=direction,
        )

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Plugin {plugin_name} not found or cannot be moved {direction}",
            )

        LOGGER.info(f"Changed priority of plugin {plugin_name} ({direction}) for {entity_type} {entity.name}")

        # Return updated plugins UI
        return await plugins_ui_getter(request, entity_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error changing {entity_type} plugin priority: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _set_entity_plugin_priority_handler(
    request: Request,
    entity_type: str,
    entity_id: str,
    plugin_name: str,
    hook: str,
    db: Session,
    plugins_ui_getter: Callable,
):
    """Generic handler to set plugin priority to absolute value for any entity type.

    Args:
        request: The HTTP request object.
        entity_type: The type of entity: prompt, tool, resource, etc.
        entity_id: The entity id.
        plugin_name: the name of the plugin.
        hook: The name of the hook to which the priority is being changed.
        db: The database session, which stores metadata about the entity.
        plugins_ui_getter: The specific function that returns the proper plugin modal depending on the entity type.

    Returns:
        Updated plugins UI HTML response from plugins_ui_getter.

    Raises:
        HTTPException: If unable to set the priority on a plugin.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Parse form data
        form_data = await request.form()
        new_priority = int(form_data.get("priority", 10))

        # Get entity from database
        entity = await _get_entity_by_id(db, entity_type, entity_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Update priority
        success = await route_service.update_plugin_priority(
            entity_type=entity_type,
            entity_name=entity.name,
            plugin_name=plugin_name,
            new_priority=new_priority,
            hook=hook,
        )

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Plugin {plugin_name} not found for {entity_type} {entity.name}",
            )

        LOGGER.info(f"Set priority of plugin {plugin_name} to {new_priority} for {entity_type} {entity.name}")

        # Return updated plugins UI
        return await plugins_ui_getter(request, entity_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error setting {entity_type} plugin priority: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plugin_admin_router.get("/tools/{tool_id}/plugins", response_class=JSONResponse)
async def get_tool_plugins(
    _request: Request,
    tool_id: str,
    db: Session = Depends(get_db),
):
    """Get plugins that apply to a specific tool.

    Returns both pre-invoke and post-invoke plugins with their execution order.
    Post-hooks are shown in their actual execution order (may be reversed based on config).

    Args:
        _request: HTTP request object.
        tool_id: The id of the tool to get the plugins for.
        db: The database session from which to return the tool metadata.

    Returns:
        Dictionary with tool_id, tool_name, pre_hooks list, and post_hooks list.

    Raises:
        HTTPException: If tool not found or error retrieving plugin information.
    """
    try:
        # First-Party
        from mcpgateway.plugins.framework.hooks.registry import get_hook_registry, HookPhase
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Get tool from database
        tool = await _get_entity_by_id(db, "tool", tool_id)

        # Get services
        route_service = get_plugin_route_service()
        hook_registry = get_hook_registry()

        # Get pre and post hook types for tools using the registry
        pre_hook_types = hook_registry.get_hooks_for_entity_type("tool", HookPhase.PRE)
        post_hook_types = hook_registry.get_hooks_for_entity_type("tool", HookPhase.POST)

        # Get plugins for each hook type (resolver applies correct ordering)
        pre_hooks = []
        post_hooks = []

        # Tool has many-to-many with servers, get first if available
        first_server = tool.servers[0] if tool.servers else None

        # Use first pre-hook type (typically tool_pre_invoke)
        if pre_hook_types:
            pre_hooks = await _get_plugins_for_entity_and_hook(
                route_service,
                entity_type="tool",
                entity_name=tool.name,
                entity_id=str(tool.id),
                tags=tool.tags or [],
                server_name=first_server.name if first_server else None,
                server_id=str(first_server.id) if first_server else None,
                hook_type=pre_hook_types[0],
            )

        # Use first post-hook type (typically tool_post_invoke)
        if post_hook_types:
            post_hooks = await _get_plugins_for_entity_and_hook(
                route_service,
                entity_type="tool",
                entity_name=tool.name,
                entity_id=str(tool.id),
                tags=tool.tags or [],
                server_name=first_server.name if first_server else None,
                server_id=str(first_server.id) if first_server else None,
                hook_type=post_hook_types[0],
            )

        return {
            "tool_id": tool.id,
            "tool_name": tool.name,
            "pre_hooks": pre_hooks,
            "post_hooks": post_hooks,
        }

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error getting tool plugins: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Bulk plugin operations (must be before parameterized routes)
@plugin_admin_router.get("/tools/bulk/plugins/status", response_class=JSONResponse)
async def get_bulk_plugin_status(
    request: Request,
    tool_ids: str = Query(..., description="Comma-separated list of tool IDs"),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Get plugin configuration status for multiple tools.

    Returns which plugins are configured on all, some, or none of the selected tools.

    Args:
        request: FastAPI request object
        tool_ids: Comma-separated tool IDs
        db: Database session
        _user: Current authenticated user

    Returns:
        JSON with plugin status breakdown

    Raises:
        HTTPException: If error occurs while retrieving plugin status.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        tool_id_list = [tid.strip() for tid in tool_ids.split(",") if tid.strip()]

        if not tool_id_list:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "No tool IDs provided"},
            )

        # First-Party
        from mcpgateway.plugins.framework import get_plugin_manager
        from mcpgateway.plugins.framework.hooks.registry import get_hook_registry

        route_service = get_plugin_route_service()
        hook_registry = get_hook_registry()

        # Reload config to ensure we have fresh data from disk
        plugin_manager = get_plugin_manager()
        if plugin_manager:
            plugin_manager.reload_config()
            LOGGER.info("Reloaded plugin config for bulk plugin status")

        # First-Party
        from mcpgateway.plugins.framework.hooks.registry import HookPhase

        # Get plugin configurations for each tool (with actual hook configuration)
        tool_plugins = {}  # tool_id -> {plugin_name -> {pre: bool, post: bool, priority: int}}
        tool_names = {}

        for tool_id in tool_id_list:
            try:
                tool = await _get_entity_by_id(db, "tool", tool_id)
                tool_names[tool_id] = tool.name
                first_server = tool.servers[0] if tool.servers else None

                # Get pre-hook plugins for this tool
                pre_hook_types = hook_registry.get_hooks_for_entity_type("tool", HookPhase.PRE)
                post_hook_types = hook_registry.get_hooks_for_entity_type("tool", HookPhase.POST)

                pre_plugins = []
                post_plugins = []

                if pre_hook_types:
                    pre_plugins = await _get_plugins_for_entity_and_hook(
                        route_service,
                        entity_type="tool",
                        entity_name=tool.name,
                        entity_id=str(tool.id),
                        tags=tool.tags or [],
                        server_name=first_server.name if first_server else None,
                        server_id=str(first_server.id) if first_server else None,
                        hook_type=pre_hook_types[0],
                    )

                if post_hook_types:
                    post_plugins = await _get_plugins_for_entity_and_hook(
                        route_service,
                        entity_type="tool",
                        entity_name=tool.name,
                        entity_id=str(tool.id),
                        tags=tool.tags or [],
                        server_name=first_server.name if first_server else None,
                        server_id=str(first_server.id) if first_server else None,
                        hook_type=post_hook_types[0],
                    )

                # Build plugin info with actual hook configuration
                plugin_info = {}
                for p in pre_plugins:
                    name = p.get("name", p.get("plugin_name", ""))
                    if name not in plugin_info:
                        plugin_info[name] = {"pre": False, "post": False, "priority": p.get("priority", 0)}
                    plugin_info[name]["pre"] = True
                    plugin_info[name]["priority"] = max(plugin_info[name]["priority"], p.get("priority", 0))

                for p in post_plugins:
                    name = p.get("name", p.get("plugin_name", ""))
                    if name not in plugin_info:
                        plugin_info[name] = {"pre": False, "post": False, "priority": p.get("priority", 0)}
                    plugin_info[name]["post"] = True
                    plugin_info[name]["priority"] = max(plugin_info[name]["priority"], p.get("priority", 0))

                tool_plugins[tool_id] = plugin_info

            except Exception as e:
                LOGGER.warning(f"Could not get plugins for tool {tool_id}: {e}")
                tool_plugins[tool_id] = {}
                tool_names[tool_id] = f"Tool {tool_id}"

        # Analyze plugin distribution across tools
        all_plugins = set()
        for plugins in tool_plugins.values():
            all_plugins.update(plugins.keys())

        LOGGER.info(f"Tool plugins mapping: {tool_plugins}")
        LOGGER.info(f"All unique plugins found: {all_plugins}")

        plugin_status = {}
        for plugin in all_plugins:
            # Count tools that have this plugin
            tool_count = sum(1 for plugins in tool_plugins.values() if plugin in plugins)
            total_tools = len(tool_id_list)

            if tool_count == total_tools:
                status = "all"
            elif tool_count > 0:
                status = "some"
            else:
                status = "none"

            # Aggregate hook configuration across tools
            has_pre = any(plugins.get(plugin, {}).get("pre", False) for plugins in tool_plugins.values())
            has_post = any(plugins.get(plugin, {}).get("post", False) for plugins in tool_plugins.values())

            # Get max priority across tools
            max_priority = max((plugins.get(plugin, {}).get("priority", 0) for plugins in tool_plugins.values()), default=0)

            plugin_status[plugin] = {
                "status": status,
                "count": tool_count,
                "total": total_tools,
                "pre_hooks": ["tool_pre_invoke"] if has_pre else [],
                "post_hooks": ["tool_post_invoke"] if has_post else [],
                "priority": max_priority,
            }

        return JSONResponse(
            content={
                "success": True,
                "tool_count": len(tool_id_list),
                "tool_names": tool_names,
                "tool_plugins": {tid: list(plugins.keys()) for tid, plugins in tool_plugins.items()},
                "plugin_status": plugin_status,
            }
        )
    except Exception as e:
        LOGGER.error(f"Error getting bulk plugin status: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": str(e)},
        )


@plugin_admin_router.get("/prompts/bulk/plugins/status", response_class=JSONResponse)
async def get_bulk_plugin_status_prompts(
    request: Request,
    prompt_ids: str = Query(..., description="Comma-separated list of prompt IDs"),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Get plugin configuration status for multiple prompts.

    Args:
        request: FastAPI request object
        prompt_ids: Comma-separated prompt IDs
        db: Database session
        _user: Current authenticated user

    Returns:
        JSON response with plugin status breakdown for prompts.

    Raises:
        HTTPException: If error occurs while retrieving plugin status.
    """
    try:
        # First-Party
        from mcpgateway.plugins.framework import get_plugin_manager
        from mcpgateway.plugins.framework.hooks.registry import get_hook_registry, HookPhase
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        prompt_id_list = [pid.strip() for pid in prompt_ids.split(",") if pid.strip()]

        if not prompt_id_list:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "No prompt IDs provided"},
            )

        route_service = get_plugin_route_service()
        hook_registry = get_hook_registry()

        plugin_manager = get_plugin_manager()
        if plugin_manager:
            plugin_manager.reload_config()

        prompt_plugins = {}
        prompt_names = {}

        for prompt_id in prompt_id_list:
            try:
                prompt = await _get_entity_by_id(db, "prompt", prompt_id)
                prompt_names[prompt_id] = prompt.name

                pre_hook_types = hook_registry.get_hooks_for_entity_type("prompt", HookPhase.PRE)
                post_hook_types = hook_registry.get_hooks_for_entity_type("prompt", HookPhase.POST)

                pre_plugins = []
                post_plugins = []

                if pre_hook_types:
                    pre_plugins = await _get_plugins_for_entity_and_hook(
                        route_service,
                        entity_type="prompt",
                        entity_name=prompt.name,
                        entity_id=str(prompt.id),
                        tags=prompt.tags or [],
                        server_name=None,
                        server_id=None,
                        hook_type=pre_hook_types[0],
                    )

                if post_hook_types:
                    post_plugins = await _get_plugins_for_entity_and_hook(
                        route_service,
                        entity_type="prompt",
                        entity_name=prompt.name,
                        entity_id=str(prompt.id),
                        tags=prompt.tags or [],
                        server_name=None,
                        server_id=None,
                        hook_type=post_hook_types[0],
                    )

                plugin_info = {}
                for p in pre_plugins:
                    name = p.get("name", p.get("plugin_name", ""))
                    if name not in plugin_info:
                        plugin_info[name] = {"pre": False, "post": False, "priority": p.get("priority", 0)}
                    plugin_info[name]["pre"] = True
                    plugin_info[name]["priority"] = max(plugin_info[name]["priority"], p.get("priority", 0))

                for p in post_plugins:
                    name = p.get("name", p.get("plugin_name", ""))
                    if name not in plugin_info:
                        plugin_info[name] = {"pre": False, "post": False, "priority": p.get("priority", 0)}
                    plugin_info[name]["post"] = True
                    plugin_info[name]["priority"] = max(plugin_info[name]["priority"], p.get("priority", 0))

                prompt_plugins[prompt_id] = plugin_info

            except Exception as e:
                LOGGER.warning(f"Could not get plugins for prompt {prompt_id}: {e}")
                prompt_plugins[prompt_id] = {}
                prompt_names[prompt_id] = f"Prompt {prompt_id}"

        all_plugins = set()
        for plugins in prompt_plugins.values():
            all_plugins.update(plugins.keys())

        plugin_status = {}
        for plugin in all_plugins:
            prompt_count = sum(1 for plugins in prompt_plugins.values() if plugin in plugins)
            total_prompts = len(prompt_id_list)

            if prompt_count == total_prompts:
                status = "all"
            elif prompt_count > 0:
                status = "some"
            else:
                status = "none"

            has_pre = any(plugins.get(plugin, {}).get("pre", False) for plugins in prompt_plugins.values())
            has_post = any(plugins.get(plugin, {}).get("post", False) for plugins in prompt_plugins.values())
            max_priority = max((plugins.get(plugin, {}).get("priority", 0) for plugins in prompt_plugins.values()), default=0)

            plugin_status[plugin] = {
                "status": status,
                "count": prompt_count,
                "total": total_prompts,
                "pre_hooks": ["prompt_pre_invoke"] if has_pre else [],
                "post_hooks": ["prompt_post_invoke"] if has_post else [],
                "priority": max_priority,
            }

        return JSONResponse(
            content={
                "success": True,
                "prompt_count": len(prompt_id_list),
                "prompt_names": prompt_names,
                "prompt_plugins": {pid: list(plugins.keys()) for pid, plugins in prompt_plugins.items()},
                "plugin_status": plugin_status,
            }
        )
    except Exception as e:
        LOGGER.error(f"Error getting bulk plugin status for prompts: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": str(e)},
        )


@plugin_admin_router.get("/resources/bulk/plugins/status", response_class=JSONResponse)
async def get_bulk_plugin_status_resources(
    request: Request,
    resource_ids: str = Query(..., description="Comma-separated list of resource IDs"),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Get plugin configuration status for multiple resources.

    Args:
        request: FastAPI request object
        resource_ids: Comma-separated resource IDs
        db: Database session
        _user: Current authenticated user

    Returns:
        JSON response with plugin status breakdown for resources.

    Raises:
        HTTPException: If error occurs while retrieving plugin status.
    """
    try:
        # First-Party
        from mcpgateway.plugins.framework import get_plugin_manager
        from mcpgateway.plugins.framework.hooks.registry import get_hook_registry, HookPhase
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        resource_id_list = [rid.strip() for rid in resource_ids.split(",") if rid.strip()]

        if not resource_id_list:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "No resource IDs provided"},
            )

        route_service = get_plugin_route_service()
        hook_registry = get_hook_registry()

        plugin_manager = get_plugin_manager()
        if plugin_manager:
            plugin_manager.reload_config()

        resource_plugins = {}
        resource_names = {}

        for resource_id in resource_id_list:
            try:
                resource = await _get_entity_by_id(db, "resource", resource_id)
                resource_names[resource_id] = resource.name

                pre_hook_types = hook_registry.get_hooks_for_entity_type("resource", HookPhase.PRE)
                post_hook_types = hook_registry.get_hooks_for_entity_type("resource", HookPhase.POST)

                pre_plugins = []
                post_plugins = []

                if pre_hook_types:
                    pre_plugins = await _get_plugins_for_entity_and_hook(
                        route_service,
                        entity_type="resource",
                        entity_name=resource.name,
                        entity_id=str(resource.id),
                        tags=resource.tags or [],
                        server_name=None,
                        server_id=None,
                        hook_type=pre_hook_types[0],
                    )

                if post_hook_types:
                    post_plugins = await _get_plugins_for_entity_and_hook(
                        route_service,
                        entity_type="resource",
                        entity_name=resource.name,
                        entity_id=str(resource.id),
                        tags=resource.tags or [],
                        server_name=None,
                        server_id=None,
                        hook_type=post_hook_types[0],
                    )

                plugin_info = {}
                for p in pre_plugins:
                    name = p.get("name", p.get("plugin_name", ""))
                    if name not in plugin_info:
                        plugin_info[name] = {"pre": False, "post": False, "priority": p.get("priority", 0)}
                    plugin_info[name]["pre"] = True
                    plugin_info[name]["priority"] = max(plugin_info[name]["priority"], p.get("priority", 0))

                for p in post_plugins:
                    name = p.get("name", p.get("plugin_name", ""))
                    if name not in plugin_info:
                        plugin_info[name] = {"pre": False, "post": False, "priority": p.get("priority", 0)}
                    plugin_info[name]["post"] = True
                    plugin_info[name]["priority"] = max(plugin_info[name]["priority"], p.get("priority", 0))

                resource_plugins[resource_id] = plugin_info

            except Exception as e:
                LOGGER.warning(f"Could not get plugins for resource {resource_id}: {e}")
                resource_plugins[resource_id] = {}
                resource_names[resource_id] = f"Resource {resource_id}"

        all_plugins = set()
        for plugins in resource_plugins.values():
            all_plugins.update(plugins.keys())

        plugin_status = {}
        for plugin in all_plugins:
            resource_count = sum(1 for plugins in resource_plugins.values() if plugin in plugins)
            total_resources = len(resource_id_list)

            if resource_count == total_resources:
                status = "all"
            elif resource_count > 0:
                status = "some"
            else:
                status = "none"

            has_pre = any(plugins.get(plugin, {}).get("pre", False) for plugins in resource_plugins.values())
            has_post = any(plugins.get(plugin, {}).get("post", False) for plugins in resource_plugins.values())
            max_priority = max((plugins.get(plugin, {}).get("priority", 0) for plugins in resource_plugins.values()), default=0)

            plugin_status[plugin] = {
                "status": status,
                "count": resource_count,
                "total": total_resources,
                "pre_hooks": ["resource_pre_invoke"] if has_pre else [],
                "post_hooks": ["resource_post_invoke"] if has_post else [],
                "priority": max_priority,
            }

        return JSONResponse(
            content={
                "success": True,
                "resource_count": len(resource_id_list),
                "resource_names": resource_names,
                "resource_plugins": {rid: list(plugins.keys()) for rid, plugins in resource_plugins.items()},
                "plugin_status": plugin_status,
            }
        )
    except Exception as e:
        LOGGER.error(f"Error getting bulk plugin status for resources: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": str(e)},
        )


@plugin_admin_router.post("/tools/bulk/plugins", response_class=JSONResponse)
async def add_bulk_plugins(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Add a plugin to multiple tools at once (bulk operation).

    Args:
        request: FastAPI request object
        db: Database session
        _user: Current authenticated user

    Returns:
        JSON response with success/failure counts

    Raises:
        HTTPException: If error occurs during bulk plugin addition.
    """
    try:
        # Parse form data manually
        form_data = await request.form()

        # Extract and validate form fields
        tool_ids = form_data.getlist("tool_ids")
        # Accept both plugin_name (singular) and plugin_names (plural) for flexibility
        plugin_name = form_data.get("plugin_name") or form_data.get("plugin_names")
        priority_str = form_data.get("priority", "10")
        priority = int(priority_str) if priority_str and priority_str.strip() else 10
        hooks = form_data.getlist("hooks") if "hooks" in form_data else None
        reverse_order_on_post = form_data.get("reverse_order_on_post") == "true"

        # Parse new advanced fields
        config_str = form_data.get("config", "").strip()
        config = None
        if config_str:
            try:
                config = json.loads(config_str)
            except json.JSONDecodeError as e:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": f"Invalid JSON in config: {e}"},
                )

        override = form_data.get("override") == "true"
        scope = form_data.get("scope", "local")
        mode = form_data.get("mode") or None  # Convert empty string to None

        LOGGER.info("=== BULK ADD PLUGIN REQUEST ===")
        LOGGER.info(f"Tool IDs: {tool_ids}")
        LOGGER.info(f"Plugin Name: {plugin_name}")
        LOGGER.info(f"Priority: {priority}")
        LOGGER.info(f"Hooks: {hooks}")
        LOGGER.info(f"Reverse order on post: {reverse_order_on_post}")
        LOGGER.info(f"Config: {config}")
        LOGGER.info(f"Override: {override}")
        LOGGER.info(f"Scope: {scope}")
        LOGGER.info(f"Mode: {mode}")

        if not tool_ids:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "No tool IDs provided"},
            )

        if not plugin_name:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "No plugin name provided"},
            )

        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        route_service = get_plugin_route_service()
        success_count = 0
        failed_count = 0
        errors = []

        for tool_id in tool_ids:
            try:
                # Get tool from database
                tool = await _get_entity_by_id(db, "tool", tool_id)

                # Add plugin route (now saves internally with file locking)
                await route_service.add_simple_route(
                    entity_type="tool",
                    entity_name=tool.name,
                    plugin_name=plugin_name,
                    priority=priority,
                    hooks=hooks if hooks else None,
                    reverse_order_on_post=reverse_order_on_post,
                    config=config,
                    override=override,
                    mode=mode,
                )
                success_count += 1

            except Exception as e:
                LOGGER.error(f"Failed to add plugin {plugin_name} to tool {tool_id}: {e}")
                failed_count += 1
                errors.append({"tool_id": tool_id, "error": str(e)})

        # Note: No need to save config here - add_simple_route saves internally with file locking

        return JSONResponse(
            content={
                "success": True,
                "message": f"Added plugin to {success_count} tools" + (f", {failed_count} failed" if failed_count > 0 else ""),
                "success_count": success_count,
                "failed_count": failed_count,
                "errors": errors if errors else None,
            }
        )

    except Exception as e:
        LOGGER.error(f"Error in bulk add plugins: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": str(e)},
        )


@plugin_admin_router.delete("/tools/bulk/plugins", response_class=JSONResponse)
async def remove_bulk_plugins(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Remove a plugin from multiple tools at once (bulk operation).

    Args:
        request: FastAPI request object
        db: Database session
        _user: Current authenticated user

    Returns:
        JSON response with success/failure counts

    Raises:
        HTTPException: If error occurs during bulk plugin removal.
    """
    # Parse form data manually to debug
    form_data = await request.form()
    LOGGER.info(f"Bulk remove plugins - raw form data keys: {list(form_data.keys())}")
    LOGGER.info(f"Bulk remove plugins - raw form data: {dict(form_data)}")
    LOGGER.info(f"Bulk remove plugins - multi(): {list(form_data.multi_items())}")

    # Extract and validate form fields
    tool_ids = form_data.getlist("tool_ids")
    # Accept both singular and plural forms, and support multiple plugins
    plugin_names_list = form_data.getlist("plugin_names")
    plugin_name_list = form_data.getlist("plugin_name")
    LOGGER.info(f"getlist('plugin_names'): {plugin_names_list}")
    LOGGER.info(f"getlist('plugin_name'): {plugin_name_list}")

    plugin_names = plugin_names_list if plugin_names_list else plugin_name_list
    # Also check for single value if getlist returns empty
    if not plugin_names:
        single_name = form_data.get("plugin_names") or form_data.get("plugin_name")
        LOGGER.info(f"Fallback single_name: {single_name}")
        if single_name:
            plugin_names = [single_name]

    # Check for clear_all flag
    clear_all = form_data.get("clear_all") == "true"

    LOGGER.info(f"Bulk remove plugins - tool_ids: {tool_ids}, plugin_names: {plugin_names}, clear_all: {clear_all}")

    if not tool_ids:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "No tool IDs provided"},
        )

    if not plugin_names and not clear_all:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "No plugin name provided"},
        )

    # First-Party
    from mcpgateway.plugins.framework.hooks.registry import get_hook_registry, HookPhase
    from mcpgateway.services.plugin_route_service import get_plugin_route_service

    route_service = get_plugin_route_service()
    hook_registry = get_hook_registry()
    success_count = 0
    failed_count = 0
    errors = []

    # If clear_all, get all plugins for each tool and remove them
    if clear_all:
        for tool_id in tool_ids:
            try:
                tool = await _get_entity_by_id(db, "tool", tool_id)
                first_server = tool.servers[0] if tool.servers else None

                # Get all configured plugins for this tool
                pre_hook_types = hook_registry.get_hooks_for_entity_type("tool", HookPhase.PRE)
                post_hook_types = hook_registry.get_hooks_for_entity_type("tool", HookPhase.POST)

                all_plugin_names = set()

                if pre_hook_types:
                    pre_plugins = await _get_plugins_for_entity_and_hook(
                        route_service,
                        entity_type="tool",
                        entity_name=tool.name,
                        entity_id=str(tool.id),
                        tags=tool.tags or [],
                        server_name=first_server.name if first_server else None,
                        server_id=str(first_server.id) if first_server else None,
                        hook_type=pre_hook_types[0],
                    )
                    all_plugin_names.update(p.get("name", "") for p in pre_plugins)

                if post_hook_types:
                    post_plugins = await _get_plugins_for_entity_and_hook(
                        route_service,
                        entity_type="tool",
                        entity_name=tool.name,
                        entity_id=str(tool.id),
                        tags=tool.tags or [],
                        server_name=first_server.name if first_server else None,
                        server_id=str(first_server.id) if first_server else None,
                        hook_type=post_hook_types[0],
                    )
                    all_plugin_names.update(p.get("name", "") for p in post_plugins)

                # Remove all plugins
                for pname in all_plugin_names:
                    if pname:
                        removed = await route_service.remove_plugin_from_entity(
                            entity_type="tool",
                            entity_name=tool.name,
                            plugin_name=pname,
                        )
                        if removed:
                            success_count += 1
                        else:
                            failed_count += 1

            except Exception as e:
                LOGGER.warning(f"Error clearing plugins for tool {tool_id}: {e}")
                failed_count += 1
                errors.append({"tool_id": tool_id, "error": str(e)})

        # Note: No need to save - remove_plugin_from_entity saves internally with file locking

        return JSONResponse(
            content={
                "success": True,
                "message": f"Cleared plugins from {len(tool_ids)} tools",
                "removed": success_count,
                "failed": failed_count,
                "errors": errors if errors else None,
            }
        )

    # Loop over all tools and all plugins (non-clear_all case)
    for tool_id in tool_ids:
        for plugin_name in plugin_names:
            try:
                # Get tool from database
                tool = await _get_entity_by_id(db, "tool", tool_id)

                # Remove plugin from entity
                removed = await route_service.remove_plugin_from_entity(
                    entity_type="tool",
                    entity_name=tool.name,
                    plugin_name=plugin_name,
                )

                if removed:
                    success_count += 1
                else:
                    failed_count += 1
                    errors.append({"tool_id": tool_id, "plugin": plugin_name, "error": "Plugin not found on this tool"})

            except Exception as e:
                LOGGER.error(f"Failed to remove plugin {plugin_name} from tool {tool_id}: {e}")
                failed_count += 1
                errors.append({"tool_id": tool_id, "plugin": plugin_name, "error": str(e)})

    # Note: No need to save config here - remove_plugin_from_entity saves internally with file locking

    return JSONResponse(
        content={
            "success": True,
            "message": f"Removed {success_count} plugin attachment(s)" + (f", {failed_count} failed" if failed_count > 0 else ""),
            "success_count": success_count,
            "failed_count": failed_count,
            "errors": errors if errors else None,
        }
    )


@plugin_admin_router.post("/tools/bulk/plugins/priority", response_class=JSONResponse)
async def update_bulk_plugin_priority(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Update plugin priority for multiple tools at once (bulk operation).

    Args:
        request: FastAPI request object
        db: Database session
        _user: Current authenticated user

    Returns:
        JSON response with success/failure counts

    Raises:
        HTTPException: If error occurs during bulk priority update.
    """
    try:
        # Parse form data
        form_data = await request.form()
        tool_ids = form_data.getlist("tool_ids")
        plugin_name = form_data.get("plugin_name")
        new_priority = int(form_data.get("priority", 10))

        LOGGER.info(f"Bulk update priority - tool_ids: {tool_ids}, plugin: {plugin_name}, priority: {new_priority}")

        if not tool_ids:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "No tool IDs provided"},
            )

        if not plugin_name:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "No plugin name provided"},
            )

        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        route_service = get_plugin_route_service()
        success_count = 0
        failed_count = 0
        errors = []

        for tool_id in tool_ids:
            try:
                # Get tool from database
                tool = await _get_entity_by_id(db, "tool", tool_id)

                # Update plugin priority for this tool
                updated = await route_service.update_plugin_priority(
                    entity_type="tool",
                    entity_name=tool.name,
                    plugin_name=plugin_name,
                    new_priority=new_priority,
                )

                if updated:
                    success_count += 1
                else:
                    failed_count += 1
                    errors.append({"tool_id": tool_id, "error": f"Plugin {plugin_name} not found for tool {tool.name}"})

            except Exception as e:
                LOGGER.error(f"Failed to update priority for plugin {plugin_name} on tool {tool_id}: {e}")
                failed_count += 1
                errors.append({"tool_id": tool_id, "error": str(e)})

        # Save configuration after all updates
        if success_count > 0:
            try:
                await route_service.save_config()
            except Exception as e:
                LOGGER.error(f"Failed to save plugin configuration: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "message": "Failed to save plugin configuration", "error": str(e)},
                )

        return JSONResponse(
            content={
                "success": True,
                "message": f"Updated priority for {success_count} tools" + (f", {failed_count} failed" if failed_count > 0 else ""),
                "success_count": success_count,
                "failed_count": failed_count,
                "errors": errors if errors else None,
            }
        )

    except Exception as e:
        LOGGER.error(f"Error in bulk update plugin priority: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": str(e)},
        )


@plugin_admin_router.post("/tools/{tool_id}/plugins", response_class=HTMLResponse)
async def add_tool_plugin(
    request: Request,
    tool_id: str,
    db: Session = Depends(get_db),
):
    """Quick-add a plugin to a tool.

    Creates a simple name-based routing rule.
    Accepts form data from HTMX forms.

    Args:
        request: The HTTP request object.
        tool_id: The id of the tool to add the plugin to.
        db: The database session.

    Returns:
        Updated plugins UI HTML response.

    Raises:
        HTTPException: If plugin name is missing, config is invalid, or error occurs.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Parse form data
        form_data = await request.form()
        plugin_name = form_data.get("plugin_name")
        priority = int(form_data.get("priority", 10))
        hooks = form_data.getlist("hooks") if "hooks" in form_data else None
        reverse_order_on_post = form_data.get("reverse_order_on_post") == "true"

        # Parse advanced fields
        config_str = form_data.get("config", "").strip()
        config = None
        if config_str:
            try:
                config = json.loads(config_str)
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON in config: {e}")

        override = form_data.get("override") == "true"
        mode = form_data.get("mode") or None  # Convert empty string to None

        if not plugin_name:
            raise HTTPException(status_code=400, detail="Plugin name is required")

        # Get tool from database
        tool = await _get_entity_by_id(db, "tool", tool_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Add simple route
        await route_service.add_simple_route(
            entity_type="tool",
            entity_name=tool.name,
            plugin_name=plugin_name,
            priority=priority,
            hooks=hooks if hooks else None,
            reverse_order_on_post=reverse_order_on_post,
            config=config,
            override=override,
            mode=mode,
        )

        # Save configuration
        await route_service.save_config()

        LOGGER.info(f"Added plugin {plugin_name} to tool {tool.name}")

        # Return updated plugins UI
        return await get_tool_plugins_ui(request, tool_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error adding tool plugin: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plugin_admin_router.delete("/tools/{tool_id}/plugins/{plugin_name}", response_class=HTMLResponse)
async def remove_tool_plugin(
    request: Request,
    tool_id: str,
    plugin_name: str,
    hook: Optional[str] = Query(None, description="Specific hook to remove (e.g., tool_pre_invoke or tool_post_invoke)"),
    db: Session = Depends(get_db),
):
    """Remove a plugin from a tool.

    Removes the plugin from simple name-based routing rules only.
    If hook is specified, only removes from that specific hook type.

    Args:
        request: The HTTP request object.
        tool_id: The id of the tool to remove the plugin from.
        plugin_name: The name of the plugin to remove.
        hook: Specific hook to remove (e.g., tool_pre_invoke or tool_post_invoke).
        db: The database session.

    Returns:
        Updated plugins UI HTML response.

    Raises:
        HTTPException: If error occurs during plugin removal.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Get tool from database
        tool = await _get_entity_by_id(db, "tool", tool_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Remove plugin from entity (optionally for specific hook only)
        removed = await route_service.remove_plugin_from_entity(
            entity_type="tool",
            entity_name=tool.name,
            plugin_name=plugin_name,
            hook=hook,
        )

        if not removed:
            hook_msg = f" for hook {hook}" if hook else ""
            raise HTTPException(
                status_code=404,
                detail=f"Plugin {plugin_name} not found in simple rules for tool {tool.name}{hook_msg}",
            )

        # Save configuration
        await route_service.save_config()

        hook_msg = f" from {hook}" if hook else ""
        LOGGER.info(f"Removed plugin {plugin_name}{hook_msg} from tool {tool.name}")

        # Return updated plugins UI
        return await get_tool_plugins_ui(request, tool_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error removing tool plugin: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plugin_admin_router.post("/tools/{tool_id}/plugins/reverse-post-hooks", response_class=HTMLResponse)
async def toggle_reverse_post_hooks(
    request: Request,
    tool_id: str,
    db: Session = Depends(get_db),
):
    """Toggle reverse_order_on_post for all plugin rules of a tool.

    When enabled, post-hooks execute in reverse order (LIFO - last added runs first).

    Args:
        request: The HTTP request object.
        tool_id: The id of the tool to toggle reverse post hooks for.
        db: The database session.

    Returns:
        Updated plugins UI HTML response.

    Raises:
        HTTPException: If error occurs during toggle operation.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Get tool from database
        tool = await _get_entity_by_id(db, "tool", tool_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Toggle reverse_order_on_post for all rules of this tool (save is handled internally by the service)
        new_state = await route_service.toggle_reverse_post_hooks(
            entity_type="tool",
            entity_name=tool.name,
        )

        LOGGER.info(f"Toggled reverse_order_on_post to {new_state} for tool {tool.name}")

        # Return updated plugins UI
        return await get_tool_plugins_ui(request, tool_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error toggling reverse post hooks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plugin_admin_router.post("/tools/{tool_id}/plugins/{plugin_name}/priority", response_class=HTMLResponse)
async def change_tool_plugin_priority(
    request: Request,
    tool_id: str,
    plugin_name: str,
    hook: str = Query(..., description="Hook type (tool_pre_invoke or tool_post_invoke)"),
    direction: str = Query(..., description="Direction to move: 'up' or 'down'"),
    db: Session = Depends(get_db),
):
    """Change a plugin's priority (move up or down in execution order).

    Moving 'up' decreases priority (runs earlier), 'down' increases priority (runs later).

    Args:
        request: The HTTP request object.
        tool_id: The id of the tool whose plugin priority to change.
        plugin_name: The name of the plugin to change priority for.
        hook: Hook type (tool_pre_invoke or tool_post_invoke).
        direction: Direction to move: 'up' or 'down'.
        db: The database session.

    Returns:
        Updated plugins UI HTML response.

    Raises:
        HTTPException: If error occurs during priority change.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Get tool from database
        tool = await _get_entity_by_id(db, "tool", tool_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Change priority (save is handled internally by the service)
        success = await route_service.change_plugin_priority(
            entity_type="tool",
            entity_name=tool.name,
            plugin_name=plugin_name,
            hook=hook,
            direction=direction,
        )

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Plugin {plugin_name} not found or cannot be moved {direction}",
            )

        LOGGER.info(f"Changed priority of plugin {plugin_name} ({direction}) for tool {tool.name}")

        # Return updated plugins UI
        return await get_tool_plugins_ui(request, tool_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error changing tool plugin priority: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plugin_admin_router.post("/tools/{tool_id}/plugins/{plugin_name}/set-priority", response_class=HTMLResponse)
async def set_tool_plugin_priority(
    request: Request,
    tool_id: str,
    plugin_name: str,
    hook: str = Query(..., description="Hook type (tool_pre_invoke or tool_post_invoke)"),
    db: Session = Depends(get_db),
):
    """Set a plugin's priority to an absolute value.

    Accepts form data with 'priority' field.

    Args:
        request: The HTTP request object.
        tool_id: The id of the tool whose plugin priority to set.
        plugin_name: The name of the plugin to set priority for.
        hook: Hook type (tool_pre_invoke or tool_post_invoke).
        db: The database session.

    Returns:
        Updated plugins UI HTML response.

    Raises:
        HTTPException: If plugin not found or error occurs.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Parse form data
        form_data = await request.form()
        new_priority = int(form_data.get("priority", 10))

        # Get tool from database
        tool = await _get_entity_by_id(db, "tool", tool_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Update priority (save is handled internally by the service)
        success = await route_service.update_plugin_priority(
            entity_type="tool",
            entity_name=tool.name,
            plugin_name=plugin_name,
            new_priority=new_priority,
        )

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Plugin {plugin_name} not found for tool {tool.name}",
            )

        LOGGER.info(f"Set priority of plugin {plugin_name} to {new_priority} for tool {tool.name}")

        # Return updated plugins UI
        return await get_tool_plugins_ui(request, tool_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error setting tool plugin priority: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plugin_admin_router.get("/tools/{tool_id}/plugins-ui", response_class=HTMLResponse)
async def get_tool_plugins_ui(
    request: Request,
    tool_id: str,
    db: Session = Depends(get_db),
):
    """Get the plugin management UI for a tool (returns HTML fragment for HTMX).

    This endpoint returns an expandable row showing:
    - Current pre-invoke and post-invoke plugins with execution order
    - Form to add new plugins
    - Buttons to remove plugins

    Args:
        request: The HTTP request object.
        tool_id: The id of the tool to get plugin UI for.
        db: The database session.

    Returns:
        HTML fragment for plugin management UI.

    Raises:
        HTTPException: If error occurs while rendering UI.
    """
    try:
        context = await _get_entity_plugins_ui_context(request, "tool", tool_id, db)
        return request.app.state.templates.TemplateResponse("entity_plugins_partial.html", context)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error loading tool plugins UI: {e}")
        raise HTTPException(status_code=500, detail=str(e))


##################################################
# Resource Plugin Routes
##################################################


@plugin_admin_router.get("/resources/{resource_id}/plugins-ui", response_class=HTMLResponse)
async def get_resource_plugins_ui(
    request: Request,
    resource_id: str,
    db: Session = Depends(get_db),
):
    """Get the plugin management UI for a resource (returns HTML fragment for HTMX).

    Args:
        request: The HTTP request object.
        resource_id: The id of the resource to get plugin UI for.
        db: The database session.

    Returns:
        HTML fragment for plugin management UI.

    Raises:
        HTTPException: If error occurs while rendering UI.
    """
    try:
        context = await _get_entity_plugins_ui_context(request, "resource", resource_id, db)
        return request.app.state.templates.TemplateResponse("entity_plugins_partial.html", context)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error loading resource plugins UI: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Bulk operations - must come before parameterized routes to avoid path conflicts
@plugin_admin_router.post("/resources/bulk/plugins", response_class=JSONResponse)
async def add_bulk_plugins_to_resources(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Add a plugin to multiple resources at once (bulk operation).

    Args:
        request: The HTTP request for bulk adding plugins to resources.
        db: The MCP gateway database session for grabbing metadata.
        _user: user authentication object.

    Returns:
        A JSON Response indicating the success or failure of the operation.
    """
    # First-Party
    from mcpgateway.admin_helpers import (
        bulk_add_plugin_to_entities,
    )
    from mcpgateway.services.plugin_route_service import get_plugin_route_service

    try:
        form_data = await request.form()
        parsed = parse_bulk_plugin_form_data(form_data, "resource_ids")

        # Parse config JSON
        config, error_response = parse_plugin_config(parsed["config_str"])
        if error_response:
            return error_response

        # Validate inputs
        validation_error = validate_bulk_plugin_inputs(parsed["entity_ids"], parsed["plugin_name"], "resource")
        if validation_error:
            return validation_error

        LOGGER.info("=== BULK ADD PLUGIN TO RESOURCES REQUEST ===")
        LOGGER.info(f"Resource IDs: {parsed['entity_ids']}")
        LOGGER.info(f"Plugin Name: {parsed['plugin_name']}")
        LOGGER.info(f"Priority: {parsed['priority']}")
        LOGGER.info(f"Hooks: {parsed['hooks']}")

        route_service = get_plugin_route_service()

        # Bulk add using helper
        success_count, failed_count, errors = await bulk_add_plugin_to_entities(
            entity_ids=parsed["entity_ids"],
            entity_type="resource",
            get_entity_by_id_func=_get_entity_by_id,
            route_service=route_service,
            db=db,
            plugin_params={
                "plugin_name": parsed["plugin_name"],
                "priority": parsed["priority"],
                "hooks": parsed["hooks"],
                "reverse_order_on_post": parsed["reverse_order_on_post"],
                "config": config,
                "override": parsed["override"],
                "mode": parsed["mode"],
            },
        )

        return build_bulk_operation_response(success_count, failed_count, errors, "resources", "Added plugin to")

    except Exception as e:
        LOGGER.error(f"Error in bulk add plugins to resources: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": str(e)},
        )


@plugin_admin_router.delete("/resources/bulk/plugins", response_class=JSONResponse)
async def remove_bulk_plugins_from_resources(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Remove a plugin from multiple resources at once (bulk operation).

    Args:
        request: The HTTP request for bulk removing plugins from resources.
        db: The MCP gateway database session for grabbing metadata.
        _user: user authentication object.

    Returns:
        An JSON Response showing the success or failure of the operation.
    """
    # First-Party
    from mcpgateway.admin_helpers import (
        bulk_remove_plugin_from_entities,
    )

    form_data = await request.form()
    parsed = parse_remove_plugin_form_data(form_data, "resource_ids")

    LOGGER.info(f"Bulk remove plugins from resources - resource_ids: {parsed['entity_ids']}, plugin_names: {parsed['plugin_names']}, clear_all: {parsed['clear_all']}")

    # Validate inputs
    validation_error = validate_remove_plugin_inputs(parsed["entity_ids"], parsed["plugin_names"], parsed["clear_all"], "resource")
    if validation_error:
        return validation_error

    # First-Party
    from mcpgateway.plugins.framework.hooks.registry import get_hook_registry, HookPhase
    from mcpgateway.services.plugin_route_service import get_plugin_route_service

    route_service = get_plugin_route_service()

    # Handle clear_all case (must stay custom due to hook registry logic)
    if parsed["clear_all"]:
        hook_registry = get_hook_registry()
        success_count = 0
        failed_count = 0
        errors = []

        for resource_id in parsed["entity_ids"]:
            try:
                resource = await _get_entity_by_id(db, "resource", resource_id)

                pre_hook_types = hook_registry.get_hooks_for_entity_type("resource", HookPhase.PRE)
                post_hook_types = hook_registry.get_hooks_for_entity_type("resource", HookPhase.POST)

                all_plugin_names = set()

                if pre_hook_types:
                    pre_plugins = await _get_plugins_for_entity_and_hook(
                        route_service,
                        entity_type="resource",
                        entity_name=resource.name,
                        entity_id=str(resource.id),
                        tags=resource.tags or [],
                        server_name=None,
                        server_id=None,
                        hook_type=pre_hook_types[0],
                    )
                    all_plugin_names.update(p.get("name", "") for p in pre_plugins)

                if post_hook_types:
                    post_plugins = await _get_plugins_for_entity_and_hook(
                        route_service,
                        entity_type="resource",
                        entity_name=resource.name,
                        entity_id=str(resource.id),
                        tags=resource.tags or [],
                        server_name=None,
                        server_id=None,
                        hook_type=post_hook_types[0],
                    )
                    all_plugin_names.update(p.get("name", "") for p in post_plugins)

                for pname in all_plugin_names:
                    if pname:
                        removed = await route_service.remove_plugin_from_entity(
                            entity_type="resource",
                            entity_name=resource.name,
                            plugin_name=pname,
                        )
                        if removed:
                            success_count += 1
                        else:
                            failed_count += 1

            except Exception as e:
                LOGGER.warning(f"Error clearing plugins for resource {resource_id}: {e}")
                failed_count += 1
                errors.append({"resource_id": resource_id, "error": str(e)})

        return JSONResponse(
            content={
                "success": True,
                "message": f"Cleared plugins from {len(parsed['entity_ids'])} resources",
                "removed": success_count,
                "failed": failed_count,
                "errors": errors if errors else None,
            }
        )

    # Handle normal remove using helper
    success_count, failed_count, errors = await bulk_remove_plugin_from_entities(
        entity_ids=parsed["entity_ids"],
        entity_type="resource",
        plugin_names=parsed["plugin_names"],
        get_entity_by_id_func=_get_entity_by_id,
        route_service=route_service,
        db=db,
    )

    return JSONResponse(
        content={
            "success": True,
            "message": f"Removed {success_count} plugin attachment(s)" + (f", {failed_count} failed" if failed_count > 0 else ""),
            "success_count": success_count,
            "failed_count": failed_count,
            "errors": errors if errors else None,
        }
    )


@plugin_admin_router.post("/resources/bulk/plugins/priority", response_class=JSONResponse)
async def update_bulk_plugin_priority_for_resources(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Update plugin priority for multiple resources at once (bulk operation).

    Args:
         request: The HTTP request for updating plugin priority for resources.
         db: The MCP gateway database session for grabbing metadata.
         _user: user authentication object.

     Raises:
         HTTPException: if there is an error retrieving and filling the UI template.

     Returns:
         An JSON Response showing the success or failure of the operation.
    """
    # First-Party
    from mcpgateway.admin_helpers import (
        bulk_update_plugin_priority_for_entities,
    )
    from mcpgateway.services.plugin_route_service import get_plugin_route_service

    try:
        form_data = await request.form()
        resource_ids = form_data.getlist("resource_ids")
        plugin_name = form_data.get("plugin_name")
        new_priority = int(form_data.get("priority", 10))

        # Validate inputs
        validation_error = validate_bulk_plugin_inputs(resource_ids, plugin_name, "resource")
        if validation_error:
            return validation_error

        route_service = get_plugin_route_service()

        # Bulk update using helper
        success_count, failed_count, errors = await bulk_update_plugin_priority_for_entities(
            entity_ids=resource_ids,
            entity_type="resource",
            plugin_name=plugin_name,
            priority=new_priority,
            get_entity_by_id_func=_get_entity_by_id,
            route_service=route_service,
            db=db,
        )

        return build_bulk_operation_response(success_count, failed_count, errors, "resources", "Updated priority for")
    except Exception as e:
        LOGGER.error(f"Error in bulk update plugin priority for resources: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": str(e)},
        )


# Individual resource plugin operations
@plugin_admin_router.post("/resources/{resource_id}/plugins", response_class=HTMLResponse)
async def add_resource_plugin(
    request: Request,
    resource_id: str,
    db: Session = Depends(get_db),
):
    """Add a plugin to a resource.

    Args:
        request: The HTTP request object.
        resource_id: The resource ID on which to add the plugin.
        db: The MCP gateway database session for grabbing metadata.

    Raises:
        HTTPException: if there is an error retrieving and filling the UI template.

    Returns:
        An HTML UI object to be rendered.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Parse form data
        form_data = await request.form()
        plugin_name = form_data.get("plugin_name")
        priority = int(form_data.get("priority", 10))
        hooks = form_data.getlist("hooks") if "hooks" in form_data else None
        reverse_order_on_post = form_data.get("reverse_order_on_post") == "true"

        # If no hooks specified, auto-detect from registry for this entity type
        if not hooks:
            # First-Party
            from mcpgateway.plugins.framework.hooks.registry import get_hook_registry

            hook_registry = get_hook_registry()
            detected_hooks = hook_registry.get_hooks_for_entity_type("resource")
            if detected_hooks:
                hooks = [str(h.value if hasattr(h, "value") else h) for h in detected_hooks]

        # Parse advanced fields
        config_str = form_data.get("config", "").strip()
        config = None
        if config_str:
            try:
                config = json.loads(config_str)
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON in config: {e}")

        override = form_data.get("override") == "true"
        mode = form_data.get("mode") or None

        if not plugin_name:
            raise HTTPException(status_code=400, detail="Plugin name is required")

        # Get resource from database
        resource = await _get_entity_by_id(db, "resource", resource_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Add simple route
        await route_service.add_simple_route(
            entity_type="resource",
            entity_name=resource.name,
            plugin_name=plugin_name,
            priority=priority,
            hooks=hooks if hooks else None,
            reverse_order_on_post=reverse_order_on_post,
            config=config,
            override=override,
            mode=mode,
        )

        # Save configuration
        await route_service.save_config()

        LOGGER.info(f"Added plugin {plugin_name} to resource {resource.name}")

        # Return updated plugins UI
        return await get_resource_plugins_ui(request, resource_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error adding resource plugin: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plugin_admin_router.delete("/resources/{resource_id}/plugins/{plugin_name}", response_class=HTMLResponse)
async def remove_resource_plugin(
    request: Request,
    resource_id: str,
    plugin_name: str,
    hook: Optional[str] = Query(None, description="Specific hook to remove"),
    db: Session = Depends(get_db),
):
    """Remove a plugin from a resource.

    Args:
        request: The HTTP request object.
        resource_id: The resource ID on which to remove the resource plugin.
        plugin_name: The name of the plugin.
        hook: The name of the hook to remove.
        db: The MCP gateway database session for grabbing metadata.

    Raises:
        HTTPException: if there is an error retrieving and filling the UI template.

    Returns:
        An HTML UI object to be rendered.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Get resource from database
        resource = await _get_entity_by_id(db, "resource", resource_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Remove route
        await route_service.remove_simple_route(
            entity_type="resource",
            entity_name=resource.name,
            plugin_name=plugin_name,
            hook_type=hook,
        )

        # Save configuration
        await route_service.save_config()

        LOGGER.info(f"Removed plugin {plugin_name} from resource {resource.name}")

        # Return updated plugins UI
        return await get_resource_plugins_ui(request, resource_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error removing resource plugin: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plugin_admin_router.post("/resources/{resource_id}/plugins/reverse-post-hooks", response_class=HTMLResponse)
async def toggle_resource_reverse_post_hooks(
    request: Request,
    resource_id: str,
    db: Session = Depends(get_db),
):
    """Toggle reverse order for post-invoke hooks on a resource.

    Args:
        request: The HTTP request object.
        resource_id: The resource ID on which to set the reverse order.
        db: The MCP gateway database session for grabbing metadata.

    Raises:
        HTTPException: if there is an error retrieving and filling the UI template.

    Returns:
        An HTML UI object to be rendered.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Get resource from database
        resource = await _get_entity_by_id(db, "resource", resource_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Toggle reverse order
        await route_service.toggle_reverse_post_hooks("resource", resource.name)

        # Save configuration
        await route_service.save_config()

        LOGGER.info(f"Toggled reverse post-hooks for resource {resource.name}")

        # Return updated plugins UI
        return await get_resource_plugins_ui(request, resource_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error toggling resource reverse post-hooks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plugin_admin_router.post("/resources/{resource_id}/plugins/{plugin_name}/priority", response_class=HTMLResponse)
async def change_resource_plugin_priority(
    request: Request,
    resource_id: str,
    plugin_name: str,
    hook: str = Query(..., description="Hook type (e.g., resource_pre_invoke or resource_post_invoke)"),
    direction: str = Query(..., description="Direction to move: 'up' or 'down'"),
    db: Session = Depends(get_db),
):
    """Change a plugin's priority (move up/down) for a resource.

    Args:
        request: The HTTP request object.
        resource_id: The resource ID on which to set the priority.
        plugin_name: The name of the plugin to set the priority.
        hook: The name of the hook to change the priority.
        direction: The direction to change the priority up or down.
        db: The MCP gateway database session for grabbing metadata.

    Raises:
        HTTPException: if there is an error retrieving and filling the UI template.

    Returns:
        An HTML UI object to be rendered.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Get resource from database
        resource = await _get_entity_by_id(db, "resource", resource_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Change priority
        await route_service.change_priority(
            entity_type="resource",
            entity_name=resource.name,
            plugin_name=plugin_name,
            hook_type=hook,
            direction=direction,
        )

        # Save configuration
        await route_service.save_config()

        LOGGER.info(f"Changed priority for plugin {plugin_name} on resource {resource.name}")

        # Return updated plugins UI
        return await get_resource_plugins_ui(request, resource_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error changing resource plugin priority: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plugin_admin_router.post("/resources/{resource_id}/plugins/{plugin_name}/set-priority", response_class=HTMLResponse)
async def set_resource_plugin_priority(
    request: Request,
    resource_id: str,
    plugin_name: str,
    hook: str = Query(..., description="Hook type (e.g., resource_pre_invoke or resource_post_invoke)"),
    db: Session = Depends(get_db),
):
    """Set a specific priority value for a plugin on a resource.

    Args:
        request: The HTTP request object.
        resource_id: The resource ID on which to set the priority.
        plugin_name: The name of the plugin to set the priority.
        hook: The name of the hook to change the priority.
        db: The MCP gateway database session for grabbing metadata.

    Raises:
        HTTPException: if there is an error retrieving and filling the UI template.

    Returns:
        An HTML UI object to be rendered.
    """
    try:
        # First-Party
        from mcpgateway.services.plugin_route_service import get_plugin_route_service

        # Parse form data
        form_data = await request.form()
        priority = int(form_data.get("priority", 10))

        # Get resource from database
        resource = await _get_entity_by_id(db, "resource", resource_id)

        # Get plugin route service
        route_service = get_plugin_route_service()

        # Set priority
        await route_service.set_priority(
            entity_type="resource",
            entity_name=resource.name,
            plugin_name=plugin_name,
            hook_type=hook,
            priority=priority,
        )

        # Save configuration
        await route_service.save_config()

        LOGGER.info(f"Set priority for plugin {plugin_name} on resource {resource.name} to {priority}")

        # Return updated plugins UI
        return await get_resource_plugins_ui(request, resource_id, db)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error setting resource plugin priority: {e}")
        raise HTTPException(status_code=500, detail=str(e))


##################################################
# Prompt Plugin Routes
##################################################


@plugin_admin_router.get("/prompts/{prompt_id}/plugins-ui", response_class=HTMLResponse)
async def get_prompt_plugins_ui(
    request: Request,
    prompt_id: str,
    db: Session = Depends(get_db),
):
    """Get the plugin management UI for a prompt (returns HTML fragment for HTMX).

    Args:
        request: The HTTP request object.
        prompt_id: The prompt ID for which to return the associated UI.
        db: The MCP gateway database session for grabbing metadata.

    Raises:
        HTTPException: if there is an error retrieving and filling the UI template.

    Returns:
        An HTML UI object to be rendered.
    """
    try:
        context = await _get_entity_plugins_ui_context(request, "prompt", prompt_id, db)
        return request.app.state.templates.TemplateResponse("entity_plugins_partial.html", context)

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Error loading prompt plugins UI: {e}")
        raise HTTPException(status_code=500, detail=str(e))


##################################################
# Prompt Bulk Plugin Routes
# Bulk operations - must come before parameterized routes to avoid path conflicts
##################################################


@plugin_admin_router.post("/prompts/bulk/plugins", response_class=JSONResponse)
async def add_bulk_plugins_to_prompts(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Add a plugin to multiple prompts at once (bulk operation).

    Args:
        request: The HTTP request for bulk adding of prompts.
        db: The MCP gateway database session for grabbing metadata.
        _user: A user authentication object.

    Returns:
        A JSON Response object indicating the success or failure of the operation.
    """
    # First-Party
    from mcpgateway.admin_helpers import (
        bulk_add_plugin_to_entities,
    )
    from mcpgateway.services.plugin_route_service import get_plugin_route_service

    try:
        form_data = await request.form()
        parsed = parse_bulk_plugin_form_data(form_data, "prompt_ids")

        # Parse config JSON
        config, error_response = parse_plugin_config(parsed["config_str"])
        if error_response:
            return error_response

        # Validate inputs
        validation_error = validate_bulk_plugin_inputs(parsed["entity_ids"], parsed["plugin_name"], "prompt")
        if validation_error:
            return validation_error

        LOGGER.info("=== BULK ADD PLUGIN TO PROMPTS REQUEST ===")
        LOGGER.info(f"Prompt IDs: {parsed['entity_ids']}")
        LOGGER.info(f"Plugin Name: {parsed['plugin_name']}")
        LOGGER.info(f"Priority: {parsed['priority']}")
        LOGGER.info(f"Hooks: {parsed['hooks']}")

        route_service = get_plugin_route_service()

        # Bulk add using helper
        success_count, failed_count, errors = await bulk_add_plugin_to_entities(
            entity_ids=parsed["entity_ids"],
            entity_type="prompt",
            get_entity_by_id_func=_get_entity_by_id,
            route_service=route_service,
            db=db,
            plugin_params={
                "plugin_name": parsed["plugin_name"],
                "priority": parsed["priority"],
                "hooks": parsed["hooks"],
                "reverse_order_on_post": parsed["reverse_order_on_post"],
                "config": config,
                "override": parsed["override"],
                "mode": parsed["mode"],
            },
        )

        return build_bulk_operation_response(success_count, failed_count, errors, "prompts", "Added plugin to")

    except Exception as e:
        LOGGER.error(f"Error in bulk add plugins to prompts: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": str(e)},
        )


@plugin_admin_router.delete("/prompts/bulk/plugins", response_class=JSONResponse)
async def remove_bulk_plugins_from_prompts(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Remove a plugin from multiple prompts at once (bulk operation).

    Args:
        request: The HTTP request for bulk removing plugins from prompts.
        db: The MCP gateway database session for grabbing metadata.
        _user: A user authentication object.

    Returns:
        A JSON Response object indicating the success or failure of the operation.
    """
    # First-Party
    from mcpgateway.admin_helpers import (
        bulk_remove_plugin_from_entities,
    )

    form_data = await request.form()
    parsed = parse_remove_plugin_form_data(form_data, "prompt_ids")

    LOGGER.info(f"Bulk remove plugins from prompts - prompt_ids: {parsed['entity_ids']}, plugin_names: {parsed['plugin_names']}, clear_all: {parsed['clear_all']}")

    # Validate inputs
    validation_error = validate_remove_plugin_inputs(parsed["entity_ids"], parsed["plugin_names"], parsed["clear_all"], "prompt")
    if validation_error:
        return validation_error

    # First-Party
    from mcpgateway.plugins.framework.hooks.registry import get_hook_registry, HookPhase
    from mcpgateway.services.plugin_route_service import get_plugin_route_service

    route_service = get_plugin_route_service()

    # Handle clear_all case (must stay custom due to hook registry logic)
    if parsed["clear_all"]:
        hook_registry = get_hook_registry()
        success_count = 0
        failed_count = 0
        errors = []

        for prompt_id in parsed["entity_ids"]:
            try:
                prompt = await _get_entity_by_id(db, "prompt", prompt_id)

                pre_hook_types = hook_registry.get_hooks_for_entity_type("prompt", HookPhase.PRE)
                post_hook_types = hook_registry.get_hooks_for_entity_type("prompt", HookPhase.POST)

                all_plugin_names = set()

                if pre_hook_types:
                    pre_plugins = await _get_plugins_for_entity_and_hook(
                        route_service,
                        entity_type="prompt",
                        entity_name=prompt.name,
                        entity_id=str(prompt.id),
                        tags=prompt.tags or [],
                        server_name=None,
                        server_id=None,
                        hook_type=pre_hook_types[0],
                    )
                    all_plugin_names.update(p.get("name", "") for p in pre_plugins)

                if post_hook_types:
                    post_plugins = await _get_plugins_for_entity_and_hook(
                        route_service,
                        entity_type="prompt",
                        entity_name=prompt.name,
                        entity_id=str(prompt.id),
                        tags=prompt.tags or [],
                        server_name=None,
                        server_id=None,
                        hook_type=post_hook_types[0],
                    )
                    all_plugin_names.update(p.get("name", "") for p in post_plugins)

                for pname in all_plugin_names:
                    if pname:
                        removed = await route_service.remove_plugin_from_entity(
                            entity_type="prompt",
                            entity_name=prompt.name,
                            plugin_name=pname,
                        )
                        if removed:
                            success_count += 1
                        else:
                            failed_count += 1

            except Exception as e:
                LOGGER.warning(f"Error clearing plugins for prompt {prompt_id}: {e}")
                failed_count += 1
                errors.append({"prompt_id": prompt_id, "error": str(e)})

        return JSONResponse(
            content={
                "success": True,
                "message": f"Cleared plugins from {len(parsed['entity_ids'])} prompts",
                "removed": success_count,
                "failed": failed_count,
                "errors": errors if errors else None,
            }
        )

    # Handle normal remove using helper
    success_count, failed_count, errors = await bulk_remove_plugin_from_entities(
        entity_ids=parsed["entity_ids"],
        entity_type="prompt",
        plugin_names=parsed["plugin_names"],
        get_entity_by_id_func=_get_entity_by_id,
        route_service=route_service,
        db=db,
    )

    return JSONResponse(
        content={
            "success": True,
            "message": f"Removed {success_count} plugin attachment(s)" + (f", {failed_count} failed" if failed_count > 0 else ""),
            "success_count": success_count,
            "failed_count": failed_count,
            "errors": errors if errors else None,
        }
    )


@plugin_admin_router.post("/prompts/bulk/plugins/priority", response_class=JSONResponse)
async def update_bulk_plugin_priority_for_prompts(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
):
    """Update plugin priority for multiple prompts at once (bulk operation).

    Args:
        request: The HTTP request for updating plugin priority for prompts.
        db: The MCP gateway database session for grabbing metadata.
        _user: A user authentication object.

    Returns:
        A JSON Response object indicating the success or failure of the operation.
    """
    # First-Party
    from mcpgateway.admin_helpers import (
        bulk_update_plugin_priority_for_entities,
    )
    from mcpgateway.services.plugin_route_service import get_plugin_route_service

    try:
        form_data = await request.form()
        prompt_ids = form_data.getlist("prompt_ids")
        plugin_name = form_data.get("plugin_name")
        new_priority = int(form_data.get("priority", 10))

        LOGGER.info(f"Bulk update priority for prompts - prompt_ids: {prompt_ids}, plugin: {plugin_name}, priority: {new_priority}")

        # Validate inputs
        validation_error = validate_bulk_plugin_inputs(prompt_ids, plugin_name, "prompt")
        if validation_error:
            return validation_error

        route_service = get_plugin_route_service()

        # Bulk update using helper
        success_count, failed_count, errors = await bulk_update_plugin_priority_for_entities(
            entity_ids=prompt_ids,
            entity_type="prompt",
            plugin_name=plugin_name,
            priority=new_priority,
            get_entity_by_id_func=_get_entity_by_id,
            route_service=route_service,
            db=db,
        )

        return build_bulk_operation_response(success_count, failed_count, errors, "prompts", "Updated priority for")

    except Exception as e:
        LOGGER.error(f"Error in bulk update plugin priority for prompts: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": str(e)},
        )
