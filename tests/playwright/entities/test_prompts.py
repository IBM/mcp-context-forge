# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_prompts.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

CRUD tests for Prompts entity in MCP Gateway Admin UI.
"""

# Standard
import json
import time

# Third-Party
from playwright.sync_api import Page


def _find_prompt(page: Page, prompt_name: str, retries: int = 5):
    """Find a prompt by name via the admin JSON endpoint."""
    for _ in range(retries):
        cache_bust = str(int(time.time() * 1000))
        response = page.request.get(f"/admin/prompts?per_page=500&cache_bust={cache_bust}")
        if response.ok:
            payload = response.json()
            data = payload.get("data", [])
            for prompt in data:
                if prompt.get("name") == prompt_name:
                    return prompt
        time.sleep(0.5)
    return None


class TestPromptsCRUD:
    """CRUD tests for Prompts entity."""

    @staticmethod
    def _wait_for_codemirror(page: Page, timeout: int = 30000):
        """Wait for CodeMirror promptArgsEditor to be initialized."""
        # First wait for CodeMirror library to load
        page.wait_for_function("typeof window.CodeMirror !== 'undefined'", timeout=timeout)
        # Then wait for the specific editor instance
        page.wait_for_function(
            "typeof window.promptArgsEditor !== 'undefined' && window.promptArgsEditor !== null",
            timeout=timeout,
        )

    def test_create_new_prompt(self, admin_page: Page, test_prompt_data):
        """Test creating a new prompt."""
        # Go to Prompts tab
        admin_page.click("#tab-prompts")
        admin_page.wait_for_selector("#prompts-panel:not(.hidden)")

        # Wait for CodeMirror editor to be initialized
        self._wait_for_codemirror(admin_page)

        # Fill the form
        admin_page.fill('#add-prompt-form [name="name"]', test_prompt_data["name"])
        admin_page.fill('#add-prompt-form [name="description"]', test_prompt_data["description"])

        # Fill arguments using CodeMirror instance
        args_json = test_prompt_data["arguments"]
        # Ensure it's a valid JSON string for JS evaluation
        if not isinstance(args_json, str):
            args_json = json.dumps(args_json)

        admin_page.evaluate(f"window.promptArgsEditor.setValue({json.dumps(args_json)})")

        # Submit
        with admin_page.expect_response(lambda response: "/admin/prompts" in response.url and response.request.method == "POST") as response_info:
            admin_page.click('#add-prompt-form button[type="submit"]')
        response = response_info.value
        assert response.status < 400

        # Verify creation
        created_prompt = _find_prompt(admin_page, test_prompt_data["name"])
        assert created_prompt is not None

        # Cleanup: delete the created prompt for idempotency
        if created_prompt:
            admin_page.request.post(
                f"/admin/prompts/{created_prompt['id']}/delete",
                data="is_inactive_checked=false",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

    def test_delete_prompt(self, admin_page: Page, test_prompt_data):
        """Test deleting a prompt."""
        # Go to Prompts tab
        admin_page.click("#tab-prompts")
        admin_page.wait_for_selector("#prompts-panel:not(.hidden)")

        # Wait for CodeMirror editor to be initialized
        self._wait_for_codemirror(admin_page)

        # Create prompt first
        admin_page.fill('#add-prompt-form [name="name"]', test_prompt_data["name"])
        admin_page.fill('#add-prompt-form [name="description"]', test_prompt_data["description"])

        # Fill arguments using CodeMirror
        args_json = test_prompt_data["arguments"]
        if not isinstance(args_json, str):
            args_json = json.dumps(args_json)
        admin_page.evaluate(f"window.promptArgsEditor.setValue({json.dumps(args_json)})")

        with admin_page.expect_response(lambda response: "/admin/prompts" in response.url and response.request.method == "POST"):
            admin_page.click('#add-prompt-form button[type="submit"]')

        created_prompt = _find_prompt(admin_page, test_prompt_data["name"])
        assert created_prompt is not None

        # Delete
        delete_response = admin_page.request.post(
            f"/admin/prompts/{created_prompt['id']}/delete",
            data="is_inactive_checked=false",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert delete_response.status < 400
        assert _find_prompt(admin_page, test_prompt_data["name"]) is None
