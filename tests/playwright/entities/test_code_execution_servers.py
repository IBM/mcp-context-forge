# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_code_execution_servers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Playwright tests for code_execution server type UI: section toggle,
CodeMirror editor lazy-init, JSON template buttons, CRUD, and edit flow.
"""

# Standard
import re
import uuid

# Third-Party
from playwright.sync_api import expect
from playwright.sync_api import Error as PlaywrightError
import pytest

# Local
from ..pages.admin_utils import cleanup_server, find_server
from ..pages.servers_page import ServersPage


def _select_code_execution_type(servers_page: ServersPage) -> None:
    """Select the code_execution server type and wait for the section to appear."""
    page = servers_page.page
    page.select_option("#server-type", "code_execution")
    page.wait_for_selector("#server-code-execution-section:not(.hidden)", timeout=5000)


def _get_editor_value(page, var_name: str) -> str:
    """Read the current value from a CodeMirror editor global variable."""
    return page.evaluate(
        "(name) => { const ed = window[name];"
        " return ed && typeof ed.getValue === 'function' ? ed.getValue() : ''; }",
        var_name,
    )


class TestCodeExecutionServerUI:
    """UI tests for the code_execution server type in the admin panel."""

    @pytest.fixture(autouse=True)
    def _navigate(self, servers_page: ServersPage):
        """Navigate to Virtual Servers tab; skip entire class if feature is off."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)
        has_option = servers_page.page.evaluate(
            "() => { const el = document.getElementById('server-type');"
            " return !!el && Array.from(el.options).some(o => o.value === 'code_execution'); }"
        )
        if not has_option:
            pytest.skip("CODE_EXECUTION_ENABLED is false in the running instance")

    def test_server_type_select_has_code_execution(self, servers_page: ServersPage):
        """The server-type select contains both standard and code_execution options."""
        options = servers_page.page.eval_on_selector(
            "#server-type", "el => Array.from(el.options).map(o => o.value)"
        )
        assert "standard" in options
        assert "code_execution" in options

    def test_code_execution_section_hidden_by_default(self, servers_page: ServersPage):
        """The code execution section is hidden when server type is standard."""
        section = servers_page.page.locator("#server-code-execution-section")
        expect(section).to_be_hidden()

    def test_code_execution_section_visible_on_select(self, servers_page: ServersPage):
        """Selecting code_execution reveals the code execution config section."""
        _select_code_execution_type(servers_page)
        section = servers_page.page.locator("#server-code-execution-section")
        expect(section).to_be_visible()

    def test_section_hides_on_switch_back(self, servers_page: ServersPage):
        """Switching back to standard hides the code execution section."""
        page = servers_page.page
        _select_code_execution_type(servers_page)
        page.select_option("#server-type", "standard")
        section = page.locator("#server-code-execution-section")
        expect(section).to_be_hidden()

    def test_codemirror_editors_lazy_initialized(self, servers_page: ServersPage):
        """CodeMirror editors for JSON fields are created when section is revealed."""
        page = servers_page.page
        _select_code_execution_type(servers_page)
        # Allow lazy-init via requestAnimationFrame + refreshEditors setTimeout
        page.wait_for_timeout(500)
        for var_name in (
            "serverMountRulesEditor",
            "serverSandboxPolicyEditor",
            "serverTokenizationEditor",
        ):
            exists = page.evaluate(
                f"() => !!window['{var_name}'] && typeof window['{var_name}'].getValue === 'function'"
            )
            assert exists, f"CodeMirror editor {var_name} was not initialized"

    def test_insert_mount_rules_template(self, servers_page: ServersPage):
        """'Insert editable JSON template' for mount rules populates the editor."""
        page = servers_page.page
        _select_code_execution_type(servers_page)
        page.wait_for_timeout(500)
        buttons = page.locator(
            "#server-code-execution-section button:has-text('Insert editable JSON template')"
        )
        buttons.nth(0).click()
        page.wait_for_timeout(200)
        value = _get_editor_value(page, "serverMountRulesEditor")
        assert "include_tags" in value

    def test_insert_sandbox_policy_template(self, servers_page: ServersPage):
        """'Insert editable JSON template' for sandbox policy populates the editor."""
        page = servers_page.page
        _select_code_execution_type(servers_page)
        page.wait_for_timeout(500)
        buttons = page.locator(
            "#server-code-execution-section button:has-text('Insert editable JSON template')"
        )
        buttons.nth(1).click()
        page.wait_for_timeout(200)
        value = _get_editor_value(page, "serverSandboxPolicyEditor")
        assert "max_execution_time_ms" in value

    def test_insert_tokenization_template(self, servers_page: ServersPage):
        """'Insert editable JSON template' for tokenization populates the editor."""
        page = servers_page.page
        _select_code_execution_type(servers_page)
        page.wait_for_timeout(500)
        buttons = page.locator(
            "#server-code-execution-section button:has-text('Insert editable JSON template')"
        )
        buttons.nth(2).click()
        page.wait_for_timeout(200)
        value = _get_editor_value(page, "serverTokenizationEditor")
        assert "bidirectional" in value

    def test_stub_language_options(self, servers_page: ServersPage):
        """The stub language select offers Auto, typescript, and python."""
        page = servers_page.page
        _select_code_execution_type(servers_page)
        options = page.eval_on_selector(
            "#server-stub-language",
            "el => Array.from(el.options).map(o => o.value)",
        )
        assert "" in options  # Auto (runtime default)
        assert "typescript" in options
        assert "python" in options

    def test_create_code_execution_server(self, servers_page: ServersPage):
        """Create a code_execution server end-to-end and verify via API."""
        page = servers_page.page
        name = f"code-exec-e2e-{uuid.uuid4().hex[:8]}"

        # Fill basic fields
        servers_page.fill_locator(servers_page.server_name_input, name)

        # Select code_execution type
        _select_code_execution_type(servers_page)
        page.wait_for_timeout(500)

        # Insert sandbox policy template (demonstrates template + submit flow)
        buttons = page.locator(
            "#server-code-execution-section button:has-text('Insert editable JSON template')"
        )
        buttons.nth(1).click()
        page.wait_for_timeout(200)

        # Submit
        with page.expect_response(
            lambda r: "/admin/servers" in r.url and r.request.method == "POST"
        ) as resp:
            servers_page.click_locator(servers_page.add_server_btn)
        assert resp.value.status < 400

        # Verify creation via API
        created = find_server(page, name)
        assert created is not None
        assert created.get("type") == "code_execution"

        # Cleanup
        cleanup_server(page, name)


