# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/runtime_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Runtime page object for secure runtime deployment UI tests.
"""

# Standard
from __future__ import annotations

import json
from typing import Any, Dict

# Third-Party
from playwright.sync_api import expect, Locator

# Local
from .base_page import BasePage


class RuntimePage(BasePage):
    """Page object for runtime deployment and approval workflows."""

    def __init__(self, page, base_url: str):
        super().__init__(page)
        self.url = f"{base_url}/admin/"

    # ==================== Top-Level Elements ====================

    @property
    def runtime_tab(self) -> Locator:
        """Runtime tab in admin sidebar."""
        return self.page.locator("#tab-runtime")

    @property
    def runtime_panel(self) -> Locator:
        """Runtime panel container."""
        return self.page.locator("#runtime-panel")

    @property
    def runtime_load_error(self) -> Locator:
        """Runtime panel load error banner."""
        return self.runtime_panel.locator("div.bg-red-50")

    # ==================== Deploy Form ====================

    @property
    def deploy_form(self) -> Locator:
        """Runtime deploy form."""
        return self.page.locator("#runtime-deploy-form")

    @property
    def deploy_name_input(self) -> Locator:
        """Runtime deploy name input."""
        return self.page.locator("#runtime-deploy-name")

    @property
    def deploy_backend_select(self) -> Locator:
        """Runtime deploy backend selector."""
        return self.page.locator("#runtime-deploy-backend")

    @property
    def deploy_source_type_select(self) -> Locator:
        """Runtime deploy source-type selector."""
        return self.page.locator("#runtime-deploy-source-type")

    @property
    def deploy_guardrails_select(self) -> Locator:
        """Runtime deploy guardrails profile selector."""
        return self.page.locator("#runtime-deploy-guardrails-profile")

    @property
    def deploy_image_input(self) -> Locator:
        """Docker image input for runtime deploy."""
        return self.page.locator("#runtime-source-image")

    @property
    def deploy_submit_button(self) -> Locator:
        """Deploy runtime submit button."""
        return self.page.locator("#runtime-deploy-submit")

    @property
    def deploy_message(self) -> Locator:
        """Deploy form result message."""
        return self.page.locator("#runtime-deploy-message")

    # ==================== Controls and Tables ====================

    @property
    def refresh_all_button(self) -> Locator:
        """Refresh-all button."""
        return self.page.locator("#runtime-refresh-all-btn")

    @property
    def refresh_approvals_button(self) -> Locator:
        """Approvals refresh button."""
        return self.page.locator("#runtime-refresh-approvals-btn")

    @property
    def refresh_runtimes_button(self) -> Locator:
        """Runtimes refresh button."""
        return self.page.locator("#runtime-refresh-runtimes-btn")

    @property
    def compatibility_button(self) -> Locator:
        """Guardrail compatibility check button."""
        return self.page.locator("#runtime-compat-check-btn")

    @property
    def compatibility_result(self) -> Locator:
        """Compatibility check result area."""
        return self.page.locator("#runtime-compat-result")

    @property
    def backends_table_body(self) -> Locator:
        """Runtime backends table body."""
        return self.page.locator("#runtime-backends-table-body")

    @property
    def guardrails_table_body(self) -> Locator:
        """Runtime guardrails table body."""
        return self.page.locator("#runtime-guardrails-table-body")

    @property
    def runtimes_table_body(self) -> Locator:
        """Runtime deployments table body."""
        return self.page.locator("#runtime-runtimes-table-body")

    @property
    def approvals_table_body(self) -> Locator:
        """Runtime approvals table body."""
        return self.page.locator("#runtime-approvals-table-body")

    @property
    def approval_filter_select(self) -> Locator:
        """Runtime approvals status filter."""
        return self.page.locator("#runtime-approval-filter-status")

    @property
    def logs_output(self) -> Locator:
        """Runtime logs output panel."""
        return self.page.locator("#runtime-logs-output")

    @property
    def clear_logs_button(self) -> Locator:
        """Clear runtime logs button."""
        return self.page.locator("#runtime-clear-logs-btn")

    @property
    def toast_notifications(self) -> Locator:
        """Transient toast notifications rendered by showNotification()."""
        return self.page.locator("div.fixed.top-4.right-4.z-50")

    # ==================== Navigation and Readiness ====================

    def navigate(self) -> None:
        """Navigate to admin page and wait for shell."""
        self.navigate_to(self.url)
        self.page.wait_for_selector('[data-testid="servers-tab"]', state="visible")

    def feature_state(self) -> Dict[str, bool]:
        """Return runtime feature flags exposed in UI globals."""
        return self.page.evaluate(
            """() => ({
                runtime_enabled: Boolean(window.RUNTIME_ENABLED),
                runtime_ui_access: Boolean(window.RUNTIME_UI_ACCESS),
                runtime_platform_admin_only: Boolean(window.RUNTIME_PLATFORM_ADMIN_ONLY),
            })"""
        )

    def runtime_ui_availability(self) -> tuple[bool, str]:
        """Check whether runtime UI is expected to be available in current session."""
        if self.runtime_tab.count() == 0:
            return False, "Runtime tab is not present in this UI configuration"

        state = self.feature_state()
        if not state.get("runtime_enabled", False):
            return False, "Runtime feature flag is disabled"
        if not state.get("runtime_ui_access", False):
            return False, "Runtime UI access is disabled for this user"
        return True, ""

    def navigate_to_runtime_tab(self) -> None:
        """Navigate to runtime tab and wait for panel visibility."""
        self.sidebar.click_runtime_tab()
        self.wait_for_runtime_panel_loaded()

    def wait_for_runtime_panel_loaded(self, timeout: int = 60000) -> None:
        """Wait for runtime panel to render either form content or an error banner."""
        self.page.wait_for_function(
            """() => {
                const panel = document.getElementById("runtime-panel");
                if (!panel || panel.classList.contains("hidden")) return false;
                const hasForm = Boolean(panel.querySelector("#runtime-deploy-form"));
                const hasError = panel.textContent.includes("Failed to load runtime panel");
                return hasForm || hasError;
            }""",
            timeout=timeout,
        )

    def wait_for_runtime_data_loaded(self, timeout: int = 60000) -> None:
        """Wait until all runtime table sections finish initial loading."""
        self.page.wait_for_function(
            """() => {
                const hasReadyText = (id, loadingMarker) => {
                    const el = document.getElementById(id);
                    if (!el) return false;
                    return !el.textContent.includes(loadingMarker);
                };
                return (
                    hasReadyText("runtime-backends-table-body", "Loading backends") &&
                    hasReadyText("runtime-guardrails-table-body", "Loading guardrail profiles") &&
                    hasReadyText("runtime-runtimes-table-body", "Loading runtimes") &&
                    hasReadyText("runtime-approvals-table-body", "Loading approvals")
                );
            }""",
            timeout=timeout,
        )

    # ==================== Deploy Helpers ====================

    def fill_docker_deploy_form(self, name: str, image: str) -> None:
        """Populate deploy form with Docker source values."""
        self.deploy_name_input.fill(name)
        self.deploy_source_type_select.select_option("docker")
        self.deploy_image_input.fill(image)

    def wait_for_deploy_message(self, timeout: int = 15000) -> str:
        """Wait for deploy status text and return normalized message."""
        self.page.wait_for_function(
            """() => {
                const el = document.getElementById("runtime-deploy-message");
                return Boolean(el && el.textContent && el.textContent.trim().length > 0);
            }""",
            timeout=timeout,
        )
        return self.deploy_message.inner_text().strip()

    def runtime_row_by_name(self, name: str) -> Locator:
        """Return locator for runtime table row matching runtime name."""
        return self.runtimes_table_body.locator(
            "tr",
            has=self.page.locator("div.font-medium", has_text=name),
        )

    def runtime_action_button(self, runtime_id: str, action: str) -> Locator:
        """Return runtime action button locator for a specific runtime."""
        return self.page.locator(
            f'button[data-runtime-action="{action}"][data-runtime-id="{runtime_id}"]'
        )

    def enabled_runtime_action_buttons(self, action: str) -> Locator:
        """Return all enabled runtime action buttons for a given action."""
        return self.page.locator(
            f'button[data-runtime-action="{action}"]:not([disabled])'
        )

    def approval_action_button(self, approval_id: str, action: str) -> Locator:
        """Return approval action button locator for a specific approval request."""
        return self.page.locator(
            f'button[data-approval-action="{action}"][data-approval-id="{approval_id}"]'
        )

    # ==================== API Helpers for Cleanup and Verification ====================

    def _auth_headers(self) -> Dict[str, str]:
        """Build API auth headers from browser session cookie."""
        cookies = self.page.context.cookies()
        jwt_cookie = next((cookie for cookie in cookies if cookie.get("name") == "jwt_token"), None)
        if not jwt_cookie:
            return {}
        return {"Authorization": f"Bearer {jwt_cookie['value']}"}

    def api_list_runtimes(self, limit: int = 200) -> list[Dict[str, Any]]:
        """Return runtime deployments via runtime API."""
        response = self.page.request.get(f"/runtimes?limit={limit}", headers=self._auth_headers())
        expect(response).to_be_ok()
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        runtimes = payload.get("runtimes", [])
        return runtimes if isinstance(runtimes, list) else []

    def api_list_approvals(self, status_filter: str = "all", limit: int = 200) -> list[Dict[str, Any]]:
        """Return runtime approvals via runtime API."""
        response = self.page.request.get(
            f"/runtimes/approvals?status_filter={status_filter}&limit={limit}",
            headers=self._auth_headers(),
        )
        expect(response).to_be_ok()
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        approvals = payload.get("approvals", [])
        return approvals if isinstance(approvals, list) else []

    def api_find_runtime_by_name(self, name: str, retries: int = 10, wait_ms: int = 400) -> Dict[str, Any] | None:
        """Find runtime by name with retries for eventual consistency."""
        for _ in range(retries):
            for runtime in self.api_list_runtimes():
                if runtime.get("name") == name:
                    return runtime
            self.page.wait_for_timeout(wait_ms)
        return None

    def api_get_runtime(self, runtime_id: str, refresh: bool = False) -> Dict[str, Any]:
        """Fetch a runtime deployment by id."""
        query = "?refresh=true" if refresh else ""
        response = self.page.request.get(
            f"/runtimes/{runtime_id}{query}",
            headers=self._auth_headers(),
        )
        expect(response).to_be_ok()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def api_find_pending_approval_for_runtime(
        self, runtime_id: str, retries: int = 10, wait_ms: int = 400
    ) -> Dict[str, Any] | None:
        """Find pending approval record for a runtime deployment id."""
        for _ in range(retries):
            for approval in self.api_list_approvals(status_filter="all"):
                if approval.get("runtime_deployment_id") == runtime_id and approval.get("status") == "pending":
                    return approval
            self.page.wait_for_timeout(wait_ms)
        return None

    def api_reject_approval(self, approval_id: str, reason: str) -> None:
        """Reject a runtime approval by id."""
        response = self.page.request.post(
            f"/runtimes/approvals/{approval_id}/reject",
            headers={"Content-Type": "application/json", **self._auth_headers()},
            data=json.dumps({"reason": reason}),
        )
        expect(response).to_be_ok()

    def api_delete_runtime(self, runtime_id: str) -> None:
        """Delete runtime deployment by id."""
        response = self.page.request.delete(f"/runtimes/{runtime_id}", headers=self._auth_headers())
        assert response.status in {200, 204}, f"Failed to delete runtime {runtime_id}: HTTP {response.status}"

    def api_cleanup_runtime(self, runtime_id: str, rejection_reason: str = "Playwright runtime cleanup") -> None:
        """Reject any pending approvals for a runtime, then delete the runtime."""
        approvals = self.api_list_approvals(status_filter="all")
        for approval in approvals:
            if approval.get("runtime_deployment_id") != runtime_id:
                continue
            if approval.get("status") == "pending":
                self.api_reject_approval(str(approval["id"]), rejection_reason)
        self.api_delete_runtime(runtime_id)

    def runtime_short_id(self, runtime_id: str, size: int = 12) -> str:
        """Return short runtime id text used in table rows."""
        if not runtime_id:
            return "-"
        if len(runtime_id) <= size:
            return runtime_id
        return f"{runtime_id[:size]}..."
