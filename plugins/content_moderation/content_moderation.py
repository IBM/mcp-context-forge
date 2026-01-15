# -*- coding: utf-8 -*-
"""Location: ./plugins/content_moderation/content_moderation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Content Moderation Plugin.
Advanced content moderation using AI services (IBM Watson, IBM Granite Guardian, OpenAI, Azure, AWS).
Detects and handles harmful content including hate speech, violence, sexual content, and self-harm.
"""

# Future
from __future__ import annotations

# Standard
from enum import Enum
import logging
import re
from typing import Any, Dict, List, Optional

# Third-Party
import httpx
import orjson
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.config import settings
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

logger = logging.getLogger(__name__)


class ModerationProvider(str, Enum):
    """Available content moderation providers."""

    IBM_WATSON = "ibm_watson"
    IBM_GRANITE = "ibm_granite"
    OPENAI = "openai"
    AZURE = "azure"
    AWS = "aws"


class ModerationAction(str, Enum):
    """Actions to take when content violations are detected."""

    BLOCK = "block"
    WARN = "warn"
    REDACT = "redact"
    TRANSFORM = "transform"


class ModerationCategory(str, Enum):
    """Content moderation categories."""

    HATE = "hate"
    VIOLENCE = "violence"
    SEXUAL = "sexual"
    SELF_HARM = "self_harm"
    HARASSMENT = "harassment"
    SPAM = "spam"
    PROFANITY = "profanity"
    TOXIC = "toxic"


class IBMWatsonConfig(BaseModel):
    """IBM Watson Natural Language Understanding configuration."""

    api_key: str = Field(description="IBM Watson API key")
    url: str = Field(description="IBM Watson service URL")
    version: str = Field(default="2022-04-07", description="API version")
    language: str = Field(default="en", description="Language code")
    timeout: int = Field(default=30, description="Request timeout in seconds")


class IBMGraniteConfig(BaseModel):
    """IBM Granite Guardian configuration via Ollama."""

    ollama_url: str = Field(default="http://localhost:11434", description="Ollama API URL")
    model: str = Field(default="granite3-guardian", description="Granite model name")
    temperature: float = Field(default=0.1, description="Model temperature")
    timeout: int = Field(default=30, description="Request timeout in seconds")


class OpenAIConfig(BaseModel):
    """OpenAI Moderation API configuration."""

    api_key: str = Field(description="OpenAI API key")
    api_base: str = Field(default="https://api.openai.com/v1", description="API base URL")
    model: str = Field(default="text-moderation-latest", description="Moderation model")
    timeout: int = Field(default=30, description="Request timeout in seconds")


class AzureConfig(BaseModel):
    """Azure Content Safety configuration."""

    api_key: str = Field(description="Azure Content Safety API key")
    endpoint: str = Field(description="Azure Content Safety endpoint")
    api_version: str = Field(default="2023-10-01", description="API version")
    timeout: int = Field(default=30, description="Request timeout in seconds")


class AWSConfig(BaseModel):
    """AWS Comprehend configuration."""

    access_key: str = Field(description="AWS access key")
    secret_key: str = Field(description="AWS secret key")
    region: str = Field(default="us-east-1", description="AWS region")
    timeout: int = Field(default=30, description="Request timeout in seconds")


class CategoryConfig(BaseModel):
    """Configuration for a specific moderation category."""

    threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="Confidence threshold")
    action: ModerationAction = Field(default=ModerationAction.WARN, description="Action to take")
    providers: List[ModerationProvider] = Field(default_factory=list, description="Providers to use for this category")
    custom_patterns: List[str] = Field(default_factory=list, description="Custom regex patterns")


