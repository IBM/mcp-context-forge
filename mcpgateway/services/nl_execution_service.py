# -*- coding: utf-8 -*-
"""Natural language execution service.

Provides intent classification, tool matching, slot filling, confirmation,
execution, and response formatting for NL tool requests.
"""

# Standard
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import re
import uuid
from typing import Any, Dict, Iterable, List, Optional

# Third-Party
import orjson
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
import jsonschema

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Tool as DbTool
from mcpgateway.llm_schemas import ChatCompletionRequest, ChatMessage
from mcpgateway.services.llm_proxy_service import LLMProxyService
from mcpgateway.services.semantic_search_service import get_semantic_search_service
from mcpgateway.services.tool_service import ToolService
from mcpgateway.utils.redis_client import get_redis_client

logger = logging.getLogger(__name__)


@dataclass
class IntentClassification:
    intent: str
    confidence: float
    domain: Optional[str]
    requires_tool: bool


@dataclass
class ToolCandidate:
    name: str
    description: Optional[str]
    input_schema: Dict[str, Any]
    visibility: str
    team_id: Optional[str] = None
    owner_email: Optional[str] = None
    server_id: Optional[str] = None
    server_name: Optional[str] = None
    annotations: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


@dataclass
class ToolMatch:
    tool: ToolCandidate
    confidence: float
    reasoning: Optional[str]
    is_primary: bool


@dataclass
class SlotFillingResult:
    parameters: Dict[str, Any]
    missing_required: List[str]
    inferred_params: Dict[str, str]
    validation_errors: List[str]
    confidence: float
    needs_clarification: bool


