# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_prompts.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

CRUD tests for Prompts entity in MCP Gateway Admin UI.
"""

# Standard
import json

# Local
from ..pages.admin_utils import find_prompt
from ..pages.prompts_page import PromptsPage


class TestPromptsCRUD:
    """CRUD tests for Prompts entity."""

    @staticmethod
    def _wait_for_codemirror(prompts_page: PromptsPage, timeout: int = 30000):
        """Wait for CodeMirror promptArgsEditor to be initialized."""
        # First wait for CodeMirror library to load
        prompts_page.page.wait_for_function("typeof window.CodeMirror !== 'undefined'", timeout=timeout)
        # Then wait for the specific editor instance
        prompts_page.page.wait_for_function(
            "typeof window.promptArgsEditor !== 'undefined' && window.promptArgsEditor !== null",
            timeout=timeout,
        )

    def test_create_new_prompt(self, prompts_page: PromptsPage, test_prompt_data):
        """Test creating a new prompt."""
        # Navigate to Prompts tab
        prompts_page.navigate_to_prompts_tab()

        # Wait for CodeMirror editor to be initialized
        self._wait_for_codemirror(prompts_page)

        # Fill the basic form fields using Page Object method
        prompts_page.fill_prompt_form(name=test_prompt_data["name"], description=test_prompt_data["description"])

        # Fill arguments using CodeMirror instance (special handling required)
        args_json = test_prompt_data["arguments"]
        if not isinstance(args_json, str):
            args_json = json.dumps(args_json)
        prompts_page.page.evaluate(f"window.promptArgsEditor.setValue({json.dumps(args_json)})")

        # Submit the form
        with prompts_page.page.expect_response(lambda response: "/admin/prompts" in response.url and response.request.method == "POST") as response_info:
            prompts_page.submit_prompt_form()
        response = response_info.value
        assert response.status < 400

        # Verify creation using utility function
        created_prompt = find_prompt(prompts_page.page, test_prompt_data["name"])
        assert created_prompt is not None

        # Cleanup: delete the created prompt for idempotency
        if created_prompt:
            prompts_page.page.request.post(
                f"/admin/prompts/{created_prompt['id']}/delete",
                data="is_inactive_checked=false",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

    def test_delete_prompt(self, prompts_page: PromptsPage, test_prompt_data):
        """Test deleting a prompt."""
        # Navigate to Prompts tab
        prompts_page.navigate_to_prompts_tab()

        # Wait for CodeMirror editor to be initialized
        self._wait_for_codemirror(prompts_page)

        # Fill the basic form fields using Page Object method
        prompts_page.fill_prompt_form(name=test_prompt_data["name"], description=test_prompt_data["description"])

        # Fill arguments using CodeMirror instance (special handling required)
        args_json = test_prompt_data["arguments"]
        if not isinstance(args_json, str):
            args_json = json.dumps(args_json)
        prompts_page.page.evaluate(f"window.promptArgsEditor.setValue({json.dumps(args_json)})")

        # Submit the form
        with prompts_page.page.expect_response(lambda response: "/admin/prompts" in response.url and response.request.method == "POST"):
            prompts_page.submit_prompt_form()

        # Verify creation
        created_prompt = find_prompt(prompts_page.page, test_prompt_data["name"])
        assert created_prompt is not None

        # Delete using API (could be enhanced with UI delete method in future)
        delete_response = prompts_page.page.request.post(
            f"/admin/prompts/{created_prompt['id']}/delete",
            data="is_inactive_checked=false",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert delete_response.status < 400

        # Verify deletion
        assert find_prompt(prompts_page.page, test_prompt_data["name"]) is None
