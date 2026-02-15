# -*- coding: utf-8 -*-
"""A base class that leverages core functionality of LLMGuard and leverages it to apply guardrails on input and output.
It imports llmguard library, and uses it to apply two or more filters, combined by the logic of policy defined by the user.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

"""

# Standard
import asyncio
import hashlib
import time
from datetime import datetime, timedelta
from typing import Any, Optional

# Third-Party
from llm_guard import input_scanners, output_scanners, scan_output, scan_prompt
from llm_guard.output_scanners import Deanonymize
from llm_guard.util import configure_logger
from llm_guard.vault import Vault
from llmguardplugin.policy import get_policy_filters, GuardrailPolicy, ResponseGuardrailPolicy
from llmguardplugin.schema import LLMGuardConfig
from prometheus_client import Counter, Histogram
from rapidfuzz.distance import Levenshtein

# First-Party
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Quiet the llm_guard logger to reduce noise
configure_logger("ERROR", True)
# Prometheus metrics
llm_guard_scan_duration_seconds = Histogram(
    "llm_guard_scan_duration_seconds",
    "Duration of LLM Guard scans in seconds",
    labelnames=["scan_type", "scanner_category"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0),
)

llm_guard_levenshtein_duration_seconds = Histogram(
    "llm_guard_levenshtein_duration_seconds",
    "Duration of Levenshtein distance calculations in seconds",
    labelnames=["comparison_type"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


llm_guard_cache_hits = Histogram(
    "llm_guard_cache_hits",
    "Cache hit rate for LLM Guard scans",
    labelnames=["scan_type"],
    buckets=(0, 1),
)

llm_guard_cache_size = Histogram(
    "llm_guard_cache_size",
    "Current size of LLM Guard cache",
    labelnames=["scan_type"],
    buckets=(0, 10, 50, 100, 500, 1000, 5000, 10000),
)

llm_guard_cache_misses_total = Counter(
    "llm_guard_cache_misses_total",
    "Total number of cache misses",
    labelnames=["scan_type"],
)


class LLMGuardBase:
    """Base class that leverages LLMGuard library to apply a combination of filters (returns true of false, allowing or denying an input (like PromptInjection)) and sanitizers (transforms the input, like Anonymizer and Deanonymizer) for both input and output prompt.

    Attributes:
        lgconfig: Configuration for guardrails.
        scanners: Sanitizers and filters defined for input and output.
    """

    def __init__(self, config: Optional[dict[str, Any]]) -> None:
        """Initialize the instance.

        Args:
            config: Configuration for guardrails.
        """

        self.lgconfig = LLMGuardConfig.model_validate(config)
        self.scanners = {"input": {"sanitizers": [], "filters": []}, "output": {"sanitizers": [], "filters": []}}
        self.__init_scanners()
        self.policy = GuardrailPolicy()

        # Initialize result cache with configurable TTL (default 300 seconds = 5 minutes)
        self.cache_ttl = config.get("cache_ttl", 300) if config else 300
        self.cache_enabled = config.get("cache_enabled", True) if config else True
        self._result_cache: dict[str, tuple[Any, float]] = {}  # {content_hash: (result, timestamp)}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        logger.info(f"Result cache initialized: enabled={self.cache_enabled}, ttl={self.cache_ttl}s")

        # Start background cache cleanup task
        if self.cache_enabled:
            self._cleanup_task = asyncio.create_task(self._background_cache_cleanup())
            logger.info("Background cache cleanup task started")

    async def _background_cache_cleanup(self) -> None:
        """Background task that periodically cleans up expired cache entries.

        Runs every cache_ttl/2 seconds to ensure timely cleanup without
        blocking the main request flow.
        """
        cleanup_interval = max(self.cache_ttl / 2, 30)  # At least every 30 seconds
        logger.info(f"Background cache cleanup running every {cleanup_interval}s")

        while not self._shutdown_event.is_set():
            try:
                # Wait for cleanup interval or shutdown signal
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=cleanup_interval)
                # If we get here, shutdown was signaled
                break
            except asyncio.TimeoutError:
                # Timeout is expected - time to clean up
                if self.cache_enabled:
                    self._cleanup_expired_cache()

        logger.info("Background cache cleanup task stopped")

    async def shutdown(self) -> None:
        """Shutdown the LLMGuard instance and cleanup resources."""
        logger.info("Shutting down LLMGuard instance")
        self._shutdown_event.set()

        if self._cleanup_task and not self._cleanup_task.done():
            try:
                await asyncio.wait_for(self._cleanup_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Cache cleanup task did not finish in time, cancelling")
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass

        logger.info("LLMGuard instance shutdown complete")

    def _compute_content_hash(self, content: str, scan_type: str) -> str:
        """Compute SHA256 hash of content for cache key.

        Args:
            content: The content to hash
            scan_type: Type of scan (input/output) to include in hash

        Returns:
            Hexadecimal hash string
        """
        hash_input = f"{scan_type}:{content}".encode("utf-8")
        return hashlib.sha256(hash_input).hexdigest()

    def _get_cached_result(self, content_hash: str, scan_type: str) -> Optional[Any]:
        """Retrieve cached result if valid.

        Args:
            content_hash: Hash of the content
            scan_type: Type of scan for metrics

        Returns:
            Cached result if valid, None otherwise
        """
        if not self.cache_enabled:
            return None

        if content_hash in self._result_cache:
            result, timestamp = self._result_cache[content_hash]
            age = time.time() - timestamp

            if age < self.cache_ttl:
                logger.debug("Cache hit for %s: %s... (age: %.2fs)", scan_type, content_hash[:8], age)
                llm_guard_cache_hits.labels(scan_type=scan_type).observe(1)
                return result
            else:
                # Expired entry
                logger.debug("Cache expired for %s: %s... (age: %.2fs)", scan_type, content_hash[:8], age)
                del self._result_cache[content_hash]

        llm_guard_cache_hits.labels(scan_type=scan_type).observe(0)
        llm_guard_cache_misses_total.labels(scan_type=scan_type).inc()
        return None

    def _cache_result(self, content_hash: str, result: Any, scan_type: str) -> None:
        """Store result in cache.

        Args:
            content_hash: Hash of the content
            result: Result to cache
            scan_type: Type of scan for metrics
        """
        if not self.cache_enabled:
            return

        self._result_cache[content_hash] = (result, time.time())
        llm_guard_cache_size.labels(scan_type=scan_type).observe(len(self._result_cache))
        logger.debug("Cached result for %s: %s... (cache size: %d)", scan_type, content_hash[:8], len(self._result_cache))

    def _cleanup_expired_cache(self) -> None:
        """Remove expired entries from cache."""
        if not self.cache_enabled:
            return

        current_time = time.time()
        expired_keys = [key for key, (_, timestamp) in self._result_cache.items() if current_time - timestamp >= self.cache_ttl]

        for key in expired_keys:
            del self._result_cache[key]

        if expired_keys:
            logger.debug("Cleaned up %d expired cache entries", len(expired_keys))

    async def _create_new_vault_on_expiry(self, vault) -> bool:
        """Takes in vault object, checks it's creation time and checks if it has reached it's expiry time.
        If yes, then new vault object is created and sanitizers are initialized with the new cache object, deleting any earlier references
        to previous vault.

        Args:
            vault: vault object

        Returns:
            boolean to indicate if vault has expired or not. If true, then vault has expired and has been reinitialized,
            if false, then vault hasn't expired yet.
        """
        logger.info("Vault creation time %s", vault.creation_time)
        logger.info("Vault ttl %s", self.vault_ttl)
        if datetime.now() - vault.creation_time > timedelta(seconds=self.vault_ttl):
            del vault
            logger.info("Vault successfully deleted after expiry")
            # Reinitalize the scanner with new vault
            self._update_input_sanitizers()
            return True
        return False

    def _create_vault(self) -> Vault:
        """This function creates a new vault and sets it's creation time as it's attribute

        Returns:
            Vault: A new vault object with creation time set.
        """
        logger.info("Vault creation")
        vault = Vault()
        vault.creation_time = datetime.now()
        logger.info("Vault creation time %s", vault.creation_time)
        return vault

    def _retreive_vault(self, sanitizer_names: list = ["Anonymize"]) -> tuple[Vault | None, int | None, tuple | None]:
        """This function is responsible for retrieving vault for given sanitizer names

        Args:
            sanitizer_names: list of names for sanitizers

        Returns:
            tuple[Vault, int, tuple]: A tuple containing the vault object, vault ID, and vault tuples.
        """
        vault_id = None
        vault_tuples = None
        length = len(self.scanners["input"]["sanitizers"])
        if length == 0:
            return None, vault_id, vault_tuples
        for i in range(length):
            scanner_name = type(self.scanners["input"]["sanitizers"][i]).__name__
            if scanner_name in sanitizer_names:
                try:
                    logger.info(self.scanners["input"]["sanitizers"][i]._vault._tuples)
                    vault_id = id(self.scanners["input"]["sanitizers"][i]._vault)
                    vault_tuples = self.scanners["input"]["sanitizers"][i]._vault._tuples
                except Exception as e:
                    logger.error("Error retrieving scanner %s: %s", scanner_name, e)
        return self.scanners["input"]["sanitizers"][i]._vault, vault_id, vault_tuples

    def _update_input_sanitizers(self, sanitizer_names: list = ["Anonymize"]) -> None:
        """This function is responsible for updating vault for given sanitizer names in input

        Args:
            sanitizer_names: list of names for sanitizers"""
        length = len(self.scanners["input"]["sanitizers"])
        for i in range(length):
            scanner_name = type(self.scanners["input"]["sanitizers"][i]).__name__
            if scanner_name in sanitizer_names:
                try:
                    del self.scanners["input"]["sanitizers"][i]._vault
                    vault = self._create_vault()
                    self.scanners["input"]["sanitizers"][i]._vault = vault
                    logger.info(self.scanners["input"]["sanitizers"][i]._vault._tuples)
                except Exception as e:
                    logger.error("Error updating scanner %s: %s", scanner_name, e)

    def _update_output_sanitizers(self, config, sanitizer_names: list = ["Deanonymize"]) -> None:
        """This function is responsible for updating vault for given sanitizer names in output

        Args:
            config: Configuration containing sanitizer settings.
            sanitizer_names: list of names for sanitizers
        """
        length = len(self.scanners["output"]["sanitizers"])
        for i in range(length):
            scanner_name = type(self.scanners["output"]["sanitizers"][i]).__name__
            if scanner_name in sanitizer_names:
                try:
                    logger.info(self.scanners["output"]["sanitizers"][i]._vault._tuples)
                    self.scanners["output"]["sanitizers"][i]._vault = Vault(tuples=config[scanner_name])
                    logger.info(self.scanners["output"]["sanitizers"][i]._vault._tuples)
                except Exception as e:
                    logger.error("Error updating scanner %s: %s", scanner_name, e)

    def _load_policy_scanners(self, config: dict = None) -> list:
        """Loads all the scanner names defined in a policy.

        Args:
            config: configuration for scanner

        Returns:
            list: Either None or a list of scanners defined in the policy.
        """
        config_keys = get_policy_filters(config)
        if "policy" in config:
            policy_filters = get_policy_filters(config["policy"])
            check_policy_filter = set(policy_filters).issubset(set(config_keys))
            if not check_policy_filter:
                logger.debug("Policy mentions filter that is not defined in config")
                policy_filters = config_keys
        else:
            policy_filters = config_keys
        return policy_filters

    def _initialize_input_filters(self) -> None:
        """Initializes the input filters"""
        policy_filter_names = self._load_policy_scanners(self.lgconfig.input.filters)
        try:
            for filter_name in policy_filter_names:
                self.scanners["input"]["filters"].append(input_scanners.get_scanner_by_name(filter_name, self.lgconfig.input.filters[filter_name]))
        except Exception as e:
            logger.error("Error initializing filters %s", e)

    def _initialize_input_sanitizers(self) -> None:
        """Initializes the input sanitizers"""
        try:
            sanitizer_names = self.lgconfig.input.sanitizers.keys()
            for sanitizer_name in sanitizer_names:
                if sanitizer_name == "Anonymize":
                    vault = self._create_vault()
                    if "vault_ttl" in self.lgconfig.input.sanitizers[sanitizer_name]:
                        self.vault_ttl = self.lgconfig.input.sanitizers[sanitizer_name]["vault_ttl"]
                    self.lgconfig.input.sanitizers[sanitizer_name]["vault"] = vault
                    anonymizer_config = {k: v for k, v in self.lgconfig.input.sanitizers[sanitizer_name].items() if k not in ["vault_ttl", "vault_leak_detection"]}
                    logger.info("Anonymizer config %s", anonymizer_config)
                    logger.info("sanitizer config %s", self.lgconfig.input.sanitizers[sanitizer_name])
                    self.scanners["input"]["sanitizers"].append(input_scanners.get_scanner_by_name(sanitizer_name, anonymizer_config))
                else:
                    self.scanners["input"]["sanitizers"].append(input_scanners.get_scanner_by_name(sanitizer_name, self.lgconfig.input.sanitizers[sanitizer_name]))
        except Exception as e:
            logger.error("Error initializing sanitizers %s", e)

    def _initialize_output_filters(self) -> None:
        """Initializes output filters"""
        policy_filter_names = self._load_policy_scanners(self.lgconfig.output.filters)
        try:
            for filter_name in policy_filter_names:
                self.scanners["output"]["filters"].append(output_scanners.get_scanner_by_name(filter_name, self.lgconfig.output.filters[filter_name]))

        except Exception as e:
            logger.error("Error initializing filters %s", e)

    def _initialize_output_sanitizers(self) -> None:
        """Initializes output sanitizers"""
        sanitizer_names = self.lgconfig.output.sanitizers.keys()
        try:
            for sanitizer_name in sanitizer_names:
                if sanitizer_name == "Deanonymize":
                    self.lgconfig.output.sanitizers[sanitizer_name]["vault"] = Vault()
                self.scanners["output"]["sanitizers"].append(output_scanners.get_scanner_by_name(sanitizer_name, self.lgconfig.output.sanitizers[sanitizer_name]))
            logger.info(self.scanners)
        except Exception as e:
            logger.error("Error initializing filters %s", e)

    def __init_scanners(self):
        """Initializes all scanners defined in the config"""
        if self.lgconfig.input and self.lgconfig.input.filters:
            self._initialize_input_filters()
        if self.lgconfig.output and self.lgconfig.output.filters:
            self._initialize_output_filters()
        if self.lgconfig.input and self.lgconfig.input.sanitizers:
            self._initialize_input_sanitizers()
        if self.lgconfig.output and self.lgconfig.output.sanitizers:
            self._initialize_output_sanitizers()

    def _process_scanner_result(self, scanner, scan_result, default_prompt: str) -> tuple[str, dict[str, Any]]:
        """Process scanner result, handling exceptions with fail-closed security.

        Returns:
            Tuple of (scanner_name, result_dict)
        """
        scanner_name = type(scanner).__name__

        if isinstance(scan_result, Exception):
            logger.error("Scanner %s failed: %s", scanner_name, scan_result)
            return scanner_name, {
                "sanitized_prompt": default_prompt,
                "is_valid": False,
                "risk_score": 1.0,
            }

        sanitized_prompt, is_valid, risk_score = scan_result
        return scanner_name, {
            "sanitized_prompt": sanitized_prompt,
            "is_valid": is_valid,
            "risk_score": risk_score,
        }

    def _record_scan_metrics(self, scan_type: str, scanner_category: str, duration: float):
        """Record Prometheus metrics for scanner execution."""
        llm_guard_scan_duration_seconds.labels(
            scan_type=scan_type,
            scanner_category=scanner_category,
        ).observe(duration)

    async def _apply_input_filters(self, input_prompt) -> dict[str, dict[str, Any]]:
        """Takes in input_prompt and applies filters on it in parallel.

        Filters are run concurrently using asyncio.gather() for better performance.
        If any scanner fails, it is treated as is_valid=False (fail-closed) to ensure
        security is not bypassed due to scanner errors.

        Note: Filter scanners should be stateless. If a scanner mutates shared state,
        concurrent requests may cause race conditions.

        Args:
            input_prompt: The prompt to apply filters on

        Returns:
            result: A dictionary with key as scanner_name which is the name of the scanner applied to the input and value as a dictionary with keys "sanitized_prompt" which is the actual prompt,
                    "is_valid" which is boolean that says if the prompt is valid or not based on a scanner applied and "risk_score" which gives the risk score assigned by the scanner to the prompt.
        """

        # Check cache first
        content_hash = self._compute_content_hash(input_prompt, "input_filters")
        cached_result = self._get_cached_result(content_hash, "input_filters")
        if cached_result is not None:
            return cached_result

        start_time = time.time()

        # Create tasks with optional timeout
        async def scan_input_prompt_with_timeout(scanner):
            """
            This code defines an async helper function that wraps a synchronous scanner operation
            to run it in a thread pool with a timeout. It's part of the LLMGuard plugin's input
            filtering mechanism that scans prompts for security/safety issues.

            Returns:
                Any: The result of the scanner operation.
            """
            coro = asyncio.to_thread(scanner.scan, input_prompt)
            return await asyncio.wait_for(coro, timeout=30.0)

        tasks = [scan_input_prompt_with_timeout(scanner) for scanner in self.scanners["input"]["filters"]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        result = dict(self._process_scanner_result(scanner, scan_result, input_prompt) for scanner, scan_result in zip(self.scanners["input"]["filters"], results))

        # Cache the result
        self._cache_result(content_hash, result, "input_filters")

        # Record metrics
        duration = time.time() - start_time
        self._record_scan_metrics("input", "filters", duration=duration)
        return result

    async def _apply_input_sanitizers(self, input_prompt) -> dict[str, dict[str, Any]] | None:
        """Takes in input_prompt and applies sanitizers on it.

        Args:
            input_prompt: The prompt to apply filters on

        Returns:
            result: A dictionary with key as scanner_name which is the name of the scanner applied to the input and value as a dictionary with keys "sanitized_prompt" which is the actual prompt,
                    "is_valid" which is boolean that says if the prompt is valid or not based on a scanner applied and "risk_score" which gives the risk score assigned by the scanner to the prompt.
        """
        start_time = time.time()
        vault, _, _ = self._retreive_vault()
        if vault is None:
            return None
        # Check for expiry of vault, every time before a sanitizer is applied.
        vault_update_status = await self._create_new_vault_on_expiry(vault)
        logger.info("Status of vault_update %s", vault_update_status)
        result = await asyncio.to_thread(scan_prompt, self.scanners["input"]["sanitizers"], input_prompt)
        if "Anonymize" in result[1]:
            anonymize_config = self.lgconfig.input.sanitizers["Anonymize"]
            if "vault_leak_detection" in anonymize_config and anonymize_config["vault_leak_detection"] and not vault_update_status:
                scanner = Deanonymize(vault)
                sanitized_output_de, _, _ = await asyncio.to_thread(scanner.scan, result[0], input_prompt)
                # input_anonymize_score = word_wise_levenshtein_distance(input_prompt, result[0])
                lev_start = time.time()
                input_anonymize_score = Levenshtein.distance(input_prompt.split(), result[0].split())
                llm_guard_levenshtein_duration_seconds.labels(comparison_type="input_anonymize").observe(time.time() - lev_start)
                # input_deanonymize_score = word_wise_levenshtein_distance(result[0], sanitized_output_de)
                lev_start = time.time()
                input_deanonymize_score = Levenshtein.distance(result[0].split(), sanitized_output_de.split())
                llm_guard_levenshtein_duration_seconds.labels(comparison_type="input_deanonymize").observe(time.time() - lev_start)
                if input_anonymize_score != input_deanonymize_score:
                    return None

        # Record metrics
        duration = time.time() - start_time
        llm_guard_scan_duration_seconds.labels(scan_type="input", scanner_category="sanitizers").observe(duration)

        return result

    async def _apply_output_filters(self, original_input, model_response) -> dict[str, dict[str, Any]]:
        """Takes in model_response and applies filters on it in parallel.

        Filters are run concurrently using asyncio.gather() for better performance.
        If any scanner fails, it is treated as is_valid=False (fail-closed) to ensure
        security is not bypassed due to scanner errors.

        Args:
            original_input: The original input prompt for which model produced a response
            model_response: The model's response to apply filters on

        Returns:
            dict[str, dict[str, Any]]: A dictionary with key as scanner_name which is the name of the scanner applied to the output and value as a dictionary with keys "sanitized_prompt" which is the actual prompt,
                    "is_valid" which is boolean that says if the prompt is valid or not based on a scanner applied and "risk_score" which gives the risk score assigned by the scanner to the prompt.
        """

        # Check cache first
        cache_key = f"{original_input}:{model_response}"
        content_hash = self._compute_content_hash(cache_key, "output_filters")
        cached_result = self._get_cached_result(content_hash, "output_filters")
        if cached_result is not None:
            return cached_result

        start_time = time.time()

        # Create tasks with optional timeout
        async def scan_output_prompt_with_timeout(scanner):
            """
            This code defines an async helper function that wraps a synchronous scanner operation to
            run it in a thread pool with a timeout. It's part of the LLMGuard plugin's output scanning
            mechanism that validates model responses for security/safety issues.

            Returns:
                Any: The result of the scanner operation.
            """
            coro = asyncio.to_thread(scanner.scan, original_input, model_response)
            return await asyncio.wait_for(coro, timeout=30.0)

        tasks = [scan_output_prompt_with_timeout(scanner) for scanner in self.scanners["output"]["filters"]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        result = {}

        result = dict(self._process_scanner_result(scanner, scan_result, model_response) for scanner, scan_result in zip(self.scanners["output"]["filters"], results))

        # Cache the result
        self._cache_result(content_hash, result, "output_filters")

        # Record metrics
        duration = time.time() - start_time
        self._record_scan_metrics("output", "filters", duration=duration)
        return result

    async def _apply_output_sanitizers(self, input_prompt, model_response) -> dict[str, dict[str, Any]]:
        """Takes in model_response and applies sanitizers on it.

        Args:
            input_prompt: The original input prompt for which model produced a response
            model_response: The model's response to apply sanitizers on

        Returns:
            dict[str, dict[str, Any]]: A dictionary with key as scanner_name which is the name of the scanner applied to the output and value as a dictionary with keys "sanitized_prompt" which is the actual prompt,
                    "is_valid" which is boolean that says if the prompt is valid or not based on a scanner applied and "risk_score" which gives the risk score assigned by the scanner to the prompt.
        """
        start_time = time.time()
        result = await asyncio.to_thread(scan_output, self.scanners["output"]["sanitizers"], input_prompt, model_response)

        # Record metrics
        duration = time.time() - start_time
        llm_guard_scan_duration_seconds.labels(scan_type="output", scanner_category="sanitizers").observe(duration)

        return result

    def _apply_policy_input(self, result_scan) -> tuple[bool, str, dict[str, Any]]:
        """Applies policy on input

        Args:
            result_scan: A dictionary of results of scanners on input

        Returns:
            tuple with first element being policy decision (true or false), policy_message as the message sent by policy and result_scan a dict with all the scan results.
        """
        policy_expression = self.lgconfig.input.filters["policy"] if "policy" in self.lgconfig.input.filters else " and ".join(list(self.lgconfig.input.filters))
        policy_message = self.lgconfig.input.filters["policy_message"] if "policy_message" in self.lgconfig.input.filters else ResponseGuardrailPolicy.DEFAULT_POLICY_DENIAL_RESPONSE.value

        if not self.policy.evaluate(policy_expression, result_scan):
            return False, policy_message, result_scan
        return True, ResponseGuardrailPolicy.DEFAULT_POLICY_ALLOW_RESPONSE.value, result_scan

    def _apply_policy_output(self, result_scan) -> tuple[bool, str, dict[str, Any]]:
        """Applies policy on output

        Args:
            result_scan: A dictionary of results of scanners on output

        Returns:
            tuple with first element being policy decision (true or false), policy_message as the message sent by policy and result_scan a dict with all the scan results.
        """
        policy_expression = self.lgconfig.output.filters["policy"] if "policy" in self.lgconfig.output.filters else " and ".join(list(self.lgconfig.output.filters))
        policy_message = self.lgconfig.output.filters["policy_message"] if "policy_message" in self.lgconfig.output.filters else ResponseGuardrailPolicy.DEFAULT_POLICY_DENIAL_RESPONSE.value
        if not self.policy.evaluate(policy_expression, result_scan):
            return False, policy_message, result_scan
        return True, ResponseGuardrailPolicy.DEFAULT_POLICY_ALLOW_RESPONSE.value, result_scan
