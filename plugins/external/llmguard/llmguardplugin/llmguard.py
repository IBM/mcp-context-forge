# -*- coding: utf-8 -*-
"""A base class that leverages core functionality of LLMGuard and leverages it to apply guardrails on input and output.
It imports llmguard library, and uses it to apply two or more filters, combined by the logic of policy defined by the user.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

"""

# Standard
import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

# Third-Party
from llm_guard import input_scanners, output_scanners, scan_output, scan_prompt
from llm_guard.output_scanners import Deanonymize
from llm_guard.util import configure_logger
from llm_guard.vault import Vault
from llmguardplugin.policy import get_policy_filters, GuardrailPolicy, ResponseGuardrailPolicy, word_wise_levenshtein_distance
from llmguardplugin.schema import LLMGuardConfig

# First-Party
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Quiet the llm_guard logger to reduce noise
configure_logger("ERROR")


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

    def _create_new_vault_on_expiry(self, vault) -> bool:
        """Takes in vault object, checks it's creation time and checks if it has reached it's expiry time.
        If yes, then new vault object is created and sanitizers are initialized with the new cache object, deleting any earlier references
        to previous vault.

        Args:
            vault: vault object

        Returns:
            boolean to indicate if vault has expired or not. If true, then vault has expired and has been reinitialized,
            if false, then vault hasn't expired yet.
        """
        logger.info(f"Vault creation time {vault.creation_time}")
        logger.info(f"Vault ttl {self.vault_ttl}")
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
        logger.info(f"Vault creation time {vault.creation_time}")
        return vault

    def _retreive_vault(self, sanitizer_names: list = ["Anonymize"]) -> tuple[Vault, int, tuple]:
        """This function is responsible for retrieving vault for given sanitizer names

        Args:
            sanitizer_names: list of names for sanitizers

        Returns:
            tuple[Vault, int, tuple]: A tuple containing the vault object, vault ID, and vault tuples.
        """
        vault_id = None
        vault_tuples = None
        length = len(self.scanners["input"]["sanitizers"])
        for i in range(length):
            scanner_name = type(self.scanners["input"]["sanitizers"][i]).__name__
            if scanner_name in sanitizer_names:
                try:
                    logger.info(self.scanners["input"]["sanitizers"][i]._vault._tuples)
                    vault_id = id(self.scanners["input"]["sanitizers"][i]._vault)
                    vault_tuples = self.scanners["input"]["sanitizers"][i]._vault._tuples
                except Exception as e:
                    logger.error(f"Error retrieving scanner {scanner_name}: {e}")
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
                    logger.error(f"Error updating scanner {scanner_name}: {e}")

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
                    logger.error(f"Error updating scanner {scanner_name}: {e}")

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
            logger.error(f"Error initializing filters {e}")

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
                    logger.info(f"Anonymizer config {anonymizer_config}")
                    logger.info(f"sanitizer config {self.lgconfig.input.sanitizers[sanitizer_name]}")
                    self.scanners["input"]["sanitizers"].append(input_scanners.get_scanner_by_name(sanitizer_name, anonymizer_config))
                else:
                    self.scanners["input"]["sanitizers"].append(input_scanners.get_scanner_by_name(sanitizer_name, self.lgconfig.input.sanitizers[sanitizer_name]))
        except Exception as e:
            logger.error(f"Error initializing sanitizers {e}")

    def _initialize_output_filters(self) -> None:
        """Initializes output filters"""
        policy_filter_names = self._load_policy_scanners(self.lgconfig.output.filters)
        try:
            for filter_name in policy_filter_names:
                self.scanners["output"]["filters"].append(output_scanners.get_scanner_by_name(filter_name, self.lgconfig.output.filters[filter_name]))

        except Exception as e:
            logger.error(f"Error initializing filters {e}")

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
            logger.error(f"Error initializing filters {e}")

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

        async def scan_async(scanner):
            """Asynchronously scan input using the provided scanner."""
            return await asyncio.to_thread(scanner.scan, input_prompt)

        tasks = [scan_async(scanner) for scanner in self.scanners["input"]["filters"]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        result = {}
        for scanner, scan_result in zip(self.scanners["input"]["filters"], results):
            scanner_name = type(scanner).__name__
            if isinstance(scan_result, Exception):
                # Fail-closed: treat scanner errors as invalid to deny the request
                logger.error(f"Scanner {scanner_name} failed: {scan_result}")
                result[scanner_name] = {
                    "sanitized_prompt": input_prompt,
                    "is_valid": False,
                    "risk_score": 1.0,
                }
                continue
            sanitized_prompt, is_valid, risk_score = scan_result
            result[scanner_name] = {
                "sanitized_prompt": sanitized_prompt,
                "is_valid": is_valid,
                "risk_score": risk_score,
            }

        return result

    async def _apply_input_sanitizers(self, input_prompt) -> dict[str, dict[str, Any]]:
        """Takes in input_prompt and applies sanitizers on it.

        Args:
            input_prompt: The prompt to apply filters on

        Returns:
            result: A dictionary with key as scanner_name which is the name of the scanner applied to the input and value as a dictionary with keys "sanitized_prompt" which is the actual prompt,
                    "is_valid" which is boolean that says if the prompt is valid or not based on a scanner applied and "risk_score" which gives the risk score assigned by the scanner to the prompt.
        """
        vault, _, _ = self._retreive_vault()
        logger.info(f"Shriti {vault}")
        # Check for expiry of vault, every time before a sanitizer is applied.
        vault_update_status = self._create_new_vault_on_expiry(vault)
        logger.info(f"Status of vault_update {vault_update_status}")
        result = await asyncio.to_thread(scan_prompt, self.scanners["input"]["sanitizers"], input_prompt)
        if "Anonymize" in result[1]:
            anonymize_config = self.lgconfig.input.sanitizers["Anonymize"]
            if "vault_leak_detection" in anonymize_config and anonymize_config["vault_leak_detection"] and not vault_update_status:
                scanner = Deanonymize(vault)
                sanitized_output_de, _, _ = await asyncio.to_thread(scanner.scan, result[0], input_prompt)
                input_anonymize_score = word_wise_levenshtein_distance(input_prompt, result[0])
                input_deanonymize_score = word_wise_levenshtein_distance(result[0], sanitized_output_de)
                if input_anonymize_score != input_deanonymize_score:
                    return None
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

        async def scan_async(scanner):
            """Asynchronously scan output using the provided scanner."""
            return await asyncio.to_thread(scanner.scan, original_input, model_response)

        tasks = [scan_async(scanner) for scanner in self.scanners["output"]["filters"]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        result = {}
        logger.info(f"Output scanners {self.scanners}")
        for scanner, scan_result in zip(self.scanners["output"]["filters"], results):
            scanner_name = type(scanner).__name__
            if isinstance(scan_result, Exception):
                # Fail-closed: treat scanner errors as invalid to deny the response
                logger.error(f"Scanner {scanner_name} failed: {scan_result}")
                result[scanner_name] = {
                    "sanitized_prompt": model_response,
                    "is_valid": False,
                    "risk_score": 1.0,
                }
                continue
            sanitized_prompt, is_valid, risk_score = scan_result
            result[scanner_name] = {
                "sanitized_prompt": sanitized_prompt,
                "is_valid": is_valid,
                "risk_score": risk_score,
            }

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
        result = await asyncio.to_thread(scan_output, self.scanners["output"]["sanitizers"], input_prompt, model_response)
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
        policy = GuardrailPolicy()
        if not policy.evaluate(policy_expression, result_scan):
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
        policy = GuardrailPolicy()
        if not policy.evaluate(policy_expression, result_scan):
            return False, policy_message, result_scan
        return True, ResponseGuardrailPolicy.DEFAULT_POLICY_ALLOW_RESPONSE.value, result_scan