def _reload_with_retry(page, attempts: int = 3) -> None:
    """Reload with retries for transient navigation-abort races."""
    for attempt in range(attempts):
        try:
            page.reload(wait_until="domcontentloaded")
            return
        except PlaywrightError as exc:
            message = str(exc)
            is_nav_race = "ERR_ABORTED" in message or "frame was detached" in message
            if not is_nav_race or attempt == attempts - 1:
                raise
            page.wait_for_timeout(300)


def _stabilize_after_server_create(servers_page: ServersPage) -> None:
    """Stabilize the UI after create-server submit + redirect."""
    servers_page.page.wait_for_load_state("domcontentloaded")
    _reload_with_retry(servers_page.page)
    servers_page.navigate_to_servers_tab()
    servers_page.wait_for_servers_table_loaded()


def _open_edit_for_server(servers_page: ServersPage, server_name: str) -> None:
    """Find a server row and click its Edit button, waiting for the edit form."""
    page = servers_page.page

    # Ensure 100 items per page so the server is visible
    pagination_select = page.locator("#servers-pagination-controls select")
    pagination_select.select_option("100")
    page.wait_for_load_state("domcontentloaded")

    server_row = page.locator(f'[data-testid="server-item"]:has-text("{server_name}")').first
    expect(server_row).to_be_visible(timeout=10000)

    edit_btn = server_row.locator('button:has-text("Edit")')
    assert edit_btn.count() > 0, f"Edit button not found for server {server_name}"

    # Click Edit and wait for the API fetch + form population
    with page.expect_response(
        lambda resp: (re.search(r"/admin/servers/[0-9a-f]", resp.url) is not None and resp.request.method == "GET"),
        timeout=15000,
    ):
        edit_btn.click()

    # Wait for edit form to be visible
    page.wait_for_selector("#server-edit-modal:not(.hidden)", state="visible", timeout=10000)


