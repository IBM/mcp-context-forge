# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/resources_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Resources page object for Resource management features.
"""

# Third-Party
from playwright.sync_api import Page, Locator, expect

# Local
from .base_page import BasePage


class ResourcesPage(BasePage):
    """Page object for Resource management features."""

    def __init__(self, page: Page):
        super().__init__(page)

    # ==================== Panel Elements ====================

    @property
    def resources_panel(self) -> Locator:
        """Resources panel container."""
        return self.page.locator("#resources-panel")

    # ==================== Resource Form Elements ====================

    @property
    def add_resource_form(self) -> Locator:
        """Add resource form."""
        return self.page.locator("#add-resource-form")

    @property
    def resource_uri_input(self) -> Locator:
        """Resource URI input field."""
        return self.add_resource_form.locator('[name="uri"]')

    @property
    def resource_name_input(self) -> Locator:
        """Resource name input field."""
        return self.add_resource_form.locator('[name="name"]')

    @property
    def resource_mime_type_input(self) -> Locator:
        """Resource MIME type input field."""
        return self.add_resource_form.locator('[name="mimeType"]')

    @property
    def resource_description_input(self) -> Locator:
        """Resource description input field."""
        return self.add_resource_form.locator('[name="description"]')

    @property
    def add_resource_btn(self) -> Locator:
        """Add resource submit button."""
        return self.add_resource_form.locator('button[type="submit"]')

    # ==================== Resource Table Elements ====================

    @property
    def resources_table(self) -> Locator:
        """Resources table."""
        return self.page.locator("#resources-table")

    @property
    def resources_table_body(self) -> Locator:
        """Resources table body."""
        return self.page.locator("#resources-table-body")

    @property
    def resource_rows(self) -> Locator:
        """All resource table rows."""
        return self.resources_table_body.locator("tr")

    @property
    def resource_items(self) -> Locator:
        """All resource items (alternative selector)."""
        return self.page.locator('[data-testid="resource-item"]')

    # ==================== Resource Modal Elements ====================

    @property
    def resource_modal(self) -> Locator:
        """Resource details modal."""
        return self.page.locator("#resource-modal")

    @property
    def resource_edit_modal(self) -> Locator:
        """Resource edit modal."""
        return self.page.locator("#resource-edit-modal")

    @property
    def resource_details_content(self) -> Locator:
        """Resource details content area in view modal."""
        return self.page.locator("#resource-details")

    @property
    def resource_modal_close_btn(self) -> Locator:
        """Close button in resource view modal."""
        return self.resource_modal.locator('button:has-text("Close")')

    @property
    def resource_edit_name_input(self) -> Locator:
        """Resource name input in edit modal."""
        return self.resource_edit_modal.locator("#edit-resource-name")

    @property
    def resource_edit_description_input(self) -> Locator:
        """Resource description input in edit modal."""
        return self.resource_edit_modal.locator("#edit-resource-description")

    @property
    def resource_edit_save_btn(self) -> Locator:
        """Save button in resource edit modal."""
        return self.resource_edit_modal.locator('button:has-text("Save")')

    @property
    def resource_edit_cancel_btn(self) -> Locator:
        """Cancel button in resource edit modal."""
        return self.resource_edit_modal.locator('button:has-text("Cancel")')

    # ==================== High-Level Navigation Methods ====================

    def navigate_to_resources_tab(self) -> None:
        """Navigate to Resources tab and wait for panel to be visible."""
        self.sidebar.click_resources_tab()

    # ==================== High-Level Resource Operations ====================

    def wait_for_resources_table_loaded(self, timeout: int = 30000) -> None:
        """Wait for resources table to be loaded and ready.
        
        Args:
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector("#resources-panel:not(.hidden)", timeout=timeout)
        # Wait for table body to exist in DOM (may be empty, so don't require visible)
        self.wait_for_attached(self.resources_table_body, timeout=timeout)

    def create_resource(self, uri: str, name: str, mime_type: str, description: str) -> None:
        """Create a new resource by filling and submitting the form.
        
        Args:
            uri: Resource URI
            name: Resource name
            mime_type: Resource MIME type
            description: Resource description
        """
        self.fill_locator(self.resource_uri_input, uri)
        self.fill_locator(self.resource_name_input, name)
        self.fill_locator(self.resource_mime_type_input, mime_type)
        self.fill_locator(self.resource_description_input, description)
        self.click_locator(self.add_resource_btn)

    def fill_resource_form(self, uri: str, name: str, mime_type: str, description: str) -> None:
        """Fill the add resource form with provided data (without submitting).
        
        Args:
            uri: Resource URI
            name: Resource name
            mime_type: Resource MIME type
            description: Resource description
        """
        self.fill_locator(self.resource_uri_input, uri)
        self.fill_locator(self.resource_name_input, name)
        self.fill_locator(self.resource_mime_type_input, mime_type)
        self.fill_locator(self.resource_description_input, description)

    def submit_resource_form(self) -> None:
        """Submit the add resource form."""
        self.click_locator(self.add_resource_btn)

    def get_resource_row(self, resource_index: int) -> Locator:
        """Get a specific resource row by index.
        
        Args:
            resource_index: Index of the resource row
            
        Returns:
            Locator for the resource row
        """
        return self.resource_rows.nth(resource_index)

    def resource_exists(self, resource_name: str) -> bool:
        """Check if a resource with the given name exists in the table.
        
        Args:
            resource_name: The name of the resource to check
            
        Returns:
            True if resource exists, False otherwise
        """
        return self.page.locator(f"text={resource_name}").is_visible()

    def get_resource_count(self) -> int:
        """Get number of resources displayed.
        
        Returns:
            Number of visible resource rows
        """
        self.page.wait_for_selector("#resources-table-body", state="attached")
        return self.resource_rows.locator(":visible").count()

    # ==================== Resource Modal Interactions ====================

    def open_resource_view_modal(self, resource_index: int = 0) -> None:
        """Open the resource view modal for a specific resource.
        
        Args:
            resource_index: Index of the resource row (default: 0 for first resource)
        """
        resource_row = self.resource_rows.nth(resource_index)
        view_btn = resource_row.locator('button:has-text("View")')
        self.click_locator(view_btn)
        # Wait for modal to open
        self.page.wait_for_selector("#resource-modal:not(.hidden)", state="visible", timeout=10000)
        self.wait_for_visible(self.resource_modal)

    def close_resource_modal(self) -> None:
        """Close the resource view modal."""
        self.click_locator(self.resource_modal_close_btn)
        # Wait for modal to close
        self.page.wait_for_selector("#resource-modal.hidden", state="hidden", timeout=10000)

    def open_resource_edit_modal(self, resource_index: int = 0) -> None:
        """Open the resource edit modal for a specific resource.
        
        Args:
            resource_index: Index of the resource row (default: 0 for first resource)
        """
        resource_row = self.resource_rows.nth(resource_index)
        edit_btn = resource_row.locator('button:has-text("Edit")')
        self.click_locator(edit_btn)
        # Wait for modal to open
        self.page.wait_for_selector("#resource-edit-modal:not(.hidden)", state="visible", timeout=10000)
        self.wait_for_visible(self.resource_edit_modal)

    def edit_resource_name(self, new_name: str) -> None:
        """Edit the resource name in the edit modal.
        
        Args:
            new_name: New name for the resource
        """
        self.fill_locator(self.resource_edit_name_input, new_name)

    def edit_resource_description(self, new_description: str) -> None:
        """Edit the resource description in the edit modal.
        
        Args:
            new_description: New description for the resource
        """
        self.fill_locator(self.resource_edit_description_input, new_description)

    def save_resource_edit(self) -> None:
        """Save changes in the resource edit modal."""
        self.click_locator(self.resource_edit_save_btn)
        # Wait for modal to close
        self.page.wait_for_selector("#resource-edit-modal.hidden", state="hidden", timeout=10000)

    def cancel_resource_edit(self) -> None:
        """Cancel editing and close the resource edit modal."""
        self.click_locator(self.resource_edit_cancel_btn)
        # Wait for modal to close
        self.page.wait_for_selector("#resource-edit-modal.hidden", state="hidden", timeout=10000)

    def delete_resource(self, resource_index: int = 0) -> None:
        """Delete a resource with confirmation.
        
        Args:
            resource_index: Index of the resource row (default: 0 for first resource)
        """
        # Setup dialog listener for confirmation
        self.page.once("dialog", lambda dialog: dialog.accept())
        
        # Click delete button
        resource_row = self.resource_rows.nth(resource_index)
        delete_btn = resource_row.locator('button:has-text("Delete")')
        self.click_locator(delete_btn)

    def wait_for_resource_visible(self, resource_name: str, timeout: int = 30000) -> None:
        """Wait for a resource to be visible in the table.
        
        Args:
            resource_name: The name of the resource
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector(f"text={resource_name}", timeout=timeout)
        expect(self.page.locator(f"text={resource_name}")).to_be_visible()

    def wait_for_resource_hidden(self, resource_name: str) -> None:
        """Wait for a resource to be hidden from the table.
        
        Args:
            resource_name: The name of the resource
        """
        expect(self.page.locator(f"text={resource_name}")).to_be_hidden()