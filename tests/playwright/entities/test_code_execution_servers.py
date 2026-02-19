# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_code_execution_servers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Playwright tests for code_execution server type UI: section toggle,
CodeMirror editor lazy-init, JSON template buttons, and CRUD.
"""

# Standard
import uuid

# Third-Party
from playwright.sync_api import expect
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
