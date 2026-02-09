# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/prompts_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Prompts page object for Prompt management features.
"""

# Third-Party
from playwright.sync_api import expect, Locator

# Local
from .base_page import BasePage


class PromptsPage(BasePage):
    """Page object for Prompt management features."""

    # ==================== Panel Elements ====================

    @property
    def prompts_panel(self) -> Locator:
        """Prompts panel container."""
        return self.page.locator("#prompts-panel")

    # ==================== Prompt Form Elements ====================

    @property
    def add_prompt_form(self) -> Locator:
        """Add prompt form."""
        return self.page.locator("#add-prompt-form")

    @property
    def prompt_name_input(self) -> Locator:
        """Prompt name input field."""
        return self.add_prompt_form.locator('[name="name"]')

    @property
    def prompt_description_input(self) -> Locator:
        """Prompt description input field."""
        return self.add_prompt_form.locator('[name="description"]')

    @property
    def prompt_content_input(self) -> Locator:
        """Prompt content/template input field."""
        return self.add_prompt_form.locator('[name="content"]')

    @property
    def prompt_arguments_input(self) -> Locator:
        """Prompt arguments input field (JSON)."""
        return self.add_prompt_form.locator('[name="arguments"]')

    @property
    def add_prompt_btn(self) -> Locator:
        """Add prompt submit button."""
        return self.add_prompt_form.locator('button[type="submit"]')

    # ==================== Prompt Table Elements ====================

    @property
    def prompts_table(self) -> Locator:
        """Prompts table."""
        return self.page.locator("#prompts-table")

    @property
    def prompts_table_body(self) -> Locator:
        """Prompts table body."""
        return self.page.locator("#prompts-table-body")

    @property
    def prompt_rows(self) -> Locator:
        """All prompt table rows."""
        return self.prompts_table_body.locator("tr")

    @property
    def prompt_items(self) -> Locator:
        """All prompt items (alternative selector)."""
        return self.page.locator('[data-testid="prompt-item"]')

    # ==================== Prompt Modal Elements ====================

    @property
    def prompt_modal(self) -> Locator:
        """Prompt details modal."""
        return self.page.locator("#prompt-modal")

    @property
    def prompt_edit_modal(self) -> Locator:
        """Prompt edit modal."""
        return self.page.locator("#prompt-edit-modal")

    @property
    def prompt_test_modal(self) -> Locator:
        """Prompt test modal."""
        return self.page.locator("#prompt-test-modal")

    @property
    def prompt_details_content(self) -> Locator:
        """Prompt details content area in view modal."""
        return self.page.locator("#prompt-details")

    @property
    def prompt_modal_close_btn(self) -> Locator:
        """Close button in prompt view modal."""
        return self.prompt_modal.locator('button:has-text("Close")')

    @property
    def prompt_edit_name_input(self) -> Locator:
        """Prompt name input in edit modal."""
        return self.prompt_edit_modal.locator("#edit-prompt-name")

    @property
    def prompt_edit_description_input(self) -> Locator:
        """Prompt description input in edit modal."""
        return self.prompt_edit_modal.locator("#edit-prompt-description")

    @property
    def prompt_edit_content_input(self) -> Locator:
        """Prompt content input in edit modal."""
        return self.prompt_edit_modal.locator("#edit-prompt-content")

    @property
    def prompt_edit_save_btn(self) -> Locator:
        """Save button in prompt edit modal."""
        return self.prompt_edit_modal.locator('button:has-text("Save")')

    @property
    def prompt_edit_cancel_btn(self) -> Locator:
        """Cancel button in prompt edit modal."""
        return self.prompt_edit_modal.locator('button:has-text("Cancel")')

    @property
    def prompt_test_form(self) -> Locator:
        """Prompt test form in test modal."""
        return self.page.locator("#prompt-test-form")

    @property
    def prompt_test_close_btn(self) -> Locator:
        """Close button in prompt test modal."""
        return self.prompt_test_modal.locator('button:has-text("Close")')

    @property
    def prompt_test_result(self) -> Locator:
        """Prompt test result display area."""
        return self.prompt_test_modal.locator("#prompt-test-result")

    # ==================== High-Level Navigation Methods ====================

    def navigate_to_prompts_tab(self) -> None:
        """Navigate to Prompts tab and wait for panel to be visible."""
        self.sidebar.click_prompts_tab()

    # ==================== High-Level Prompt Operations ====================

    def wait_for_prompts_table_loaded(self, timeout: int = 30000) -> None:
        """Wait for prompts table to be loaded and ready.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector("#prompts-panel:not(.hidden)", timeout=timeout)
        # Wait for table body to exist in DOM (may be empty, so don't require visible)
        self.wait_for_attached(self.prompts_table_body, timeout=timeout)

    def create_prompt(self, name: str, description: str, content: str = None, arguments: str = None) -> None:
        """Create a new prompt by filling and submitting the form.

        Args:
            name: Prompt name
            description: Prompt description
            content: Optional prompt content/template
            arguments: Optional prompt arguments (JSON string)
        """
        self.fill_locator(self.prompt_name_input, name)
        self.fill_locator(self.prompt_description_input, description)
        if content:
            self.fill_locator(self.prompt_content_input, content)
        if arguments:
            self.fill_locator(self.prompt_arguments_input, arguments)
        self.click_locator(self.add_prompt_btn)

    def fill_prompt_form(self, name: str, description: str, content: str = None, arguments: str = None) -> None:
        """Fill the add prompt form with provided data (without submitting).

        Args:
            name: Prompt name
            description: Prompt description
            content: Optional prompt content/template
            arguments: Optional prompt arguments (JSON string)
        """
        self.fill_locator(self.prompt_name_input, name)
        self.fill_locator(self.prompt_description_input, description)
        if content:
            self.fill_locator(self.prompt_content_input, content)
        if arguments:
            self.fill_locator(self.prompt_arguments_input, arguments)

    def submit_prompt_form(self) -> None:
        """Submit the add prompt form."""
        self.click_locator(self.add_prompt_btn)

    def get_prompt_row(self, prompt_index: int) -> Locator:
        """Get a specific prompt row by index.

        Args:
            prompt_index: Index of the prompt row

        Returns:
            Locator for the prompt row
        """
        return self.prompt_rows.nth(prompt_index)

    def prompt_exists(self, prompt_name: str) -> bool:
        """Check if a prompt with the given name exists in the table.

        Args:
            prompt_name: The name of the prompt to check

        Returns:
            True if prompt exists, False otherwise
        """
        return self.page.locator(f"text={prompt_name}").is_visible()

    def get_prompt_count(self) -> int:
        """Get number of prompts displayed.

        Returns:
            Number of visible prompt rows
        """
        self.page.wait_for_selector("#prompts-table-body", state="attached")
        return self.prompt_rows.locator(":visible").count()

    # ==================== Prompt Modal Interactions ====================

    def open_prompt_view_modal(self, prompt_index: int = 0) -> None:
        """Open the prompt view modal for a specific prompt.

        Args:
            prompt_index: Index of the prompt row (default: 0 for first prompt)
        """
        prompt_row = self.prompt_rows.nth(prompt_index)
        view_btn = prompt_row.locator('button:has-text("View")')
        self.click_locator(view_btn)
        # Wait for modal to open
        self.page.wait_for_selector("#prompt-modal:not(.hidden)", state="visible", timeout=10000)
        self.wait_for_visible(self.prompt_modal)

    def close_prompt_modal(self) -> None:
        """Close the prompt view modal."""
        self.click_locator(self.prompt_modal_close_btn)
        # Wait for modal to close
        self.page.wait_for_selector("#prompt-modal.hidden", state="hidden", timeout=10000)

    def open_prompt_edit_modal(self, prompt_index: int = 0) -> None:
        """Open the prompt edit modal for a specific prompt.

        Args:
            prompt_index: Index of the prompt row (default: 0 for first prompt)
        """
        prompt_row = self.prompt_rows.nth(prompt_index)
        edit_btn = prompt_row.locator('button:has-text("Edit")')
        self.click_locator(edit_btn)
        # Wait for modal to open
        self.page.wait_for_selector("#prompt-edit-modal:not(.hidden)", state="visible", timeout=10000)
        self.wait_for_visible(self.prompt_edit_modal)

    def edit_prompt_name(self, new_name: str) -> None:
        """Edit the prompt name in the edit modal.

        Args:
            new_name: New name for the prompt
        """
        self.fill_locator(self.prompt_edit_name_input, new_name)

    def edit_prompt_description(self, new_description: str) -> None:
        """Edit the prompt description in the edit modal.

        Args:
            new_description: New description for the prompt
        """
        self.fill_locator(self.prompt_edit_description_input, new_description)

    def edit_prompt_content(self, new_content: str) -> None:
        """Edit the prompt content in the edit modal.

        Args:
            new_content: New content for the prompt
        """
        self.fill_locator(self.prompt_edit_content_input, new_content)

    def save_prompt_edit(self) -> None:
        """Save changes in the prompt edit modal."""
        self.click_locator(self.prompt_edit_save_btn)
        # Wait for modal to close
        self.page.wait_for_selector("#prompt-edit-modal.hidden", state="hidden", timeout=10000)

    def cancel_prompt_edit(self) -> None:
        """Cancel editing and close the prompt edit modal."""
        self.click_locator(self.prompt_edit_cancel_btn)
        # Wait for modal to close
        self.page.wait_for_selector("#prompt-edit-modal.hidden", state="hidden", timeout=10000)

    def open_prompt_test_modal(self, prompt_index: int = 0) -> None:
        """Open the prompt test modal for a specific prompt.

        Args:
            prompt_index: Index of the prompt row (default: 0 for first prompt)
        """
        prompt_row = self.prompt_rows.nth(prompt_index)
        test_btn = prompt_row.locator('button:has-text("Test")')
        self.click_locator(test_btn)
        # Wait for modal to open
        self.page.wait_for_selector("#prompt-test-modal:not(.hidden)", state="visible", timeout=10000)
        self.wait_for_visible(self.prompt_test_modal)

    def run_prompt_test(self, params: dict = None) -> None:
        """Run a prompt test with optional parameters.

        Args:
            params: Optional dictionary of test parameters to fill in the form
        """
        if params:
            # Fill in test parameters if provided
            for key, value in params.items():
                input_field = self.prompt_test_form.locator(f'[name="{key}"]')
                if input_field.count() > 0:
                    self.fill_locator(input_field, str(value))

        # Submit the test form
        submit_btn = self.prompt_test_form.locator('button[type="submit"]')
        if submit_btn.count() > 0:
            self.click_locator(submit_btn)

    def close_prompt_test_modal(self) -> None:
        """Close the prompt test modal."""
        self.click_locator(self.prompt_test_close_btn)
        # Wait for modal to close
        self.page.wait_for_selector("#prompt-test-modal.hidden", state="hidden", timeout=10000)

    def delete_prompt(self, prompt_index: int = 0) -> None:
        """Delete a prompt with confirmation.

        Args:
            prompt_index: Index of the prompt row (default: 0 for first prompt)
        """
        # Setup dialog listener for confirmation
        self.page.once("dialog", lambda dialog: dialog.accept())

        # Click delete button
        prompt_row = self.prompt_rows.nth(prompt_index)
        delete_btn = prompt_row.locator('button:has-text("Delete")')
        self.click_locator(delete_btn)

    def wait_for_prompt_visible(self, prompt_name: str, timeout: int = 30000) -> None:
        """Wait for a prompt to be visible in the table.

        Args:
            prompt_name: The name of the prompt
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector(f"text={prompt_name}", timeout=timeout)
        expect(self.page.locator(f"text={prompt_name}")).to_be_visible()

    def wait_for_prompt_hidden(self, prompt_name: str) -> None:
        """Wait for a prompt to be hidden from the table.

        Args:
            prompt_name: The name of the prompt
        """
        expect(self.page.locator(f"text={prompt_name}")).to_be_hidden()