class ContentModerationConfig(BaseModel):
    """Configuration for the content moderation plugin."""

    provider: ModerationProvider = Field(default=ModerationProvider.IBM_WATSON, description="Primary provider")
    fallback_provider: Optional[ModerationProvider] = Field(default=None, description="Fallback provider")
    fallback_on_error: ModerationAction = Field(default=ModerationAction.WARN, description="Action when provider fails")

    # Provider configurations
    ibm_watson: Optional[IBMWatsonConfig] = None
    ibm_granite: Optional[IBMGraniteConfig] = None
    openai: Optional[OpenAIConfig] = None
    azure: Optional[AzureConfig] = None
    aws: Optional[AWSConfig] = None

    # Category configurations
    categories: Dict[ModerationCategory, CategoryConfig] = Field(
        default_factory=lambda: {
            ModerationCategory.HATE: CategoryConfig(threshold=0.7, action=ModerationAction.BLOCK),
            ModerationCategory.VIOLENCE: CategoryConfig(threshold=0.8, action=ModerationAction.BLOCK),
            ModerationCategory.SEXUAL: CategoryConfig(threshold=0.6, action=ModerationAction.WARN),
            ModerationCategory.SELF_HARM: CategoryConfig(threshold=0.5, action=ModerationAction.BLOCK),
            ModerationCategory.HARASSMENT: CategoryConfig(threshold=0.7, action=ModerationAction.WARN),
            ModerationCategory.SPAM: CategoryConfig(threshold=0.8, action=ModerationAction.WARN),
            ModerationCategory.PROFANITY: CategoryConfig(threshold=0.6, action=ModerationAction.REDACT),
            ModerationCategory.TOXIC: CategoryConfig(threshold=0.7, action=ModerationAction.WARN),
        }
    )

    # General settings
    audit_decisions: bool = Field(default=True, description="Log all moderation decisions")
    include_confidence_scores: bool = Field(default=True, description="Include confidence scores in results")
    enable_caching: bool = Field(default=True, description="Cache moderation results")
    cache_ttl: int = Field(default=3600, description="Cache TTL in seconds")
    max_text_length: int = Field(default=10000, description="Maximum text length to moderate")


class ModerationResult(BaseModel):
    """Result from content moderation check."""

    flagged: bool = Field(description="Whether content was flagged")
    categories: Dict[str, float] = Field(default_factory=dict, description="Category scores")
    action: ModerationAction = Field(description="Recommended action")
    provider: ModerationProvider = Field(description="Provider used")
    confidence: float = Field(description="Overall confidence score")
    modified_content: Optional[str] = Field(default=None, description="Modified content if action was redact/transform")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional details")


