"""
Helper functions for admin UI operations.

This module contains shared utility functions used by admin.py to reduce
code duplication across bulk plugin operations and other admin endpoints.
"""

# Standard
import json
import logging
from typing import Any, Callable

# Third-Party
from fastapi.responses import JSONResponse

LOGGER = logging.getLogger(__name__)


def parse_bulk_plugin_form_data(form_data, entity_id_key: str) -> dict[str, Any]:
    """Parse common bulk plugin operation form fields.

    Args:
        form_data: FastAPI form data object
        entity_id_key: Key for entity IDs (e.g., 'tool_ids', 'prompt_ids', 'resource_ids')

    Returns:
        Dictionary with parsed fields:
        - entity_ids: List of entity IDs
        - plugin_name: Plugin name (from plugin_name or plugin_names field)
        - priority: Integer priority (default 10)
        - hooks: List of hook names or None
        - reverse_order_on_post: Boolean flag
        - config_str: Raw config string
        - override: Boolean flag
        - scope: Scope string (default 'local')
        - mode: Mode string or None
    """
    entity_ids = form_data.getlist(entity_id_key)
    plugin_name = form_data.get("plugin_name") or form_data.get("plugin_names")
    priority_str = form_data.get("priority", "10")
    priority = int(priority_str) if priority_str and priority_str.strip() else 10
    hooks = form_data.getlist("hooks") if "hooks" in form_data else None
    reverse_order_on_post = form_data.get("reverse_order_on_post") == "true"
    config_str = form_data.get("config", "").strip()
    override = form_data.get("override") == "true"
    scope = form_data.get("scope", "local")
    mode = form_data.get("mode") or None

    return {
        "entity_ids": entity_ids,
        "plugin_name": plugin_name,
        "priority": priority,
        "hooks": hooks,
        "reverse_order_on_post": reverse_order_on_post,
        "config_str": config_str,
        "override": override,
        "scope": scope,
        "mode": mode,
    }


def parse_remove_plugin_form_data(form_data, entity_id_key: str) -> dict[str, Any]:
    """Parse form data for bulk plugin removal operations.

    Handles both single and multiple plugin names, plus clear_all flag.

    Args:
        form_data: FastAPI form data object
        entity_id_key: Key for entity IDs (e.g., 'tool_ids', 'prompt_ids', 'resource_ids')

    Returns:
        Dictionary with parsed fields:
        - entity_ids: List of entity IDs
        - plugin_names: List of plugin names to remove
        - clear_all: Boolean flag to remove all plugins
    """
    entity_ids = form_data.getlist(entity_id_key)

    # Accept both singular and plural forms, support multiple plugins
    plugin_names_list = form_data.getlist("plugin_names")
    plugin_name_list = form_data.getlist("plugin_name")

    plugin_names = plugin_names_list if plugin_names_list else plugin_name_list

    # Fallback to single value if getlist returns empty
    if not plugin_names:
        single_name = form_data.get("plugin_names") or form_data.get("plugin_name")
        if single_name:
            plugin_names = [single_name]

    clear_all = form_data.get("clear_all") == "true"

    return {
        "entity_ids": entity_ids,
        "plugin_names": plugin_names,
        "clear_all": clear_all,
    }


def parse_plugin_config(config_str: str) -> tuple[dict | None, JSONResponse | None]:
    """Parse plugin config JSON string.

    Args:
        config_str: JSON string to parse

    Returns:
        Tuple of (parsed_config, error_response):
        - If parsing succeeds: (config_dict, None)
        - If parsing fails: (None, JSONResponse with 400 error)
        - If empty string: (None, None)
    """
    if not config_str:
        return None, None

    try:
        config = json.loads(config_str)
        return config, None
    except json.JSONDecodeError as e:
        error_response = JSONResponse(
            status_code=400,
            content={"success": False, "message": f"Invalid JSON in config: {e}"},
        )
        return None, error_response


def validate_bulk_plugin_inputs(
    entity_ids: list,
    plugin_name: str | None,
    entity_type: str,
    require_plugin_name: bool = True,
) -> JSONResponse | None:
    """Validate bulk plugin operation inputs.

    Args:
        entity_ids: List of entity IDs
        plugin_name: Plugin name to validate
        entity_type: Entity type name for error messages (e.g., 'tool', 'prompt', 'resource')
        require_plugin_name: Whether to require plugin_name to be present

    Returns:
        JSONResponse with 400 error if validation fails, None if valid
    """
    if not entity_ids:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": f"No {entity_type} IDs provided"},
        )

    if require_plugin_name and not plugin_name:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "No plugin name provided"},
        )

    return None


def validate_remove_plugin_inputs(
    entity_ids: list,
    plugin_names: list,
    clear_all: bool,
    entity_type: str,
) -> JSONResponse | None:
    """Validate bulk plugin removal operation inputs.

    Args:
        entity_ids: List of entity IDs
        plugin_names: List of plugin names to remove
        clear_all: Whether to clear all plugins
        entity_type: Entity type name for error messages

    Returns:
        JSONResponse with 400 error if validation fails, None if valid
    """
    if not entity_ids:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": f"No {entity_type} IDs provided"},
        )

    if not plugin_names and not clear_all:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "No plugin name provided"},
        )

    return None


