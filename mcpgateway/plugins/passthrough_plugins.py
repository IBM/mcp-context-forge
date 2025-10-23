# -*- coding: utf-8 -*-
"""
Passthrough Plugin Framework

Copyright 2025
SPDX-License-Identifier: Apache-2.0

This module provides a plugin framework for REST passthrough endpoints.
Integrates with the existing MCP Gateway plugin framework to provide
pre- and post-processing plugin chains for validation, transformation, 
redaction, and auditing of passthrough requests and responses.

Key Features:
- Integration with existing plugin framework
- Pre-request and post-response hooks
- Context passing between plugins
- Error handling and plugin isolation
- Uses existing plugins (PII filter, deny filter, regex filter, etc.)

Usage:
    # Execute plugin chain using existing framework
    result = await on_passthrough_request(context, request, chain=["deny_filter", "pii_filter"])
    result = await on_passthrough_response(context, request, response, chain=["pii_filter"])

See also:
- mcpgateway.routers.rest_passthrough for usage
- plugins/config.yaml for configuration
- plugins/ directory for existing plugin implementations
"""

import logging
from typing import Any, Dict, List, Optional, Union
import asyncio

# First-Party
from mcpgateway.plugins.framework import (
    PluginManager,
    PluginContext,
    GlobalContext,
    PluginViolation,
    HookType,
    PassthroughPreRequestPayload,
    PassthroughPostResponsePayload,
    PassthroughPreRequestResult,
    PassthroughPostResponseResult
)
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Global plugin manager instance
_plugin_manager: Optional[PluginManager] = None


async def get_plugin_manager() -> PluginManager:
    """
    Get or initialize the global plugin manager.
    
    Returns:
        Initialized plugin manager instance
    """
    global _plugin_manager
    if _plugin_manager is None:
        # Initialize plugin manager with default config
        _plugin_manager = PluginManager("plugins/config.yaml")
        await _plugin_manager.initialize()
        logger.info("Initialized plugin manager for passthrough processing")
    return _plugin_manager


def map_passthrough_plugin_names(plugin_names: List[str]) -> List[str]:
    """
    Map passthrough plugin names to actual plugin names in the framework.
    
    Args:
        plugin_names: List of plugin names used in passthrough context
        
    Returns:
        List of actual plugin names that exist in the framework
    """
    # Mapping from passthrough plugin names to actual plugin names
    name_mapping = {
        "deny_filter": "DenyListPlugin",
        "pii_filter": "PIIFilterPlugin", 
        "regex_filter": "ReplaceBadWordsPlugin",  # Using the search/replace plugin
        "resource_filter": "ResourceFilterExample",
        "rate_limit": "RateLimiterPlugin",
        "response_shape": None,  # This will be handled separately as it's passthrough-specific
    }
    
    mapped_names = []
    for name in plugin_names:
        mapped_name = name_mapping.get(name)
        if mapped_name:
            mapped_names.append(mapped_name)
        elif name == "response_shape":
            # Keep response_shape for separate handling
            mapped_names.append(name)
        else:
            logger.warning(f"Unknown passthrough plugin: {name}")
            
    return mapped_names