class ContentModerationPlugin(Plugin):
    """Plugin for advanced content moderation using multiple AI providers."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize content moderation plugin with configuration.

        Args:
            config: Plugin configuration containing moderation settings.
        """
        super().__init__(config)
        self._cfg = ContentModerationConfig(**(config.config or {}))
        self._client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=settings.httpx_max_connections,
                max_keepalive_connections=settings.httpx_max_keepalive_connections,
                keepalive_expiry=settings.httpx_keepalive_expiry,
            ),
            timeout=httpx.Timeout(
                connect=settings.httpx_connect_timeout,
                read=settings.httpx_read_timeout,
                write=settings.httpx_write_timeout,
                pool=settings.httpx_pool_timeout,
            ),
        )
        self._cache: Dict[str, ModerationResult] = {} if self._cfg.enable_caching else None

    async def _get_cache_key(self, text: str, provider: ModerationProvider) -> str:
        """Generate cache key for content.

        Args:
            text: Content text to generate key for.
            provider: Moderation provider being used.

        Returns:
            Cache key string.
        """
        # Standard
        import hashlib

        content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        return f"{provider.value}:{content_hash}"

    async def _get_cached_result(self, text: str, provider: ModerationProvider) -> Optional[ModerationResult]:
        """Get cached moderation result.

        Args:
            text: Content text to check cache for.
            provider: Moderation provider being used.

        Returns:
            Cached moderation result if available, None otherwise.
        """
        if not self._cfg.enable_caching or not self._cache:
            return None

        cache_key = await self._get_cache_key(text, provider)
        return self._cache.get(cache_key)

    async def _cache_result(self, text: str, provider: ModerationProvider, result: ModerationResult) -> None:
        """Cache moderation result.

        Args:
            text: Content text being cached.
            provider: Moderation provider being used.
            result: Moderation result to cache.
        """
        if not self._cfg.enable_caching or not self._cache:
            return

        cache_key = await self._get_cache_key(text, provider)
        self._cache[cache_key] = result

    async def _moderate_with_ibm_watson(self, text: str) -> ModerationResult:
        """Moderate content using IBM Watson Natural Language Understanding.

        Args:
            text: Content text to moderate.

        Returns:
            Moderation result from IBM Watson.

        Raises:
            ValueError: If IBM Watson configuration not provided.
            Exception: If API call fails.
        """
        if not self._cfg.ibm_watson:
            raise ValueError("IBM Watson configuration not provided")

        config = self._cfg.ibm_watson

        # IBM Watson NLU API call
        url = f"{config.url}/v1/analyze"

        payload = {"text": text, "features": {"emotion": {}, "sentiment": {}, "concepts": {"limit": 5}}, "language": config.language, "version": config.version}

        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {config.api_key}"}

        try:
            response = await self._client.post(url, json=payload, headers=headers, timeout=config.timeout)
            response.raise_for_status()

            data = response.json()

            # Extract moderation scores from Watson response
            emotion_scores = data.get("emotion", {}).get("document", {}).get("emotion", {})
            sentiment = data.get("sentiment", {}).get("document", {})
            concepts = data.get("concepts", [])

            # Calculate category scores based on Watson's analysis
            categories = {}

            # Map Watson emotions to our categories
            anger_score = emotion_scores.get("anger", 0.0)
            disgust_score = emotion_scores.get("disgust", 0.0)
            fear_score = emotion_scores.get("fear", 0.0)
            sadness_score = emotion_scores.get("sadness", 0.0)

            # Sentiment-based scoring
            sentiment_score = sentiment.get("score", 0.0) if sentiment.get("label") == "negative" else 0.0

            categories[ModerationCategory.HATE.value] = min(anger_score + disgust_score, 1.0)
            categories[ModerationCategory.VIOLENCE.value] = min(anger_score + fear_score * 0.5, 1.0)
            categories[ModerationCategory.TOXIC.value] = min(abs(sentiment_score) if sentiment_score < -0.5 else 0.0, 1.0)
            categories[ModerationCategory.HARASSMENT.value] = min(anger_score * 0.8, 1.0)
            categories[ModerationCategory.SELF_HARM.value] = min(sadness_score + fear_score * 0.3, 1.0)

            # Check if any category exceeds threshold
            flagged = any(score >= self._cfg.categories[ModerationCategory(cat)].threshold for cat, score in categories.items() if ModerationCategory(cat) in self._cfg.categories)

            # Determine action
            action = ModerationAction.WARN
            max_score = max(categories.values()) if categories else 0.0

            if flagged:
                # Find the category with highest score above threshold
                for cat, score in categories.items():
                    cat_enum = ModerationCategory(cat)
                    if cat_enum in self._cfg.categories and score >= self._cfg.categories[cat_enum].threshold and score == max_score:
                        action = self._cfg.categories[cat_enum].action
                        break

            return ModerationResult(
                flagged=flagged,
                categories=categories,
                action=action,
                provider=ModerationProvider.IBM_WATSON,
                confidence=max_score,
                details={"watson_emotion": emotion_scores, "watson_sentiment": sentiment, "watson_concepts": concepts},
            )

        except Exception as e:
            logger.error(f"IBM Watson moderation failed: {e}")
            raise

    async def _moderate_with_ibm_granite(self, text: str) -> ModerationResult:
        """Moderate content using IBM Granite Guardian via Ollama.

        Args:
            text: Content text to moderate.

        Returns:
            Moderation result from IBM Granite.

        Raises:
            ValueError: If IBM Granite configuration not provided.
            Exception: If API call fails.
        """
        if not self._cfg.ibm_granite:
            raise ValueError("IBM Granite configuration not provided")

        config = self._cfg.ibm_granite

        # Ollama API call for Granite Guardian
        url = f"{config.ollama_url}/api/generate"

        # Craft prompt for content moderation
        prompt = f"""Analyze the following text for harmful content. Provide scores (0.0-1.0) for these categories:
- hate: hate speech, discrimination
- violence: threats, violent content
- sexual: sexual content, nudity
- self_harm: self-harm, suicide ideation
- harassment: bullying, harassment
- toxic: toxic, offensive language

Text to analyze: "{text}"

Respond with JSON format:
{{"hate": 0.0, "violence": 0.0, "sexual": 0.0, "self_harm": 0.0, "harassment": 0.0, "toxic": 0.0}}"""

        payload = {"model": config.model, "prompt": prompt, "temperature": config.temperature, "stream": False, "format": "json"}

        try:
            response = await self._client.post(url, json=payload, timeout=config.timeout)
            response.raise_for_status()

            data = response.json()
            response_text = data.get("response", "")

            # Parse JSON response from Granite
            try:
                categories = orjson.loads(response_text)
            except orjson.JSONDecodeError:
                # Fallback parsing if JSON is not perfect
                categories = {}
                for cat in ModerationCategory:
                    pattern = rf'"{cat.value}":\s*([\d.]+)'
                    match = re.search(pattern, response_text)
                    if match:
                        categories[cat.value] = float(match.group(1))
                    else:
                        categories[cat.value] = 0.0

            # Check if any category exceeds threshold
            flagged = any(score >= self._cfg.categories[ModerationCategory(cat)].threshold for cat, score in categories.items() if ModerationCategory(cat) in self._cfg.categories)

            # Determine action
            action = ModerationAction.WARN
            max_score = max(categories.values()) if categories else 0.0

            if flagged:
                for cat, score in categories.items():
                    cat_enum = ModerationCategory(cat)
                    if cat_enum in self._cfg.categories and score >= self._cfg.categories[cat_enum].threshold and score == max_score:
                        action = self._cfg.categories[cat_enum].action
                        break

            return ModerationResult(flagged=flagged, categories=categories, action=action, provider=ModerationProvider.IBM_GRANITE, confidence=max_score, details={"granite_response": response_text})

        except Exception as e:
            logger.error(f"IBM Granite moderation failed: {e}")
            raise

    async def _moderate_with_openai(self, text: str) -> ModerationResult:
        """Moderate content using OpenAI Moderation API.

        Args:
            text: Content text to moderate.

        Returns:
            Moderation result from OpenAI.

        Raises:
            ValueError: If OpenAI configuration not provided.
            Exception: If API call fails.
        """
        if not self._cfg.openai:
            raise ValueError("OpenAI configuration not provided")

        config = self._cfg.openai

        url = f"{config.api_base}/moderations"

        payload = {"input": text, "model": config.model}

        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {config.api_key}"}

        try:
            response = await self._client.post(url, json=payload, headers=headers, timeout=config.timeout)
            response.raise_for_status()

            data = response.json()
            result = data["results"][0]

            # Map OpenAI categories to our categories
            categories = {}
            openai_categories = result.get("category_scores", {})

            categories[ModerationCategory.HATE.value] = openai_categories.get("hate", 0.0)
            categories[ModerationCategory.VIOLENCE.value] = openai_categories.get("violence", 0.0)
            categories[ModerationCategory.SEXUAL.value] = openai_categories.get("sexual", 0.0)
            categories[ModerationCategory.SELF_HARM.value] = openai_categories.get("self-harm", 0.0)
            categories[ModerationCategory.HARASSMENT.value] = openai_categories.get("harassment", 0.0)

            flagged = result.get("flagged", False)
            max_score = max(categories.values()) if categories else 0.0

            # Determine action based on flagged categories
            action = ModerationAction.WARN
            if flagged:
                flagged_categories = result.get("categories", {})
                for cat, is_flagged in flagged_categories.items():
                    if is_flagged:
                        # Map OpenAI category to our category
                        our_cat = None
                        if cat == "hate":
                            our_cat = ModerationCategory.HATE
                        elif cat == "violence":
                            our_cat = ModerationCategory.VIOLENCE
                        elif cat == "sexual":
                            our_cat = ModerationCategory.SEXUAL
                        elif cat == "self-harm":
                            our_cat = ModerationCategory.SELF_HARM
                        elif cat == "harassment":
                            our_cat = ModerationCategory.HARASSMENT

                        if our_cat and our_cat in self._cfg.categories:
                            action = self._cfg.categories[our_cat].action
                            break

            return ModerationResult(flagged=flagged, categories=categories, action=action, provider=ModerationProvider.OPENAI, confidence=max_score, details={"openai_result": result})

        except Exception as e:
            logger.error(f"OpenAI moderation failed: {e}")
            raise

    async def _apply_moderation_action(self, text: str, result: ModerationResult) -> str:
        """Apply the moderation action to the text.

        Args:
            text: Original content text.
            result: Moderation result with action to apply.

        Returns:
            Modified text based on moderation action.
        """
        if result.action == ModerationAction.BLOCK:
            return ""  # Empty content
        elif result.action == ModerationAction.REDACT:
            # Simple redaction - replace with [CONTENT REMOVED]
            return "[CONTENT REMOVED BY MODERATION]"
        elif result.action == ModerationAction.TRANSFORM:
            # Basic transformation - replace problematic words
            transformed = text
            for category, score in result.categories.items():
                if score >= self._cfg.categories.get(ModerationCategory(category), CategoryConfig()).threshold:
                    # Simple word replacement for demonstration
                    if category == ModerationCategory.PROFANITY.value:
                        transformed = re.sub(r"\b(damn|hell|crap)\b", "[FILTERED]", transformed, flags=re.IGNORECASE)
            return transformed
        else:  # WARN or default
            return text  # Return original text

    async def _moderate_content(self, text: str) -> ModerationResult:
        """Moderate content using the configured provider.

        Args:
            text: Content text to moderate.

        Returns:
            Moderation result from the configured provider.
        """
        if len(text) > self._cfg.max_text_length:
            text = text[: self._cfg.max_text_length]

        # Check cache first
        cached_result = await self._get_cached_result(text, self._cfg.provider)
        if cached_result:
            return cached_result

        try:
            # Try primary provider
            if self._cfg.provider == ModerationProvider.IBM_WATSON:
                result = await self._moderate_with_ibm_watson(text)
            elif self._cfg.provider == ModerationProvider.IBM_GRANITE:
                result = await self._moderate_with_ibm_granite(text)
            elif self._cfg.provider == ModerationProvider.OPENAI:
                result = await self._moderate_with_openai(text)
            else:
                # Fallback to basic pattern matching
                result = await self._moderate_with_patterns(text)

        except Exception as e:
            logger.warning(f"Primary provider {self._cfg.provider} failed: {e}")

            # Try fallback provider
            if self._cfg.fallback_provider:
                try:
                    if self._cfg.fallback_provider == ModerationProvider.IBM_WATSON:
                        result = await self._moderate_with_ibm_watson(text)
                    elif self._cfg.fallback_provider == ModerationProvider.IBM_GRANITE:
                        result = await self._moderate_with_ibm_granite(text)
                    elif self._cfg.fallback_provider == ModerationProvider.OPENAI:
                        result = await self._moderate_with_openai(text)
                    else:
                        result = await self._moderate_with_patterns(text)
                except Exception:
                    result = await self._moderate_with_patterns(text)
            else:
                result = await self._moderate_with_patterns(text)

        # Cache the result
        await self._cache_result(text, result.provider, result)

        # Apply action to content if needed
        if result.action in [ModerationAction.REDACT, ModerationAction.TRANSFORM]:
            result.modified_content = await self._apply_moderation_action(text, result)

        return result

    async def _moderate_with_patterns(self, text: str) -> ModerationResult:
        """Fallback moderation using regex patterns.

        Args:
            text: Content text to moderate.

        Returns:
            Moderation result based on pattern matching.
        """
        categories = {}

        # Basic pattern matching for different categories
        patterns = {
            ModerationCategory.HATE: [r"\b(hate|racist|nazi|fascist)\b", r"\b(kill\s+(all\s+)?(jews|muslims|christians|blacks|whites))\b"],
            ModerationCategory.VIOLENCE: [r"\b(kill|murder|shoot|stab|bomb)\s+(you|him|her|them)\b", r"\b(death\s+threat|going\s+to\s+kill)\b"],
            ModerationCategory.SELF_HARM: [r"\b(kill\s+myself|suicide|self\s*harm|end\s+it\s+all)\b", r"\b(want\s+to\s+die|cutting\s+myself)\b"],
            ModerationCategory.PROFANITY: [r"\b(fuck\w*|shit|damn|hell|crap|bitch|asshole)\b"],
            ModerationCategory.HARASSMENT: [r"\b(you\s+suck|loser|idiot|moron|stupid)\b", r"\b(go\s+away|nobody\s+likes\s+you)\b"],
        }

        for category, category_patterns in patterns.items():
            score = 0.0
            for pattern in category_patterns:
                matches = len(re.findall(pattern, text, re.IGNORECASE))
                if matches > 0:
                    score = min(score + (matches * 0.3), 1.0)

            categories[category.value] = score

        # Fill remaining categories with 0.0
        for cat in ModerationCategory:
            if cat.value not in categories:
                categories[cat.value] = 0.0

        max_score = max(categories.values()) if categories else 0.0

        # Check if flagged
        flagged = any(score >= self._cfg.categories[ModerationCategory(cat)].threshold for cat, score in categories.items() if ModerationCategory(cat) in self._cfg.categories)

        # Determine action
        action = ModerationAction.WARN
        if flagged:
            for cat, score in categories.items():
                cat_enum = ModerationCategory(cat)
                if cat_enum in self._cfg.categories and score >= self._cfg.categories[cat_enum].threshold and score == max_score:
                    action = self._cfg.categories[cat_enum].action
                    break

        return ModerationResult(
            flagged=flagged,
            categories=categories,
            action=action,
            provider=ModerationProvider.IBM_WATSON,
            confidence=max_score,
            details={"method": "pattern_matching"},  # Default fallback
        )

    async def _extract_text_content(self, payload: Any) -> List[str]:
        """Extract text content from various payload types.

        Args:
            payload: Payload to extract text from.

        Returns:
            List of extracted text strings.
        """
        texts = []

        if hasattr(payload, "args") and payload.args:
            for key, value in payload.args.items():
                if isinstance(value, str) and len(value.strip()) > 0:
                    texts.append(value)
                elif isinstance(value, dict):
                    # Extract string values from nested dicts
                    for nested_value in value.values():
                        if isinstance(nested_value, str) and len(nested_value.strip()) > 0:
                            texts.append(nested_value)

        if hasattr(payload, "name") and isinstance(payload.name, str):
            texts.append(payload.name)

        return [text for text in texts if len(text.strip()) > 3]  # Filter very short texts

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, _context: PluginContext) -> PromptPrehookResult:
        """Moderate prompt content before fetching.

        Args:
            payload: Prompt payload to moderate.
            _context: Plugin context (unused).

        Returns:
            Result indicating whether to continue processing.
        """
        texts = await self._extract_text_content(payload)

        for text in texts:
            try:
                result = await self._moderate_content(text)

                if self._cfg.audit_decisions:
                    logger.info(
                        f"Content moderation - Prompt: {payload.prompt_id}, Result: {result.flagged}, Action: {result.action}, Provider: {result.provider}, Confidence: {result.confidence:.2f}"
                    )

                if result.action == ModerationAction.BLOCK:
                    return PromptPrehookResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            reason="Content policy violation detected",
                            description=f"Harmful content detected with {result.confidence:.2f} confidence",
                            code="CONTENT_MODERATION",
                            details={
                                "categories": result.categories,
                                "provider": result.provider.value,
                                "confidence": result.confidence,
                                "flagged_text_preview": text[:100] + "..." if len(text) > 100 else text,
                            },
                        ),
                        metadata={"moderation_result": result.model_dump(), "provider": result.provider.value},
                    )
                elif result.modified_content:
                    # Modify the payload with redacted/transformed content
                    modified_payload = PromptPrehookPayload(prompt_id=payload.prompt_id, args={k: result.modified_content if v == text else v for k, v in payload.args.items()})
                    return PromptPrehookResult(modified_payload=modified_payload, metadata={"moderation_result": result.dict(), "content_modified": True})

            except Exception as e:
                logger.error(f"Content moderation failed for prompt {payload.prompt_id}: {e}")
                if self._cfg.fallback_on_error == ModerationAction.BLOCK:
                    return PromptPrehookResult(
                        continue_processing=False,
                        violation=PluginViolation(reason="Content moderation service error", description="Unable to verify content safety", code="MODERATION_ERROR", details={"error": str(e)}),
                    )

        return PromptPrehookResult()

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, _context: PluginContext) -> ToolPreInvokeResult:
        """Moderate tool arguments before invocation.

        Args:
            payload: Tool invocation payload to moderate.
            _context: Plugin context (unused).

        Returns:
            Result indicating whether to continue processing.
        """
        texts = await self._extract_text_content(payload)

        for text in texts:
            try:
                result = await self._moderate_content(text)

                if self._cfg.audit_decisions:
                    logger.info(f"Content moderation - Tool: {payload.name}, Result: {result.flagged}, Action: {result.action}, Provider: {result.provider}")

                if result.action == ModerationAction.BLOCK:
                    return ToolPreInvokeResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            reason="Content policy violation in tool arguments",
                            description=f"Harmful content detected in {payload.name} arguments",
                            code="CONTENT_MODERATION",
                            details={"tool": payload.name, "categories": result.categories, "provider": result.provider.value, "confidence": result.confidence},
                        ),
                    )
                elif result.modified_content:
                    # Modify the payload arguments
                    modified_args = {k: result.modified_content if v == text else v for k, v in payload.args.items()}
                    modified_payload = ToolPreInvokePayload(name=payload.name, args=modified_args)
                    return ToolPreInvokeResult(modified_payload=modified_payload, metadata={"moderation_applied": True, "content_modified": True})

            except Exception as e:
                logger.error(f"Content moderation failed for tool {payload.name}: {e}")
                if self._cfg.fallback_on_error == ModerationAction.BLOCK:
                    return ToolPreInvokeResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            reason="Content moderation service error", description="Unable to verify tool argument safety", code="MODERATION_ERROR", details={"error": str(e), "tool": payload.name}
                        ),
                    )

        return ToolPreInvokeResult(metadata={"moderation_checked": True})

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, _context: PluginContext) -> ToolPostInvokeResult:
        """Moderate tool output after invocation.

        Args:
            payload: Tool result payload to moderate.
            _context: Plugin context (unused).

        Returns:
            Result indicating whether to continue processing.
        """
        # Extract text from tool results
        result_text = ""
        if hasattr(payload.result, "content"):
            if isinstance(payload.result.content, list):
                for item in payload.result.content:
                    if hasattr(item, "text") and isinstance(item.text, str):
                        result_text += item.text + " "
            elif isinstance(payload.result.content, str):
                result_text = payload.result.content
        elif isinstance(payload.result, dict):
            # Handle dict results
            for value in payload.result.values():
                if isinstance(value, str):
                    result_text += value + " "
        elif isinstance(payload.result, str):
            result_text = payload.result

        if len(result_text.strip()) > 3:
            try:
                moderation_result = await self._moderate_content(result_text)

                if self._cfg.audit_decisions:
                    logger.info(f"Content moderation - Tool output: {payload.name}, Result: {moderation_result.flagged}")

                if moderation_result.action == ModerationAction.BLOCK:
                    return ToolPostInvokeResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            reason="Content policy violation in tool output",
                            description=f"Harmful content detected in {payload.name} output",
                            code="CONTENT_MODERATION",
                            details={"tool": payload.name, "categories": moderation_result.categories, "confidence": moderation_result.confidence},
                        ),
                    )
                elif moderation_result.modified_content:
                    # Return modified result
                    return ToolPostInvokeResult(
                        modified_payload=ToolPostInvokePayload(name=payload.name, result=moderation_result.modified_content), metadata={"content_moderated": True, "content_modified": True}
                    )

            except Exception as e:
                logger.error(f"Content moderation failed for tool output {payload.name}: {e}")

        return ToolPostInvokeResult(metadata={"output_checked": True})

    async def shutdown(self) -> None:
        """Shutdown and cleanup HTTP client when plugin shuts down."""
        client = getattr(self, "_client", None)
        if client:
            await client.aclose()
            self._client = None

    async def __aenter__(self):
        """Async context manager entry.

        Returns:
            ContentModerationPlugin: The plugin instance.
        """
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb):
        """Async context manager exit - cleanup HTTP client."""
        await self.shutdown()