def build_bulk_operation_response(
    success_count: int,
    failed_count: int,
    errors: list,
    entity_type: str,
    operation: str = "Added plugin to",
) -> JSONResponse:
    """Build standardized bulk operation response.

    Args:
        success_count: Number of successful operations
        failed_count: Number of failed operations
        errors: List of error dictionaries
        entity_type: Entity type in plural form (e.g., 'resources', 'prompts', 'tools')
        operation: Operation description prefix

    Returns:
        JSONResponse with standardized success/failure information
    """
    message = f"{operation} {success_count} {entity_type}"
    if failed_count > 0:
        message += f", {failed_count} failed"

    return JSONResponse(
        content={
            "success": True,
            "message": message,
            "success_count": success_count,
            "failed_count": failed_count,
            "errors": errors if errors else None,
        }
    )


async def bulk_add_plugin_to_entities(
    entity_ids: list[str],
    entity_type: str,
    get_entity_by_id_func: Callable,
    route_service: Any,
    db: Any,
    plugin_params: dict[str, Any],
) -> tuple[int, int, list[dict[str, Any]]]:
    """Add a plugin to multiple entities in bulk.

    Args:
        entity_ids: List of entity IDs to process
        entity_type: Entity type ('tool', 'prompt', 'resource')
        get_entity_by_id_func: Async function to get entity by ID
        route_service: Plugin route service instance
        db: Database session
        plugin_params: Dictionary of plugin parameters (plugin_name, priority, hooks, etc.)

    Returns:
        Tuple of (success_count, failed_count, errors)
    """
    success_count = 0
    failed_count = 0
    errors = []

    for entity_id in entity_ids:
        try:
            entity = await get_entity_by_id_func(db, entity_type, entity_id)

            await route_service.add_simple_route(
                entity_type=entity_type,
                entity_name=entity.name,
                plugin_name=plugin_params["plugin_name"],
                priority=plugin_params["priority"],
                hooks=plugin_params.get("hooks"),
                reverse_order_on_post=plugin_params.get("reverse_order_on_post", False),
                config=plugin_params.get("config"),
                override=plugin_params.get("override", False),
                mode=plugin_params.get("mode"),
            )
            success_count += 1

        except Exception as e:
            LOGGER.error(f"Failed to add plugin to {entity_type} {entity_id}: {e}")
            failed_count += 1
            errors.append({f"{entity_type}_id": entity_id, "error": str(e)})

    return success_count, failed_count, errors


async def bulk_remove_plugin_from_entities(
    entity_ids: list[str],
    entity_type: str,
    plugin_names: list[str],
    get_entity_by_id_func: Callable,
    route_service: Any,
    db: Any,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Remove plugin(s) from multiple entities in bulk.

    Args:
        entity_ids: List of entity IDs to process
        entity_type: Entity type ('tool', 'prompt', 'resource')
        plugin_names: List of plugin names to remove
        get_entity_by_id_func: Async function to get entity by ID
        route_service: Plugin route service instance
        db: Database session

    Returns:
        Tuple of (success_count, failed_count, errors)
    """
    success_count = 0
    failed_count = 0
    errors = []

    for entity_id in entity_ids:
        try:
            entity = await get_entity_by_id_func(db, entity_type, entity_id)

            for plugin_name in plugin_names:
                removed = await route_service.remove_plugin_from_entity(
                    entity_type=entity_type,
                    entity_name=entity.name,
                    plugin_name=plugin_name,
                )
                if removed:
                    success_count += 1
                else:
                    failed_count += 1

        except Exception as e:
            LOGGER.warning(f"Error removing plugins from {entity_type} {entity_id}: {e}")
            failed_count += 1
            errors.append({f"{entity_type}_id": entity_id, "error": str(e)})

    return success_count, failed_count, errors


async def bulk_update_plugin_priority_for_entities(
    entity_ids: list[str],
    entity_type: str,
    plugin_name: str,
    priority: int,
    get_entity_by_id_func: Callable,
    route_service: Any,
    db: Any,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Update plugin priority for multiple entities in bulk.

    Args:
        entity_ids: List of entity IDs to process
        entity_type: Entity type ('tool', 'prompt', 'resource')
        plugin_name: Name of plugin to update
        priority: New priority value
        get_entity_by_id_func: Async function to get entity by ID
        route_service: Plugin route service instance
        db: Database session

    Returns:
        Tuple of (success_count, failed_count, errors)
    """
    success_count = 0
    failed_count = 0
    errors = []

    for entity_id in entity_ids:
        try:
            entity = await get_entity_by_id_func(db, entity_type, entity_id)

            await route_service.update_plugin_priority(
                entity_type=entity_type,
                entity_name=entity.name,
                plugin_name=plugin_name,
                new_priority=priority,
            )
            success_count += 1

        except Exception as e:
            LOGGER.error(f"Failed to update priority for {entity_type} {entity_id}: {e}")
            failed_count += 1
            errors.append({f"{entity_type}_id": entity_id, "error": str(e)})

    return success_count, failed_count, errors