class ConversationContextManager:
    """Store and retrieve NL conversation context."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._memory_store: Dict[str, Dict[str, Any]] = {}

    async def get_context(self, session_id: str) -> Dict[str, Any]:
        redis = await get_redis_client()
        if redis:
            raw = await redis.get(self._redis_key(session_id))
            if raw:
                return json.loads(raw)
        return self._memory_store.get(session_id) or self._default_context(session_id)

    async def save_context(self, context: Dict[str, Any]) -> None:
        session_id = context["session_id"]
        payload = json.dumps(context)
        redis = await get_redis_client()
        if redis:
            await redis.set(self._redis_key(session_id), payload, ex=self._ttl_seconds)
        else:
            self._memory_store[session_id] = context

    async def clear_context(self, session_id: str) -> None:
        redis = await get_redis_client()
        if redis:
            await redis.delete(self._redis_key(session_id))
        self._memory_store.pop(session_id, None)

    def _redis_key(self, session_id: str) -> str:
        return f"nl:context:{session_id}"

    def _default_context(self, session_id: str) -> Dict[str, Any]:
        return {
            "session_id": session_id,
            "messages": [],
            "extracted_entities": {},
            "pending_execution": None,
            "clarification_rounds": 0,
        }


class ExecutionSafeguard:
    """Safety checks for NL execution."""

    CONFIRM_ALWAYS = ["delete-*", "deploy-*", "payment-*"]

    def __init__(self) -> None:
        self._sensitive_patterns = [re.compile(pat, re.IGNORECASE) for pat in settings.nl_execution_sensitive_param_patterns]

    def requires_confirmation(self, tool: ToolCandidate, params: Dict[str, Any]) -> Dict[str, Any]:
        reasons: List[str] = []
        risk_level = self._get_risk_level(tool)
        if settings.nl_execution_confirm_high_risk and risk_level in {"high", "critical"}:
            reasons.append(f"Tool '{tool.name}' has {risk_level} risk level")

        if settings.nl_execution_confirm_destructive:
            for pattern in self.CONFIRM_ALWAYS:
                if self._matches_pattern(tool.name, pattern):
                    reasons.append(f"Tool matches sensitive pattern '{pattern}'")

        for param_name, value in params.items():
            for pattern in self._sensitive_patterns:
                if pattern.search(param_name) or pattern.search(str(value)):
                    reasons.append(f"Parameter '{param_name}' contains sensitive data")
                    break

        return {
            "required": bool(reasons),
            "reasons": reasons,
            "confirmation_type": "explicit" if len(reasons) > 1 else "quick",
        }

    def mask_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        masked = {}
        for key, value in params.items():
            if self._is_sensitive_key(key) or self._is_sensitive_value(value):
                masked[key] = settings.masked_auth_value
            else:
                masked[key] = value
        return masked

    def _matches_pattern(self, value: str, pattern: str) -> bool:
        return re.fullmatch(pattern.replace("*", ".*"), value) is not None

    def _is_sensitive_key(self, key: str) -> bool:
        return any(pattern.search(key) for pattern in self._sensitive_patterns)

    def _is_sensitive_value(self, value: Any) -> bool:
        return any(pattern.search(str(value)) for pattern in self._sensitive_patterns)

    def _get_risk_level(self, tool: ToolCandidate) -> str:
        annotations = tool.annotations or {}
        if isinstance(annotations, dict):
            risk = annotations.get("risk_level") or annotations.get("risk")
            if isinstance(risk, str):
                return risk.lower()
        return "unknown"


class NLLMClient:
    """Lightweight LLM client for NL execution workflows."""

    def __init__(self, llm_proxy_service: LLMProxyService) -> None:
        self._llm_proxy_service = llm_proxy_service

    async def generate_text(
        self,
        db: Session,
        model: str,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system: Optional[str] = None,
    ) -> str:
        await self._llm_proxy_service.initialize()
        messages = []
        if system:
            messages.append(ChatMessage(role="system", content=system))
        messages.append(ChatMessage(role="user", content=prompt))
        request = ChatCompletionRequest(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
        response = await self._llm_proxy_service.chat_completion(db, request)
        if not response.choices:
            return ""
        return response.choices[0].message.content or ""

    async def generate_json(
        self,
        db: Session,
        model: str,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system: Optional[str] = None,
    ) -> Dict[str, Any]:
        text = await self.generate_text(db, model, prompt, temperature, max_tokens, system)
        parsed = self._parse_json(text)
        if parsed is not None:
            return parsed
        return {}

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        try:
            return orjson.loads(text)
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return orjson.loads(match.group(0))
            except Exception:
                return None
        return None


class NLExecutionService:
    """Orchestrates natural language tool execution."""

    def __init__(self) -> None:
        self._tool_service = ToolService()
        self._semantic_search = get_semantic_search_service()
        self._llm_proxy_service = LLMProxyService()
        self._llm = NLLMClient(self._llm_proxy_service)
        self._context_manager = ConversationContextManager(settings.nl_execution_context_ttl)
        self._safeguard = ExecutionSafeguard()

    async def execute(
        self,
        query: str,
        db: Session,
        user_ctx: Dict[str, Any],
        request_headers: Optional[Dict[str, str]],
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        include_follow_ups: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        session_id = session_id or uuid.uuid4().hex
        context = await self._context_manager.get_context(session_id)
        intent = await self._classify_intent(query, context, db, model, temperature, max_tokens)

        if context.get("pending_execution"):
            return await self._continue_pending_execution(
                query=query,
                db=db,
                user_ctx=user_ctx,
                request_headers=request_headers,
                session_id=session_id,
                context=context,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                include_follow_ups=include_follow_ups,
                dry_run=dry_run,
            )

        if not intent.requires_tool:
            response_text = await self._handle_non_tool_query(query, intent, db, model, temperature, max_tokens)
            result = self._build_response(
                session_id=session_id,
                response=response_text,
                response_type="no_tool_needed",
                intent=intent,
            )
            await self._update_context(query, result, context)
            return result

        matches = await self._match_tools(query, intent, db, user_ctx)
        if not matches or matches[0].confidence < settings.nl_execution_min_confidence:
            response_text = "I couldn't find a tool to help with that. Could you be more specific?"
            result = self._build_response(
                session_id=session_id,
                response=response_text,
                response_type="no_match",
                intent=intent,
                alternatives=self._format_alternatives(matches),
            )
            await self._update_context(query, result, context)
            return result

        best_match = matches[0]
        if not await self._can_execute_tool(db, best_match.tool, user_ctx):
            response_text = f"You don't have permission to use {best_match.tool.name}."
            result = self._build_response(
                session_id=session_id,
                response=response_text,
                response_type="permission_denied",
                intent=intent,
                tool_used=best_match.tool.name,
            )
            await self._update_context(query, result, context)
            return result

        slots = await self._fill_slots(query, best_match.tool, context, db, model, temperature, max_tokens)
        if slots.needs_clarification:
            clarification = await self._generate_clarification(best_match.tool, slots.missing_required, db, model, temperature, max_tokens)
            context["pending_execution"] = {
                "tool": best_match.tool.name,
                "params": slots.parameters,
                "missing": slots.missing_required,
            }
            context["clarification_rounds"] = context.get("clarification_rounds", 0) + 1
            await self._context_manager.save_context(context)
            return self._build_response(
                session_id=session_id,
                response=clarification,
                response_type="clarification_needed",
                intent=intent,
                pending_tool=best_match.tool.name,
                partial_params=slots.parameters,
                alternatives=self._format_alternatives(matches),
            )

        confirmation = self._safeguard.requires_confirmation(best_match.tool, slots.parameters)
        if confirmation["required"]:
            masked_params = self._safeguard.mask_params(slots.parameters)
            context["pending_execution"] = {
                "tool": best_match.tool.name,
                "params": slots.parameters,
                "missing": [],
                "confirmation": confirmation,
            }
            await self._context_manager.save_context(context)
            response_text = self._format_confirmation(best_match.tool, masked_params, confirmation)
            return self._build_response(
                session_id=session_id,
                response=response_text,
                response_type="confirmation_needed",
                intent=intent,
                pending_tool=best_match.tool.name,
                partial_params=masked_params,
            )

        if dry_run:
            response_text = "I can run this tool when you're ready."
            result = self._build_response(
                session_id=session_id,
                response=response_text,
                response_type="ready",
                intent=intent,
                tool_used=best_match.tool.name,
                parameters=slots.parameters,
            )
            await self._update_context(query, result, context)
            return result

        try:
            tool_result = await self._invoke_tool(db, best_match.tool, slots.parameters, user_ctx, request_headers)
        except Exception as exc:
            result = self._build_response(
                session_id=session_id,
                response=f"Tool execution failed: {exc}",
                response_type="error",
                intent=intent,
                tool_used=best_match.tool.name,
            )
            await self._update_context(query, result, context)
            return result

        response_text, follow_ups = await self._format_response_with_followups(
            query,
            best_match.tool,
            tool_result,
            db,
            model,
            temperature,
            max_tokens,
            include_follow_ups,
        )
        result = self._build_response(
            session_id=session_id,
            response=response_text,
            response_type="success",
            intent=intent,
            tool_used=best_match.tool.name,
            parameters=slots.parameters,
            raw_result=tool_result,
            follow_ups=follow_ups,
        )
        await self._update_context(query, result, context)
        return result

    async def parse(
        self,
        query: str,
        db: Session,
        user_ctx: Dict[str, Any],
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        session_id = session_id or uuid.uuid4().hex
        context = await self._context_manager.get_context(session_id)
        intent = await self._classify_intent(query, context, db, model, temperature, max_tokens)
        matches = await self._match_tools(query, intent, db, user_ctx) if intent.requires_tool else []
        slots = None
        if matches:
            slots = await self._fill_slots(query, matches[0].tool, context, db, model, temperature, max_tokens)
        result = {
            "session_id": session_id,
            "intent": self._intent_to_dict(intent),
            "matches": [self._match_to_dict(m) for m in matches],
            "slot_filling": self._slot_to_dict(slots) if slots else None,
        }
        await self._update_context(query, {"response": "", "tool_used": None}, context, store_response=False)
        return result

    async def confirm(
        self,
        session_id: str,
        db: Session,
        user_ctx: Dict[str, Any],
        request_headers: Optional[Dict[str, str]],
        confirm: bool,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        context = await self._context_manager.get_context(session_id)
        pending = context.get("pending_execution")
        if not pending:
            return self._build_response(session_id=session_id, response="No pending execution to confirm.", response_type="no_pending")

        if not confirm:
            context["pending_execution"] = None
            await self._context_manager.save_context(context)
            return self._build_response(session_id=session_id, response="Okay, cancelled.", response_type="cancelled")

        tool = await self._load_tool_candidate(db, pending.get("tool"), user_ctx)
        if tool is None:
            context["pending_execution"] = None
            await self._context_manager.save_context(context)
            return self._build_response(session_id=session_id, response="I couldn't find that tool anymore.", response_type="no_match")

        if not await self._can_execute_tool(db, tool, user_ctx):
            context["pending_execution"] = None
            await self._context_manager.save_context(context)
            return self._build_response(session_id=session_id, response=f"You don't have permission to use {tool.name}.", response_type="permission_denied")

        try:
            tool_result = await self._invoke_tool(db, tool, pending.get("params") or {}, user_ctx, request_headers)
        except Exception as exc:
            context["pending_execution"] = None
            await self._context_manager.save_context(context)
            return self._build_response(
                session_id=session_id,
                response=f"Tool execution failed: {exc}",
                response_type="error",
                tool_used=tool.name,
            )

        response_text, follow_ups = await self._format_response_with_followups("", tool, tool_result, db, model, temperature, max_tokens, True)
        result = self._build_response(
            session_id=session_id,
            response=response_text,
            response_type="success",
            tool_used=tool.name,
            parameters=pending.get("params") or {},
            raw_result=tool_result,
            follow_ups=follow_ups,
        )
        context["pending_execution"] = None
        await self._update_context("", result, context)
        return result

    async def get_context(self, session_id: str) -> Dict[str, Any]:
        return await self._context_manager.get_context(session_id)

    async def clear_context(self, session_id: str) -> None:
        await self._context_manager.clear_context(session_id)

    async def submit_feedback(self, session_id: Optional[str], feedback: Dict[str, Any]) -> None:
        logger.info("NL feedback received for session %s", session_id or "unknown")
        logger.debug("NL feedback payload keys: %s", list(feedback.keys()))

    async def _classify_intent(
        self,
        query: str,
        context: Dict[str, Any],
        db: Session,
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> IntentClassification:
        prompt = self._intent_prompt(query, context)
        result = await self._llm.generate_json(
            db,
            self._resolve_model(model),
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        intent = (result.get("intent") or "question").strip()
        confidence = float(result.get("confidence") or 0.0)
        domain = result.get("domain")
        requires_tool = intent in {"tool_execution", "workflow_execution"}
        return IntentClassification(intent=intent, confidence=confidence, domain=domain, requires_tool=requires_tool)

    async def _match_tools(
        self,
        query: str,
        intent: IntentClassification,
        db: Session,
        user_ctx: Dict[str, Any],
    ) -> List[ToolMatch]:
        semantic_results = await self._semantic_search.search_tools(
            query=query,
            limit=settings.nl_execution_max_tool_candidates,
            threshold=settings.nl_execution_semantic_threshold,
            db=db,
        )
        keyword_results = await self._keyword_search(query, db, settings.nl_execution_max_tool_candidates)
        candidates = self._merge_search_results(semantic_results, keyword_results)
        tool_candidates = await self._filter_accessible_candidates(candidates, db, user_ctx)

        if intent.domain:
            tool_candidates = [t for t in tool_candidates if self._matches_domain(t, intent.domain)]

        tool_candidates = tool_candidates[: settings.nl_execution_max_tool_candidates]
        if not tool_candidates:
            return []

        prompt = self._tool_match_prompt(query, intent, tool_candidates)
        result = await self._llm.generate_json(
            db,
            self._resolve_model(None),
            prompt,
            temperature=settings.nl_execution_temperature,
            max_tokens=settings.nl_execution_max_tokens,
        )
        selected = result.get("selected_tool")
        alternatives = result.get("alternatives") or []

        matches: List[ToolMatch] = []
        tool_by_name = {t.name: t for t in tool_candidates}

        if selected in tool_by_name:
            matches.append(
                ToolMatch(
                    tool=tool_by_name[selected],
                    confidence=float(result.get("confidence") or 0.0),
                    reasoning=result.get("reasoning"),
                    is_primary=True,
                )
            )

        for alt in alternatives:
            if alt in tool_by_name and alt != selected:
                matches.append(ToolMatch(tool=tool_by_name[alt], confidence=0.5, reasoning=None, is_primary=False))

        if not matches:
            matches = [ToolMatch(tool=t, confidence=0.4, reasoning=None, is_primary=(i == 0)) for i, t in enumerate(tool_candidates)]

        return matches

    async def _fill_slots(
        self,
        query: str,
        tool: ToolCandidate,
        context: Dict[str, Any],
        db: Session,
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> SlotFillingResult:
        prompt = self._slot_prompt(query, tool, context)
        result = await self._llm.generate_json(
            db,
            self._resolve_model(model),
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        parameters = result.get("parameters") or {}
        missing_required = result.get("missing_required") or []
        inferred = result.get("inferred") or {}
        confidence = float(result.get("confidence") or 0.0)

        validated_params, errors = self._validate_parameters(parameters, tool.input_schema)
        required = set(tool.input_schema.get("required") or [])
        missing = [param for param in required if param not in validated_params]
        missing = list(dict.fromkeys(missing_required + missing))

        return SlotFillingResult(
            parameters=validated_params,
            missing_required=missing,
            inferred_params=inferred,
            validation_errors=errors,
            confidence=confidence,
            needs_clarification=bool(missing),
        )

    async def _generate_clarification(
        self,
        tool: ToolCandidate,
        missing_params: List[str],
        db: Session,
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        prompt = self._clarification_prompt(tool, missing_params)
        return await self._llm.generate_text(
            db,
            self._resolve_model(model),
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def _handle_non_tool_query(
        self,
        query: str,
        intent: IntentClassification,
        db: Session,
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        prompt = (
            "Answer the user's question conversationally.\n"
            f"Query: \"{query}\"\n"
            f"Intent: {intent.intent}\n"
        )
        return await self._llm.generate_text(db, self._resolve_model(model), prompt, temperature=temperature, max_tokens=max_tokens)

    async def _invoke_tool(
        self,
        db: Session,
        tool: ToolCandidate,
        params: Dict[str, Any],
        user_ctx: Dict[str, Any],
        request_headers: Optional[Dict[str, str]],
    ) -> Dict[str, Any]:
        tool_result = await self._tool_service.invoke_tool(
            db=db,
            name=tool.name,
            arguments=params,
            request_headers=request_headers,
            user_email=user_ctx.get("email"),
            token_teams=user_ctx.get("teams"),
            meta_data={"nl_query": True},
        )
        return self._tool_result_to_dict(tool_result)

    async def _format_response_with_followups(
        self,
        query: str,
        tool: ToolCandidate,
        tool_result: Dict[str, Any],
        db: Session,
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        include_follow_ups: Optional[bool],
    ) -> tuple[str, List[Dict[str, str]]]:
        response_text = await self._format_response(query, tool, tool_result, db, model, temperature, max_tokens)
        follow_ups: List[Dict[str, str]] = []
        if include_follow_ups if include_follow_ups is not None else settings.nl_execution_followups_enabled:
            follow_ups = await self._generate_followups(query, tool_result, db, model, temperature, max_tokens)
        return response_text, follow_ups[: settings.nl_execution_max_followups]

    async def _format_response(
        self,
        query: str,
        tool: ToolCandidate,
        tool_result: Dict[str, Any],
        db: Session,
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        prompt = (
            "Format this tool result as a natural language response.\n\n"
            f"Original query: \"{query}\"\n"
            f"Tool used: {tool.name}\n"
            f"Result:\n{json.dumps(tool_result, indent=2)}\n\n"
            "Requirements:\n"
            "1. Respond conversationally, answering the original query\n"
            "2. Include key information from the result\n"
            "3. Be concise but complete\n"
            "4. Don't mention the tool unless relevant\n"
            "5. If result is an error, explain what went wrong\n"
        )
        return await self._llm.generate_text(db, self._resolve_model(model), prompt, temperature=temperature, max_tokens=max_tokens)

    async def _generate_followups(
        self,
        query: str,
        tool_result: Dict[str, Any],
        db: Session,
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> List[Dict[str, str]]:
        prompt = (
            "Suggest 2-3 natural follow-up actions based on this interaction.\n"
            f"Query: \"{query}\"\n"
            f"Result summary: {tool_result.get('summary') or tool_result}\n"
            "Return JSON: {\"follow_ups\": [{\"text\": \"...\", \"tool_hint\": \"tool_id\"}]}"
        )
        result = await self._llm.generate_json(db, self._resolve_model(model), prompt, temperature=temperature, max_tokens=max_tokens)
        follow_ups = result.get("follow_ups") or []
        return [f for f in follow_ups if isinstance(f, dict) and f.get("text")]

    async def _continue_pending_execution(
        self,
        query: str,
        db: Session,
        user_ctx: Dict[str, Any],
        request_headers: Optional[Dict[str, str]],
        session_id: str,
        context: Dict[str, Any],
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        include_follow_ups: Optional[bool],
        dry_run: bool,
    ) -> Dict[str, Any]:
        pending = context.get("pending_execution") or {}
        tool = await self._load_tool_candidate(db, pending.get("tool"), user_ctx)
        if not tool:
            context["pending_execution"] = None
            await self._context_manager.save_context(context)
            return self._build_response(session_id=session_id, response="I couldn't find that tool anymore.", response_type="no_match")

        slots = await self._fill_slots(query, tool, context, db, model, temperature, max_tokens)
        combined_params = {**(pending.get("params") or {}), **slots.parameters}
        missing = [m for m in pending.get("missing") or [] if m not in combined_params]
        for item in slots.missing_required:
            if item not in missing and item not in combined_params:
                missing.append(item)

        if missing and context.get("clarification_rounds", 0) < settings.nl_execution_max_clarification_rounds:
            clarification = await self._generate_clarification(tool, missing, db, model, temperature, max_tokens)
            context["pending_execution"] = {"tool": tool.name, "params": combined_params, "missing": missing}
            context["clarification_rounds"] = context.get("clarification_rounds", 0) + 1
            await self._context_manager.save_context(context)
            return self._build_response(
                session_id=session_id,
                response=clarification,
                response_type="clarification_needed",
                pending_tool=tool.name,
                partial_params=combined_params,
            )

        confirmation = self._safeguard.requires_confirmation(tool, combined_params)
        if confirmation["required"]:
            masked_params = self._safeguard.mask_params(combined_params)
            context["pending_execution"] = {
                "tool": tool.name,
                "params": combined_params,
                "missing": [],
                "confirmation": confirmation,
            }
            await self._context_manager.save_context(context)
            response_text = self._format_confirmation(tool, masked_params, confirmation)
            return self._build_response(
                session_id=session_id,
                response=response_text,
                response_type="confirmation_needed",
                pending_tool=tool.name,
                partial_params=masked_params,
            )

        context["pending_execution"] = None
        context["clarification_rounds"] = 0
        await self._context_manager.save_context(context)

        if dry_run:
            return self._build_response(
                session_id=session_id,
                response="I can run this tool when you're ready.",
                response_type="ready",
                tool_used=tool.name,
                parameters=combined_params,
            )

        try:
            tool_result = await self._invoke_tool(db, tool, combined_params, user_ctx, request_headers)
        except Exception as exc:
            result = self._build_response(
                session_id=session_id,
                response=f"Tool execution failed: {exc}",
                response_type="error",
                tool_used=tool.name,
            )
            await self._update_context(query, result, context)
            return result

        response_text, follow_ups = await self._format_response_with_followups(
            query,
            tool,
            tool_result,
            db,
            model,
            temperature,
            max_tokens,
            include_follow_ups,
        )
        result = self._build_response(
            session_id=session_id,
            response=response_text,
            response_type="success",
            tool_used=tool.name,
            parameters=combined_params,
            raw_result=tool_result,
            follow_ups=follow_ups,
        )
        await self._update_context(query, result, context)
        return result

    async def _keyword_search(self, query: str, db: Session, limit: int) -> List[Dict[str, Any]]:
        if not query.strip():
            return []
        pattern = f"%{query}%"
        rows = (
            db.execute(
                select(DbTool).where(
                    DbTool.enabled.is_(True),
                    or_(DbTool.name.ilike(pattern), DbTool.description.ilike(pattern), DbTool.original_description.ilike(pattern)),
                )
            )
            .scalars()
            .all()
        )
        results = []
        for tool in rows[:limit]:
            results.append(
                {
                    "tool_name": tool.name,
                    "description": tool.description,
                    "server_id": tool.gateway_id,
                    "server_name": tool.gateway.name if tool.gateway else None,
                    "similarity_score": 0.35,
                }
            )
        return results

    def _merge_search_results(
        self,
        semantic_results: Iterable[Any],
        keyword_results: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        for result in list(semantic_results) + list(keyword_results):
            tool_name = result.tool_name if hasattr(result, "tool_name") else result.get("tool_name")
            if not tool_name:
                continue
            score = result.similarity_score if hasattr(result, "similarity_score") else result.get("similarity_score", 0.0)
            entry = merged.get(tool_name)
            if not entry or score > entry["similarity_score"]:
                merged[tool_name] = {
                    "tool_name": tool_name,
                    "description": result.description if hasattr(result, "description") else result.get("description"),
                    "server_id": result.server_id if hasattr(result, "server_id") else result.get("server_id"),
                    "server_name": result.server_name if hasattr(result, "server_name") else result.get("server_name"),
                    "similarity_score": score,
                }
        return sorted(merged.values(), key=lambda r: r["similarity_score"], reverse=True)

    async def _filter_accessible_candidates(
        self,
        candidates: List[Dict[str, Any]],
        db: Session,
        user_ctx: Dict[str, Any],
    ) -> List[ToolCandidate]:
        if not candidates:
            return []
        names = [c["tool_name"] for c in candidates]
        tools = db.execute(select(DbTool).where(DbTool.name.in_(names), DbTool.enabled.is_(True))).scalars().all()
        results: List[ToolCandidate] = []
        for tool in tools:
            tool_payload = {
                "visibility": tool.visibility,
                "team_id": tool.team_id,
                "owner_email": tool.owner_email,
            }
            if not await self._tool_service._check_tool_access(db, tool_payload, user_ctx.get("email"), user_ctx.get("teams")):
                continue
            results.append(
                ToolCandidate(
                    name=tool.name,
                    description=tool.description or tool.original_description,
                    input_schema=tool.input_schema or {},
                    visibility=tool.visibility,
                    team_id=tool.team_id,
                    owner_email=tool.owner_email,
                    server_id=tool.gateway_id,
                    server_name=tool.gateway.name if tool.gateway else None,
                    annotations=tool.annotations or {},
                    tags=tool.tags or [],
                )
            )
        results.sort(key=lambda t: next((c["similarity_score"] for c in candidates if c["tool_name"] == t.name), 0.0), reverse=True)
        return results

    async def _load_tool_candidate(
        self,
        db: Session,
        tool_name: Optional[str],
        user_ctx: Dict[str, Any],
    ) -> Optional[ToolCandidate]:
        if not tool_name:
            return None
        tool = db.execute(select(DbTool).where(DbTool.name == tool_name, DbTool.enabled.is_(True))).scalar_one_or_none()
        if not tool:
            return None
        tool_payload = {"visibility": tool.visibility, "team_id": tool.team_id, "owner_email": tool.owner_email}
        if not await self._tool_service._check_tool_access(db, tool_payload, user_ctx.get("email"), user_ctx.get("teams")):
            return None
        return ToolCandidate(
            name=tool.name,
            description=tool.description or tool.original_description,
            input_schema=tool.input_schema or {},
            visibility=tool.visibility,
            team_id=tool.team_id,
            owner_email=tool.owner_email,
            server_id=tool.gateway_id,
            server_name=tool.gateway.name if tool.gateway else None,
            annotations=tool.annotations or {},
            tags=tool.tags or [],
        )

    async def _can_execute_tool(self, db: Session, tool: ToolCandidate, user_ctx: Dict[str, Any]) -> bool:
        tool_payload = {
            "visibility": tool.visibility,
            "team_id": tool.team_id,
            "owner_email": tool.owner_email,
        }
        return await self._tool_service._check_tool_access(db, tool_payload, user_ctx.get("email"), user_ctx.get("teams"))

    def _format_confirmation(self, tool: ToolCandidate, params: Dict[str, Any], confirmation: Dict[str, Any]) -> str:
        reasons = "; ".join(confirmation.get("reasons") or [])
        return (
            f"Before I run {tool.name}, please confirm. "
            f"Parameters: {json.dumps(params)}. "
            f"Reason: {reasons}."
        )

    def _tool_result_to_dict(self, tool_result: Any) -> Dict[str, Any]:
        content_text = self._tool_content_to_text(tool_result)
        return {
            "is_error": bool(getattr(tool_result, "isError", False)),
            "content": content_text,
            "summary": content_text,
        }

    def _tool_content_to_text(self, tool_result: Any) -> str:
        content = getattr(tool_result, "content", None)
        if not content:
            return ""
        if isinstance(content, list) and content:
            first = content[0]
            text = getattr(first, "text", None)
            if text is not None:
                return text
            return str(first)
        return str(content)

    def _slot_to_dict(self, slots: Optional[SlotFillingResult]) -> Optional[Dict[str, Any]]:
        if not slots:
            return None
        return {
            "parameters": slots.parameters,
            "missing_required": slots.missing_required,
            "inferred": slots.inferred_params,
            "validation_errors": slots.validation_errors,
            "confidence": slots.confidence,
        }

    def _intent_to_dict(self, intent: IntentClassification) -> Dict[str, Any]:
        return {
            "intent": intent.intent,
            "confidence": intent.confidence,
            "domain": intent.domain,
            "requires_tool": intent.requires_tool,
        }

    def _match_to_dict(self, match: ToolMatch) -> Dict[str, Any]:
        return {
            "tool": {
                "name": match.tool.name,
                "description": match.tool.description,
            },
            "confidence": match.confidence,
            "reasoning": match.reasoning,
            "is_primary": match.is_primary,
        }

    def _format_alternatives(self, matches: List[ToolMatch]) -> List[Dict[str, Any]]:
        alternatives = []
        for match in matches[1:]:
            alternatives.append({"tool_name": match.tool.name, "description": match.tool.description})
        return alternatives

    def _build_response(
        self,
        session_id: str,
        response: str,
        response_type: str,
        intent: Optional[IntentClassification] = None,
        tool_used: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        raw_result: Optional[Dict[str, Any]] = None,
        pending_tool: Optional[str] = None,
        partial_params: Optional[Dict[str, Any]] = None,
        alternatives: Optional[List[Dict[str, Any]]] = None,
        follow_ups: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        return {
            "session_id": session_id,
            "type": response_type,
            "response": response,
            "tool_used": tool_used,
            "parameters": parameters,
            "raw_result": raw_result,
            "pending_tool": pending_tool,
            "partial_params": partial_params,
            "alternatives": alternatives or [],
            "follow_ups": follow_ups or [],
            "intent": self._intent_to_dict(intent) if intent else None,
        }

    async def _update_context(self, query: str, result: Dict[str, Any], context: Dict[str, Any], store_response: bool = True) -> None:
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        if query:
            context["messages"].append({"role": "user", "content": query, "timestamp": timestamp})
        if store_response and result.get("response"):
            context["messages"].append(
                {
                    "role": "assistant",
                    "content": result.get("response"),
                    "timestamp": timestamp,
                    "tool_used": result.get("tool_used"),
                }
            )
        if result.get("parameters"):
            context["extracted_entities"].update(result.get("parameters") or {})
        context["messages"] = context["messages"][-settings.nl_execution_max_context_messages :]
        await self._context_manager.save_context(context)

    def _intent_prompt(self, query: str, context: Dict[str, Any]) -> str:
        recent = context.get("messages", [])[-5:]
        return (
            "Classify the user's intent from this query.\n\n"
            f"Query: \"{query}\"\n\n"
            f"Previous context: {recent}\n\n"
            "Possible intents:\n"
            "- tool_execution: User wants to run a specific tool/action\n"
            "- tool_discovery: User is looking for tools\n"
            "- workflow_execution: User wants to run multiple tools\n"
            "- question: User is asking a general question\n"
            "- clarification: User is responding to a clarification request\n\n"
            "Return JSON: {\"intent\": \"...\", \"confidence\": 0.0-1.0, \"domain\": \"...\"}"
        )

    def _tool_match_prompt(self, query: str, intent: IntentClassification, tools: List[ToolCandidate]) -> str:
        formatted = []
        for tool in tools:
            formatted.append(
                {
                    "tool_id": tool.name,
                    "description": tool.description,
                    "required_params": tool.input_schema.get("required") or [],
                    "properties": list((tool.input_schema.get("properties") or {}).keys()),
                }
            )
        return (
            "Select the best tool to fulfill this request.\n\n"
            f"User query: \"{query}\"\n"
            f"User intent: {intent.intent}\n\n"
            f"Available tools:\n{json.dumps(formatted, indent=2)}\n\n"
            "Consider:\n"
            "1. Does the tool's purpose match the query?\n"
            "2. Can the tool's parameters be filled from the query?\n"
            "3. Is the tool appropriate for this context?\n\n"
            "Return JSON: {\"selected_tool\": \"tool_id\", \"confidence\": 0.0-1.0, \"reasoning\": \"...\", \"alternatives\": [\"tool_id2\"]}"
        )

    def _slot_prompt(self, query: str, tool: ToolCandidate, context: Dict[str, Any]) -> str:
        schema = self._summarize_schema(tool.input_schema)
        entities = context.get("extracted_entities")
        return (
            "Extract parameters for the tool from the user's query.\n\n"
            f"Query: \"{query}\"\n\n"
            f"Tool: {tool.name}\n"
            f"Description: {tool.description}\n\n"
            f"Parameters:\n{schema}\n\n"
            f"Context from conversation:\n{entities}\n\n"
            "Rules:\n"
            "1. Only extract values explicitly mentioned or clearly implied\n"
            "2. Use context entities if directly relevant\n"
            f"3. {'Allow' if settings.nl_execution_allow_inference else 'Do not allow'} inferred values beyond the query and context\n"
            "4. Mark required params without values as \"missing\"\n"
            "5. Convert natural language to appropriate types\n\n"
            "Return JSON: {\"parameters\": {\"param_name\": \"value\"}, "
            "\"missing_required\": [\"param_name\"], "
            "\"inferred\": {\"param_name\": \"reason\"}, "
            "\"confidence\": 0.0-1.0}"
        )

    def _clarification_prompt(self, tool: ToolCandidate, missing_params: List[str]) -> str:
        param_desc = {}
        props = tool.input_schema.get("properties") or {}
        for name in missing_params:
            if name in props:
                param_desc[name] = props[name]
        return (
            "Generate a natural clarification question to get missing information.\n\n"
            f"Tool: {tool.name}\n"
            f"Missing parameters: {json.dumps(param_desc, indent=2)}\n\n"
            "The question should be:\n"
            "1. Conversational and friendly\n"
            "2. Ask for all missing info in one question if possible\n"
            "3. Provide examples if helpful\n\n"
            "Return: A single clarifying question string"
        )

    def _summarize_schema(self, schema: Dict[str, Any]) -> str:
        if not schema:
            return "{}"
        properties = schema.get("properties") or {}
        summary = {}
        for key, value in properties.items():
            summary[key] = {
                "type": value.get("type"),
                "description": value.get("description"),
            }
        return json.dumps({"required": schema.get("required") or [], "properties": summary}, indent=2)

    def _validate_parameters(self, params: Dict[str, Any], schema: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
        if not schema:
            return params, []
        allowed = set((schema.get("properties") or {}).keys())
        filtered = {k: v for k, v in params.items() if k in allowed}
        errors = []
        try:
            jsonschema.Draft7Validator(schema).validate(filtered)
        except jsonschema.ValidationError as exc:
            errors.append(exc.message)
        return filtered, errors

    def _matches_domain(self, tool: ToolCandidate, domain: str) -> bool:
        domain_lower = domain.lower()
        if tool.description and domain_lower in tool.description.lower():
            return True
        if tool.tags and any(domain_lower in str(tag).lower() for tag in tool.tags):
            return True
        return domain_lower in tool.name.lower()

    def _resolve_model(self, override: Optional[str]) -> str:
        return override or settings.nl_execution_model