class TestCodeExecutionServerEdit:
    """Edit-flow regression tests for code_execution servers.

    Ensures the edit form correctly displays and preserves code_execution
    server type, including when the code_execution option is disabled in
    the template (CODE_EXECUTION_ENABLED=false).
    """

    @pytest.fixture(autouse=True)
    def _navigate(self, servers_page: ServersPage):
        """Navigate to Virtual Servers tab; skip if feature is off."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)
        has_option = servers_page.page.evaluate(
            "() => { const el = document.getElementById('server-type');"
            " return !!el && Array.from(el.options).some(o => o.value === 'code_execution'); }"
        )
        if not has_option:
            pytest.skip("CODE_EXECUTION_ENABLED is false in the running instance")

    @pytest.fixture()
    def code_exec_server(self, servers_page: ServersPage):
        """Create a code_execution server for edit tests, clean up after."""
        page = servers_page.page
        name = f"edit-ce-{uuid.uuid4().hex[:8]}"

        servers_page.fill_locator(servers_page.server_name_input, name)
        _select_code_execution_type(servers_page)
        page.wait_for_timeout(500)

        with page.expect_response(
            lambda r: "/admin/servers" in r.url and r.request.method == "POST"
        ) as resp:
            servers_page.click_locator(servers_page.add_server_btn)
        assert resp.value.status < 400

        _stabilize_after_server_create(servers_page)

        yield name

        cleanup_server(page, name)

    def test_edit_form_shows_code_execution_type(self, servers_page: ServersPage, code_exec_server: str):
        """Edit form select shows code_execution for a code_execution server."""
        _open_edit_for_server(servers_page, code_exec_server)

        select_value = servers_page.page.eval_on_selector(
            "#edit-server-type", "el => el.value"
        )
        assert select_value == "code_execution", (
            f"Expected edit form to show 'code_execution', got '{select_value}'"
        )

    def test_edit_form_shows_code_execution_section(self, servers_page: ServersPage, code_exec_server: str):
        """Edit form reveals the code execution config section."""
        _open_edit_for_server(servers_page, code_exec_server)

        section = servers_page.page.locator("#edit-server-code-execution-section")
        expect(section).to_be_visible()

    def test_edit_form_disabled_option_regression(self, servers_page: ServersPage, code_exec_server: str):
        """Regression: edit form shows code_execution even when the option is disabled.

        When CODE_EXECUTION_ENABLED=false, the template renders
        <option value="code_execution" disabled>. The JS fix enables it
        before setting the value. This test simulates that scenario.
        """
        page = servers_page.page

        # Disable the code_execution option on the edit form to simulate
        # CODE_EXECUTION_ENABLED=false template rendering
        page.evaluate(
            "() => {"
            "  const opt = document.querySelector('#edit-server-type option[value=\"code_execution\"]');"
            "  if (opt) { opt.disabled = true; }"
            "  document.getElementById('edit-server-type').value = 'standard';"
            "}"
        )

        # Now open the edit form — the JS should enable the option and select it
        _open_edit_for_server(servers_page, code_exec_server)

        select_value = page.eval_on_selector("#edit-server-type", "el => el.value")
        assert select_value == "code_execution", (
            f"Expected 'code_execution' even with disabled option, got '{select_value}'"
        )

    def test_edit_save_preserves_code_execution_type(self, servers_page: ServersPage, code_exec_server: str):
        """Saving the edit form preserves the code_execution server type."""
        page = servers_page.page
        _open_edit_for_server(servers_page, code_exec_server)

        # Confirm type is code_execution before saving
        select_value = page.eval_on_selector("#edit-server-type", "el => el.value")
        assert select_value == "code_execution"

        # Click Save Changes
        save_btn = page.locator('#server-edit-modal button:has-text("Save Changes")')
        with page.expect_response(
            lambda r: "/admin/servers/" in r.url and "/edit" in r.url and r.request.method == "POST",
            timeout=15000,
        ) as resp:
            save_btn.click()
        assert resp.value.status < 400

        # Verify type is preserved via API
        page.wait_for_load_state("domcontentloaded")
        server = find_server(page, code_exec_server)
        assert server is not None, f"Server {code_exec_server} not found after save"
        assert server.get("type") == "code_execution", (
            f"Expected type 'code_execution' after save, got '{server.get('type')}'"
        )