async def execute_plugin_chain_with_framework(
    chain: List[str], 
    context: Dict[str, Any], 
    data: Any,
    hook_type: HookType,
    **kwargs
) -> Any:
    """
    Execute a chain of plugins using the plugin framework.
    
    Args:
        chain: List of plugin names to execute in order
        context: Shared context dict (tool_id, user, etc.)
        data: Data to process (request or response)
        hook_type: Type of hook to execute
        **kwargs: Additional arguments passed to plugins
        
    Returns:
        Processed data after all plugins
        
    Raises:
        PluginViolationError: If any plugin blocks processing
        Exception: Plugin execution errors (logged but not re-raised)
    """
    if not chain:
        return data
        
    plugin_manager = await get_plugin_manager()
    
    # Map plugin names to framework names
    mapped_chain = map_passthrough_plugin_names(chain)
    
    # Create global context for plugin execution
    global_context = GlobalContext(
        request_id=context.get("request_id", "unknown"),
        user=context.get("user", "anonymous"),
        tenant_id=context.get("tenant_id", "default")
    )
    
    result_data = data
    
    # Handle response_shape separately as it's passthrough-specific
    if "response_shape" in mapped_chain:
        result_data = await _handle_response_shape(context, result_data, **kwargs)
        mapped_chain = [name for name in mapped_chain if name != "response_shape"]
    
    # Use the proper framework hooks
    if hook_type == HookType.PASSTHROUGH_PRE_REQUEST and mapped_chain:
        # Create payload for pre-request processing
        payload = PassthroughPreRequestPayload(
            method=result_data.get("method", "GET"),
            headers=result_data.get("headers", {}),
            params=result_data.get("params", {}),
            body=result_data.get("body"),
            url=result_data.get("url", ""),
            tool_id=context.get("tool_id")
        )
        
        # Execute through framework
        try:
            result, _ = await plugin_manager.passthrough_pre_request(payload, global_context, plugin_chain=mapped_chain)
            if result.continue_processing and result.modified_payload:
                # Extract modified data back to original format
                modified = result.modified_payload
                result_data = {
                    "method": modified.method,
                    "headers": modified.headers,
                    "params": modified.params,
                    "body": modified.body,
                    "url": modified.url
                }
            elif not result.continue_processing and result.violation:
                logger.warning(f"Passthrough request blocked by plugin: {result.violation.reason}")
                raise ValueError(f"Request blocked: {result.violation.reason}")
        except Exception as e:
            logger.error(f"Error in passthrough pre-request processing: {e}", exc_info=True)
    
    elif hook_type == HookType.PASSTHROUGH_POST_RESPONSE and mapped_chain:
        # Create payload for post-response processing
        payload = PassthroughPostResponsePayload(
            response=result_data,
            original_request=kwargs.get("original_request", {}),
            status_code=getattr(result_data, 'status_code', 200),
            headers=getattr(result_data, 'headers', {}),
            content=getattr(result_data, 'content', None),
            tool_id=context.get("tool_id")
        )
        
        # Execute through framework
        try:
            result, _ = await plugin_manager.passthrough_post_response(payload, global_context, plugin_chain=mapped_chain)
            if result.continue_processing and result.modified_payload:
                # Use the modified response
                result_data = result.modified_payload.response
            elif not result.continue_processing and result.violation:
                logger.warning(f"Passthrough response blocked by plugin: {result.violation.reason}")
                raise ValueError(f"Response blocked: {result.violation.reason}")
        except Exception as e:
            logger.error(f"Error in passthrough post-response processing: {e}", exc_info=True)
    
    return result_data


async def _handle_response_shape(context: Dict[str, Any], data: Any, **kwargs) -> Any:
    """
    Handle response shaping for passthrough responses.
    This is a built-in function for passthrough-specific logic.
    """
    request_type = kwargs.get("request_type", "unknown")
    
    if request_type == "post":
        # Only process responses
        if hasattr(data, 'content') and data.content:
            try:
                import json
                # Try to parse as JSON and wrap in standard format
                if hasattr(data, 'headers') and 'application/json' in str(data.headers.get('content-type', '')):
                    content = data.content
                    if isinstance(content, bytes):
                        content = content.decode('utf-8')
                    
                    json_data = json.loads(content)
                    
                    # Wrap in standard response format if not already wrapped
                    if not isinstance(json_data, dict) or "data" not in json_data:
                        wrapped = {
                            "data": json_data,
                            "meta": {
                                "tool_id": context.get("tool_id"),
                                "processed_at": context.get("timestamp"),
                                "processed_by": "passthrough_plugin"
                            }
                        }
                        data.content = json.dumps(wrapped).encode('utf-8')
                        
            except (json.JSONDecodeError, AttributeError):
                # Not JSON or can't process, leave as-is
                pass
    
    return data


