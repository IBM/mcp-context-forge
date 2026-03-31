# -*- coding: utf-8 -*-
"""Location: ./plugins/crt_router/crt_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

CRT (Chinese Remainder Theorem) based semantic tool router plugin.

This plugin implements a two-phase routing algorithm:
1. CRT Pre-filtering: Use modular arithmetic to filter incompatible tools
2. Semantic Ranking: Apply embedding-based similarity on filtered subset

Provides both:
- API methods (rank_tools, get_health) for direct endpoint invocation  
- Hook method (tool_pre_invoke) for automatic tool validation
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from mcpgateway.services.embedding_service import EmbeddingService
from plugins.crt_router.semantic_router import CRTRouter

logger = logging.getLogger(__name__)


class CRTRouterConfig(BaseModel):
    """Configuration for CRT Router plugin."""
    calibration_path: str = Field(
        default="data/calibration/crt_model.json",
        description="Path to calibration artifacts"
    )
    default_k: int = Field(default=10, description="Default top-K tools to expose")
    default_threshold: float = Field(
        default=0.72,
        description="Default relevance threshold"
    )
    cache_enabled: bool = Field(default=True, description="Enable routing cache")


class CRTRouterPlugin(Plugin):
    """CRT (Chinese Remainder Theorem) based semantic tool router for MCP Gateway.
    
    Implements efficient tool routing using a two-phase algorithm:
    - Phase 1: CRT pre-filtering eliminates 70-90% of incompatible tools via modular arithmetic
    - Phase 2: Semantic ranking scores remaining tools using embedding similarity
    
    Provides two modes of operation:
    1. API method (rank_tools): Called directly from GET /servers/{server_id}/tools endpoint
    2. Hook method (tool_pre_invoke): Automatic validation of tool invocations
    
    Requires calibration artifacts with prime_list, difficulty_bins, success_tables,
    and tool_embeddings.
    """

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._cfg = CRTRouterConfig(**(config.config or {}))
        self._router: Optional[CRTRouter] = None
        self._embedding_service: Optional[EmbeddingService] = None
        
        # Backward compatibility: expose config values as attributes for tests
        self._calibration_path = self._cfg.calibration_path
        self._default_k = self._cfg.default_k
        self._default_threshold = self._cfg.default_threshold

    async def initialize(self) -> None:
        """Initialize CRT router with calibration data from JSON file."""
        try:
            self._router = CRTRouter.from_json(self._cfg.calibration_path)
            logger.info("CRTRouterPlugin: calibration loaded from '%s'", self._cfg.calibration_path)
        except FileNotFoundError:
            # Calibration file not found - instantiate with empty tool set as fallback
            self._router = CRTRouter.from_tool_embeddings({})
            logger.warning(
                "Calibration file not found at %s - CRT router initialized with empty tool set",
                self._cfg.calibration_path
            )
        
        # Embedding service is initialized lazily on first use (see _ensure_embedding_service)
        self._embedding_service = EmbeddingService()

    async def shutdown(self) -> None:
        """Shut down the plugin."""
        logger.info("CRTRouterPlugin shutting down")
    
    async def _ensure_embedding_service(self) -> bool:
        """Ensure embedding service is initialized. Returns True if ready, False otherwise.
        
        This lazy initialization allows the plugin to be registered without requiring
        langchain-openai dependencies until the service is actually needed.
        """
        if not self._embedding_service:
            return False
            
        # Check if already initialized
        if hasattr(self._embedding_service, '_initialized') and self._embedding_service._initialized:
            return True
            
        try:
            await self._embedding_service.initialize()
            return True
        except ImportError as e:
            logger.warning(
                "CRT router embedding service unavailable: %s - plugin will operate in degraded mode",
                str(e)
            )
            return False
        except Exception as e:
            logger.error(
                "Failed to initialize embedding service: %s - plugin will operate in degraded mode",
                str(e),
                exc_info=True
            )
            return False

    # ========================================================================
    # API Methods (for direct endpoint invocation)
    # ========================================================================

    async def rank_tools(
        self,
        tools: List[Any],
        prompt: str,
        k: int,
        threshold: float,
        db: Optional[Any] = None,
    ) -> List[Tuple[Any, Dict[str, float]]]:
        """Rank tools by relevance to the given prompt (API method).

        Called directly from GET /servers/{server_id}/tools endpoint to filter
        and rank the tool list by relevance to a user prompt.

        Returns a list of (tool, scores) tuples where scores contains:
            - relevance: float in [0, 1] — higher means more relevant
            - loss:      float in [0, 1] — expected mis-selection cost (placeholder)  
            - entropy:   float in bits  — uncertainty of routing decision (placeholder)

        The list is ordered by relevance descending.

        Args:
            tools:     The full list of ToolRead objects from list_server_tools().
            prompt:    The natural language prompt from the API caller.
            k:         Maximum number of tools to return.
            threshold: Minimum relevance score to include a tool.
            db:        SQLAlchemy session (optional, for future use).

        Returns:
            List of (tool, scores_dict) tuples ordered by relevance descending.
        """
        if not self._router:
            logger.warning("CRT router not initialized - returning all tools with neutral scores")
            return [(tool, {"relevance": 1.0, "loss": 0.0, "entropy": 0.0}) for tool in tools]
        
        # Ensure embedding service is ready
        if not await self._ensure_embedding_service():
            logger.warning("Embedding service unavailable - returning all tools with neutral scores")
            return [(tool, {"relevance": 1.0, "loss": 0.0, "entropy": 0.0}) for tool in tools]
        
        try:
            # Generate prompt embedding
            prompt_embedding = await self._embedding_service.embed_query(prompt)
            
            # Get tool names for matching
            tool_name_map = {tool.original_name: tool for tool in tools}
            available_tool_names = list(tool_name_map.keys())
            
            # Rank tools using CRT router
            ranked = self._router.rank_tools(
                prompt_embedding=prompt_embedding,
                available_tools=available_tool_names,
                k=k,
                threshold=threshold
            )
            
            # Convert to API format: (tool, scores_dict)
            result = []
            for tool_score in ranked:
                if tool_score.tool_name in tool_name_map:
                    tool_obj = tool_name_map[tool_score.tool_name]
                    scores = {
                        "relevance": tool_score.relevance_score,
                        "loss": 0.0,  # Placeholder for future loss estimation
                        "entropy": 0.0,  # Placeholder for future uncertainty estimation
                    }
                    result.append((tool_obj, scores))
            
            logger.debug(
                "CRTRouterPlugin.rank_tools: prompt=%r, k=%d, threshold=%.2f, input_tools=%d, ranked=%d",
                prompt, k, threshold, len(tools), len(result)
            )
            return result
            
        except Exception as e:
            logger.error(
                "CRT router error during tool ranking: %s - returning all tools with neutral scores",
                str(e),
                exc_info=True
            )
            return [(tool, {"relevance": 1.0, "loss": 0.0, "entropy": 0.0}) for tool in tools]

    async def get_health(self) -> Dict[str, Any]:
        """Return calibration and version information for the /router/health endpoint.

        Returns:
            Dictionary with status, version, calibration_checksum, and calibration_state.
        """
        import os  # pylint: disable=import-outside-toplevel

        calibration_available = os.path.exists(self._cfg.calibration_path)
        router_initialized = self._router is not None
        embedding_available = await self._ensure_embedding_service()
        
        # Status is healthy if calibration file exists (primary requirement)
        # Router and embedding service availability are tracked separately
        status = "healthy" if calibration_available else "degraded"
        
        return {
            "status": status,
            "version": "1.0.0",
            "calibration_checksum": "n/a",  # TODO: Compute checksum from calibration file
            "calibration_state": "available" if calibration_available else "missing",
            "calibration_path": self._cfg.calibration_path,
            "router_initialized": router_initialized,
            "embedding_service_available": embedding_available,
        }

    # ========================================================================
    # Hook Methods (for automatic tool validation)
    # ========================================================================

    async def tool_pre_invoke(
        self,
        payload: ToolPreInvokePayload,
        context: PluginContext
    ) -> ToolPreInvokeResult:
        """Filter and rank tools using CRT pre-filtering + semantic similarity (Hook method).
        
        This hook intercepts tool invocations to apply intelligent routing:
        1. Extract query from payload.args['query']
        2. Generate query embedding using EmbeddingService
        3. CRT Phase: Filter tools based on capability matching via modular arithmetic
        4. Semantic Phase: Rank filtered tools by embedding similarity to query
        5. Validate that the invoked tool (payload.name) is in the top-k ranked tools
        6. Block invocation if tool is not relevant (not in top-k or below threshold)
        
        Args:
            payload: Tool invocation payload containing tool name and arguments
            context: Plugin execution context
            
        Returns:
            ToolPreInvokeResult with continue_processing=True if tool is relevant,
            or continue_processing=False with violation if tool should be blocked
        """
        # Early return if router not initialized
        if not self._router:
            logger.warning("CRT router not initialized - allowing invocation")
            return ToolPreInvokeResult(continue_processing=True)
        
        # Ensure embedding service is ready (lazy initialization)
        if not await self._ensure_embedding_service():
            logger.debug("CRT router embedding service unavailable - allowing invocation")
            return ToolPreInvokeResult(continue_processing=True)
        
        # Extract query from payload.args
        if not payload.args:
            logger.debug("No args in payload - allowing invocation")
            return ToolPreInvokeResult(continue_processing=True)
            
        query = payload.args.get("query")
        if not query or not isinstance(query, str):
            # No query provided - allow invocation (not a routing decision)
            logger.debug("No 'query' key in payload.args - allowing invocation")
            return ToolPreInvokeResult(continue_processing=True)
        
        try:
            # Generate query embedding
            query_embedding = await self._embedding_service.embed_query(query)
            
            # Rank tools using CRT router
            ranked_tools = self._router.rank_tools(
                prompt_embedding=query_embedding,
                available_tools=None,  # Consider all calibrated tools
                k=self._cfg.default_k,
                threshold=self._cfg.default_threshold
            )
            
            # Check if invoked tool is in the ranked results
            tool_names = [result.tool_name for result in ranked_tools]
            
            if payload.name in tool_names:
                # Tool is relevant - find its rank and score
                tool_result = next((r for r in ranked_tools if r.tool_name == payload.name), None)
                logger.info(
                    "CRT router allowed tool '%s' - rank %d/%d, relevance %.3f",
                    payload.name,
                    tool_result.rank if tool_result else 0,
                    len(ranked_tools),
                    tool_result.relevance_score if tool_result else 0.0
                )
                return ToolPreInvokeResult(
                    continue_processing=True,
                    metadata={
                        "crt_router_rank": tool_result.rank if tool_result else 0,
                        "crt_router_relevance": tool_result.relevance_score if tool_result else 0.0,
                        "crt_router_total_tools": len(ranked_tools)
                    }
                )
            else:
                # Tool not in top-k or below threshold - block invocation
                logger.warning(
                    "CRT router blocked tool '%s' - not in top-%d relevant tools (threshold %.3f)",
                    payload.name,
                    self._cfg.default_k,
                    self._cfg.default_threshold
                )
                return ToolPreInvokeResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Tool not relevant for query",
                        description=f"Tool '{payload.name}' is not in the top-{self._cfg.default_k} "
                                  f"relevant tools for the query. CRT router suggests: "
                                  f"{', '.join(tool_names[:3])}",
                        code="CRT_ROUTER_TOOL_NOT_RELEVANT",
                        details={
                            "invoked_tool": payload.name,
                            "suggested_tools": tool_names[:3],
                            "top_k": self._cfg.default_k,
                            "threshold": self._cfg.default_threshold
                        }
                    )
                )
                
        except Exception as e:
            # Log error but allow invocation to proceed (fail-safe behavior)
            logger.error(
                "CRT router error during tool evaluation for '%s': %s - allowing invocation",
                payload.name,
                str(e),
                exc_info=True
            )
            return ToolPreInvokeResult(continue_processing=True)