async def on_passthrough_request(
    context: Dict[str, Any],
    mapped_request: Dict[str, Any],
    chain: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Execute pre-processing plugin chain on passthrough request.
    
    Args:
        context: Request context (tool_id, user, etc.)
        mapped_request: Mapped request dict with method, headers, params, body
        chain: Plugin chain to execute (defaults to config)
        
    Returns:
        Processed request data
    """
    if not chain:
        # Use default pre-processing chain from config
        chain = ["deny_filter", "pii_filter", "regex_filter", "resource_filter", "rate_limit"]
        
    logger.info(f"Executing pre-request plugin chain: {chain}")
    
    try:
        return await execute_plugin_chain_with_framework(
            chain, context, mapped_request, 
            HookType.PASSTHROUGH_PRE_REQUEST,  # Use the new passthrough-specific hook
            request_type="pre"
        )
    except Exception as e:
        logger.error(f"Error in passthrough request processing: {e}", exc_info=True)
        return mapped_request


async def on_passthrough_response(
    context: Dict[str, Any],
    mapped_request: Dict[str, Any],
    response: Any,
    chain: Optional[List[str]] = None
) -> Any:
    """
    Execute post-processing plugin chain on passthrough response.
    
    Args:
        context: Request context (tool_id, user, etc.)  
        mapped_request: Original mapped request for reference
        response: Response object to process
        chain: Plugin chain to execute (defaults to config)
        
    Returns:
        Processed response
    """
    if not chain:
        # Use default post-processing chain from config
        chain = ["pii_filter", "response_shape"]
        
    logger.debug(f"Executing post-response plugin chain: {chain}")
    
    try:
        return await execute_plugin_chain_with_framework(
            chain, context, response,
            HookType.PASSTHROUGH_POST_RESPONSE,  # Use the new passthrough-specific hook
            request_type="post", 
            original_request=mapped_request
        )
    except Exception as e:
        logger.error(f"Error in passthrough response processing: {e}", exc_info=True)
        return response


async def get_available_plugins() -> List[str]:
    """
    Get list of available plugin names from the plugin framework.
    
    Returns:
        List of available plugin names for passthrough processing
    """
    try:
        plugin_manager = await get_plugin_manager()
        # Get all plugins that could be used for passthrough processing
        available_plugins = []
        
        # Add plugins that are mapped for passthrough use
        plugin_mapping = {
            "deny_filter": "DenyListPlugin",
            "pii_filter": "PIIFilterPlugin", 
            "regex_filter": "ReplaceBadWordsPlugin",
            "resource_filter": "ResourceFilterExample",
            "rate_limit": "RateLimiterPlugin",
            "response_shape": "response_shape"  # Built-in
        }
        
        for passthrough_name, actual_name in plugin_mapping.items():
            if actual_name == "response_shape" or plugin_manager.registry.get_plugin(actual_name):
                available_plugins.append(passthrough_name)
                
        return available_plugins
        
    except Exception as e:
        logger.error(f"Error getting available plugins: {e}")
        return ["deny_filter", "pii_filter", "regex_filter", "resource_filter", "rate_limit", "response_shape"]


async def get_plugin_info() -> Dict[str, Dict[str, Any]]:
    """
    Get information about all available passthrough plugins.
    
    Returns:
        Dict mapping plugin names to their info
    """
    info = {}
    
    try:
        plugin_manager = await get_plugin_manager()
        
        # Information about mapped plugins
        plugin_mapping = {
            "deny_filter": {
                "actual_name": "DenyListPlugin",
                "description": "Blocks requests/responses based on deny list patterns",
                "hooks": ["pre-request"]
            },
            "pii_filter": {
                "actual_name": "PIIFilterPlugin", 
                "description": "Detects and masks Personally Identifiable Information",
                "hooks": ["pre-request", "post-response"]
            },
            "regex_filter": {
                "actual_name": "ReplaceBadWordsPlugin",
                "description": "Applies regex transformations and word replacements",
                "hooks": ["pre-request", "post-response"]
            },
            "resource_filter": {
                "actual_name": "ResourceFilterExample",
                "description": "Manages resource access and quotas",
                "hooks": ["pre-request", "post-response"]
            },
            "rate_limit": {
                "actual_name": "RateLimiterPlugin",
                "description": "Enforces request rate limits per user/tool",
                "hooks": ["pre-request"]
            },
            "response_shape": {
                "actual_name": "response_shape",
                "description": "Transforms response structure and format",
                "hooks": ["post-response"]
            }
        }
        
        for passthrough_name, plugin_info in plugin_mapping.items():
            actual_name = plugin_info["actual_name"]
            
            if actual_name == "response_shape":
                # Built-in passthrough-specific plugin
                info[passthrough_name] = {
                    "name": passthrough_name,
                    "actual_name": actual_name,
                    "description": plugin_info["description"],
                    "hooks": plugin_info["hooks"],
                    "type": "built-in"
                }
            else:
                # Framework plugin
                framework_plugin = plugin_manager.registry.get_plugin(actual_name)
                if framework_plugin:
                    info[passthrough_name] = {
                        "name": passthrough_name,
                        "actual_name": actual_name,
                        "description": plugin_info["description"],
                        "hooks": plugin_info["hooks"],
                        "type": "framework",
                        "framework_info": {
                            "author": framework_plugin.config.author,
                            "version": framework_plugin.config.version,
                            "tags": framework_plugin.config.tags
                        }
                    }
                    
    except Exception as e:
        logger.error(f"Error getting plugin info: {e}")
        
    return info


async def shutdown_passthrough_plugins():
    """
    Shutdown the passthrough plugin system.
    """
    global _plugin_manager
    if _plugin_manager:
        await _plugin_manager.shutdown()
        _plugin_manager = None
        logger.info("Passthrough plugin system shut down")