# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_runtime_ui.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end Playwright tests for runtime deployment UI workflows.
"""

# Standard
import uuid

# Third-Party
from playwright.sync_api import expect
import pytest

# Local
from .pages.runtime_page import RuntimePage

DOCKER_RUNTIME_IMAGE = "ghcr.io/ibm/fast-time-server:0.8.0"


@pytest.mark.ui
@pytest.mark.e2e
class TestRuntimeUI:
    """Runtime UI end-to-end workflow tests (Docker-focused)."""

    @staticmethod
    def _open_runtime_panel_or_skip(runtime_page: RuntimePage) -> None:
        """Open runtime tab and skip test if feature is unavailable."""
        runtime_page.navigate()
        available, reason = runtime_page.runtime_ui_availability()
        if not available:
            pytest.skip(reason)

        runtime_page.navigate_to_runtime_tab()

        if runtime_page.runtime_load_error.is_visible():
            pytest.skip(
                f"Runtime panel load failed in this environment: {runtime_page.runtime_load_error.inner_text().strip()}"
            )

        runtime_page.wait_for_runtime_data_loaded()

    @staticmethod
    def _runtime_name(suffix: str) -> str:
        """Generate unique runtime name for tests."""
        return f"pw-runtime-ui-{suffix}-{uuid.uuid4().hex[:8]}"

    def _deploy_runtime_via_ui(
        self, runtime_page: RuntimePage, runtime_name: str
    ) -> str:
        """Deploy a Docker runtime from UI and return runtime id."""
        runtime_page.fill_docker_deploy_form(
            name=runtime_name,
            image=DOCKER_RUNTIME_IMAGE,
        )

        with runtime_page.page.expect_response(
            lambda response: "/runtimes/deploy" in response.url
            and response.request.method == "POST",
            timeout=60000,
        ) as deploy_response:
            runtime_page.deploy_submit_button.click()

        assert deploy_response.value.status in {200, 201}
        deploy_message = runtime_page.wait_for_deploy_message(timeout=30000)
        assert "deployment" in deploy_message.lower()

        runtime_record = runtime_page.api_find_runtime_by_name(
            runtime_name, retries=15, wait_ms=500
        )
        assert runtime_record is not None, "Runtime not found after deploy submit"
        return str(runtime_record["id"])

    def _find_pending_approval_or_skip(
        self, runtime_page: RuntimePage, runtime_id: str
    ) -> str:
        """Find pending approval for runtime id or skip test."""
        pending_approval = runtime_page.api_find_pending_approval_for_runtime(
            runtime_id,
            retries=15,
            wait_ms=500,
        )
        if pending_approval is None:
            pytest.skip("Environment does not produce pending approvals for this Docker deploy path")
        return str(pending_approval["id"])

    def _show_all_approvals(self, runtime_page: RuntimePage) -> None:
        """Set approvals filter to all and refresh table."""
        runtime_page.approval_filter_select.select_option("all")
        with runtime_page.page.expect_response(
            lambda response: "/runtimes/approvals?" in response.url
            and response.request.method == "GET",
            timeout=30000,
        ):
            runtime_page.refresh_approvals_button.click()

    def test_runtime_panel_loads_and_has_expected_controls(
        self, runtime_page: RuntimePage
    ):
        """Load runtime panel and verify core controls are rendered."""
        self._open_runtime_panel_or_skip(runtime_page)

        expect(runtime_page.runtime_panel).to_be_visible()
        expect(runtime_page.deploy_form).to_be_visible()
        expect(runtime_page.refresh_all_button).to_be_visible()
        expect(runtime_page.compatibility_button).to_be_visible()
        expect(runtime_page.deploy_submit_button).to_be_visible()
        expect(runtime_page.clear_logs_button).to_be_visible()
        expect(runtime_page.backends_table_body).to_be_visible()
        expect(runtime_page.guardrails_table_body).to_be_visible()
        expect(runtime_page.runtimes_table_body).to_be_visible()
        expect(runtime_page.approvals_table_body).to_be_visible()
        expect(
            runtime_page.deploy_source_type_select.locator('option[value="docker"]')
        ).to_be_attached()
        expect(
            runtime_page.deploy_source_type_select.locator('option[value="github"]')
        ).to_be_attached()
        expect(
            runtime_page.deploy_source_type_select.locator('option[value="compose"]')
        ).to_be_attached()
        expect(
            runtime_page.deploy_source_type_select.locator('option[value="catalog"]')
        ).to_be_attached()

    def test_refresh_all_button_triggers_all_runtime_api_loaders_and_refreshes_tables(
        self, runtime_page: RuntimePage
    ):
        """Verify Refresh All calls all runtime loaders and leaves tables in ready state."""
        self._open_runtime_panel_or_skip(runtime_page)

        with (
            runtime_page.page.expect_response(
                lambda response: "/runtimes/backends" in response.url
                and response.request.method == "GET",
                timeout=30000,
            ) as backends_response,
            runtime_page.page.expect_response(
                lambda response: "/runtimes/guardrails" in response.url
                and "/compatibility" not in response.url
                and response.request.method == "GET",
                timeout=30000,
            ) as guardrails_response,
            runtime_page.page.expect_response(
                lambda response: "/runtimes?" in response.url
                and response.request.method == "GET",
                timeout=30000,
            ) as runtimes_response,
            runtime_page.page.expect_response(
                lambda response: "/runtimes/approvals?" in response.url
                and response.request.method == "GET",
                timeout=30000,
            ) as approvals_response,
        ):
            runtime_page.refresh_all_button.click()

        assert backends_response.value.status < 400
        assert guardrails_response.value.status < 400
        assert runtimes_response.value.status < 400
        assert approvals_response.value.status < 400

        runtime_page.wait_for_runtime_data_loaded(timeout=30000)
        assert "loading" not in runtime_page.backends_table_body.inner_text().lower()
        assert "loading" not in runtime_page.guardrails_table_body.inner_text().lower()
        assert "loading" not in runtime_page.runtimes_table_body.inner_text().lower()
        assert "loading" not in runtime_page.approvals_table_body.inner_text().lower()

    def test_check_compatibility_button_executes_and_renders_useful_result(
        self, runtime_page: RuntimePage
    ):
        """Run compatibility check and verify rendered message matches API payload semantics."""
        self._open_runtime_panel_or_skip(runtime_page)

        with runtime_page.page.expect_response(
            lambda response: "/runtimes/guardrails/" in response.url
            and "/compatibility?backend=" in response.url
            and response.request.method == "GET",
            timeout=30000,
        ) as compatibility_response:
            runtime_page.compatibility_button.click()

        response = compatibility_response.value
        assert response.status < 400
        payload = response.json()

        compatibility_text = runtime_page.compatibility_result.inner_text().strip()
        assert compatibility_text

        compatible = bool(payload.get("compatible", False))
        warnings = payload.get("warnings", [])
        if compatible:
            assert "compatible" in compatibility_text.lower()
        else:
            assert "warning" in compatibility_text.lower()
            assert isinstance(warnings, list)

    def test_deploy_validates_missing_and_invalid_docker_images_client_side(
        self, runtime_page: RuntimePage
    ):
        """Verify deploy blocks missing/invalid docker images before POST /runtimes/deploy."""
        self._open_runtime_panel_or_skip(runtime_page)

        runtime_name = self._runtime_name("validation")
        runtime_page.deploy_name_input.fill(runtime_name)
        runtime_page.deploy_source_type_select.select_option("docker")

        deploy_requests: list[str] = []

        def _capture_deploy_request(request) -> None:
            if request.method == "POST" and "/runtimes/deploy" in request.url:
                deploy_requests.append(request.url)

        runtime_page.page.on("request", _capture_deploy_request)
        try:
            runtime_page.deploy_image_input.fill("")
            runtime_page.deploy_submit_button.click()
            missing_image_message = runtime_page.wait_for_deploy_message()
            assert "docker image is required" in missing_image_message.lower()

            runtime_page.deploy_image_input.fill("bad image ref")
            runtime_page.deploy_submit_button.click()
            invalid_image_message = runtime_page.wait_for_deploy_message()
            assert "valid container reference" in invalid_image_message.lower()

            runtime_page.page.wait_for_timeout(600)
            assert not deploy_requests
        finally:
            runtime_page.page.remove_listener("request", _capture_deploy_request)

    def test_deploy_runtime_from_docker_source_creates_runtime_row(
        self, runtime_page: RuntimePage
    ):
        """Submit runtime deploy request and verify deployment appears in runtime table."""
        self._open_runtime_panel_or_skip(runtime_page)

        runtime_name = self._runtime_name("deploy")
        runtime_id: str | None = None

        try:
            runtime_id = self._deploy_runtime_via_ui(runtime_page, runtime_name)
            expect(runtime_page.runtime_row_by_name(runtime_name)).to_be_visible(
                timeout=20000
            )
        finally:
            if runtime_id:
                runtime_page.api_cleanup_runtime(runtime_id)

    def test_runtime_actions_refresh_logs_clear_and_delete_for_deployment(
        self, runtime_page: RuntimePage
    ):
        """Verify refresh/logs/clear/delete action buttons work for a deployment row."""
        self._open_runtime_panel_or_skip(runtime_page)

        runtime_name = self._runtime_name("actions")
        runtime_id: str | None = None

        try:
            runtime_id = self._deploy_runtime_via_ui(runtime_page, runtime_name)

            refresh_button = runtime_page.runtime_action_button(runtime_id, "refresh")
            logs_button = runtime_page.runtime_action_button(runtime_id, "logs")
            start_button = runtime_page.runtime_action_button(runtime_id, "start")
            stop_button = runtime_page.runtime_action_button(runtime_id, "stop")
            delete_button = runtime_page.runtime_action_button(runtime_id, "delete")

            expect(refresh_button).to_be_visible(timeout=20000)
            expect(logs_button).to_be_visible(timeout=20000)
            expect(start_button).to_be_disabled()
            expect(stop_button).to_be_disabled()
            expect(delete_button).to_be_visible()

            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/{runtime_id}?refresh=true" in response.url
                and response.request.method == "GET",
                timeout=30000,
            ) as refresh_response:
                refresh_button.click()
            assert refresh_response.value.status < 500

            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/{runtime_id}/logs?tail=200" in response.url
                and response.request.method == "GET",
                timeout=30000,
            ) as logs_response:
                logs_button.click()
            assert logs_response.value.status < 500

            logs_text = runtime_page.logs_output.inner_text().strip()
            assert logs_text
            assert logs_text.lower() != "no logs loaded."

            runtime_page.clear_logs_button.click()
            expect(runtime_page.logs_output).to_have_text("No logs loaded.")

            runtime_page.page.once("dialog", lambda dialog: dialog.accept())
            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/{runtime_id}" in response.url
                and response.request.method == "DELETE",
                timeout=30000,
            ) as delete_response:
                delete_button.click()

            assert delete_response.value.status < 400

            runtime_page.page.wait_for_timeout(1000)
            runtime_after_delete = runtime_page.api_find_runtime_by_name(
                runtime_name, retries=6, wait_ms=300
            )
            assert runtime_after_delete is not None
            assert runtime_after_delete.get("status") == "deleted"
        finally:
            if runtime_id:
                runtime_page.api_cleanup_runtime(runtime_id)

    def test_reject_approval_action_updates_runtime_and_start_button_flow(
        self, runtime_page: RuntimePage
    ):
        """Reject approval in UI, then verify start action request path is wired."""
        self._open_runtime_panel_or_skip(runtime_page)

        runtime_name = self._runtime_name("reject")
        runtime_id: str | None = None

        try:
            runtime_id = self._deploy_runtime_via_ui(runtime_page, runtime_name)
            approval_id = self._find_pending_approval_or_skip(runtime_page, runtime_id)

            self._show_all_approvals(runtime_page)
            reject_button = runtime_page.approval_action_button(approval_id, "reject")
            expect(reject_button).to_be_visible(timeout=20000)

            runtime_page.page.once(
                "dialog", lambda dialog: dialog.accept("Playwright rejection validation")
            )
            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/approvals/{approval_id}/reject"
                in response.url
                and response.request.method == "POST",
                timeout=30000,
            ) as reject_response:
                reject_button.click()

            assert reject_response.value.status < 400

            runtime_page.page.wait_for_timeout(1000)
            runtime_after_reject = runtime_page.api_find_runtime_by_name(
                runtime_name, retries=10, wait_ms=300
            )
            assert runtime_after_reject is not None
            assert runtime_after_reject.get("approval_status") == "rejected"
            assert runtime_after_reject.get("status") in {"error", "deleted"}

            start_button = runtime_page.runtime_action_button(runtime_id, "start")
            expect(start_button).to_be_visible()

            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/{runtime_id}/start" in response.url
                and response.request.method == "POST",
                timeout=30000,
            ) as start_response:
                start_button.click()

            assert start_response.value.status < 500
        finally:
            if runtime_id:
                runtime_page.api_cleanup_runtime(runtime_id)

    def test_approve_approval_action_sends_request_and_handles_result(
        self, runtime_page: RuntimePage
    ):
        """Approve action should call API and surface either success or meaningful backend error."""
        self._open_runtime_panel_or_skip(runtime_page)

        runtime_name = self._runtime_name("approve")
        runtime_id: str | None = None

        try:
            runtime_id = self._deploy_runtime_via_ui(runtime_page, runtime_name)
            approval_id = self._find_pending_approval_or_skip(runtime_page, runtime_id)

            self._show_all_approvals(runtime_page)
            approve_button = runtime_page.approval_action_button(approval_id, "approve")
            expect(approve_button).to_be_visible(timeout=20000)

            runtime_page.page.once(
                "dialog", lambda dialog: dialog.accept("Playwright approval validation")
            )
            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/approvals/{approval_id}/approve"
                in response.url
                and response.request.method == "POST",
                timeout=30000,
            ) as approve_response:
                approve_button.click()

            status_code = approve_response.value.status
            if status_code < 400:
                runtime_page.page.wait_for_timeout(1000)
                runtime_after_approve = runtime_page.api_find_runtime_by_name(
                    runtime_name, retries=10, wait_ms=300
                )
                assert runtime_after_approve is not None
                assert runtime_after_approve.get("approval_status") in {
                    "approved",
                    "rejected",
                    "pending",
                }
            else:
                expect(
                    runtime_page.toast_notifications.filter(
                        has_text="Approval action failed"
                    ).first
                ).to_be_visible(timeout=5000)
        finally:
            if runtime_id:
                runtime_page.api_cleanup_runtime(runtime_id)

    def test_full_docker_lifecycle_via_ui_actions(
        self, runtime_page: RuntimePage
    ):
        """Run full UI lifecycle: deploy, approve, logs/clear, stop/start/stop, delete."""
        self._open_runtime_panel_or_skip(runtime_page)

        runtime_name = self._runtime_name("full")
        runtime_id: str | None = None

        try:
            runtime_id = self._deploy_runtime_via_ui(runtime_page, runtime_name)
            approval_id = self._find_pending_approval_or_skip(runtime_page, runtime_id)

            self._show_all_approvals(runtime_page)
            approve_button = runtime_page.approval_action_button(approval_id, "approve")
            expect(approve_button).to_be_visible(timeout=20000)

            runtime_page.page.once(
                "dialog", lambda dialog: dialog.accept("Playwright full lifecycle approval")
            )
            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/approvals/{approval_id}/approve"
                in response.url
                and response.request.method == "POST",
                timeout=30000,
            ) as approve_response:
                approve_button.click()
            assert approve_response.value.status < 400

            runtime_status = None
            runtime_error = None
            for _ in range(30):
                runtime_payload = runtime_page.api_get_runtime(runtime_id, refresh=True)
                runtime_status = runtime_payload.get("status")
                runtime_error = runtime_payload.get("error_message")
                if runtime_status in {"running", "connected"}:
                    break
                if runtime_status == "error":
                    pytest.fail(f"Runtime failed after approval: {runtime_error}")
                runtime_page.page.wait_for_timeout(1000)
            assert runtime_status in {"running", "connected"}

            runtime_page.refresh_runtimes_button.click()
            runtime_page.page.wait_for_timeout(800)

            logs_button = runtime_page.runtime_action_button(runtime_id, "logs")
            stop_button = runtime_page.runtime_action_button(runtime_id, "stop")
            start_button = runtime_page.runtime_action_button(runtime_id, "start")
            delete_button = runtime_page.runtime_action_button(runtime_id, "delete")

            expect(logs_button).to_be_visible(timeout=20000)
            expect(stop_button).to_be_enabled(timeout=20000)
            expect(start_button).to_be_disabled()
            expect(delete_button).to_be_visible()

            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/{runtime_id}/logs?tail=200" in response.url
                and response.request.method == "GET",
                timeout=30000,
            ) as logs_response:
                logs_button.click()
            assert logs_response.value.status < 400

            runtime_page.clear_logs_button.click()
            expect(runtime_page.logs_output).to_have_text("No logs loaded.")

            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/{runtime_id}/stop" in response.url
                and response.request.method == "POST",
                timeout=30000,
            ) as stop_response:
                stop_button.click()
            assert stop_response.value.status < 400

            runtime_page.refresh_runtimes_button.click()
            runtime_page.page.wait_for_timeout(800)
            expect(runtime_page.runtime_action_button(runtime_id, "start")).to_be_enabled(timeout=20000)

            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/{runtime_id}/start" in response.url
                and response.request.method == "POST",
                timeout=30000,
            ) as start_response:
                runtime_page.runtime_action_button(runtime_id, "start").click()
            assert start_response.value.status < 400

            runtime_page.refresh_runtimes_button.click()
            runtime_page.page.wait_for_timeout(800)
            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/{runtime_id}/stop" in response.url
                and response.request.method == "POST",
                timeout=30000,
            ) as second_stop_response:
                runtime_page.runtime_action_button(runtime_id, "stop").click()
            assert second_stop_response.value.status < 400

            runtime_page.page.once("dialog", lambda dialog: dialog.accept())
            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/{runtime_id}" in response.url
                and response.request.method == "DELETE",
                timeout=30000,
            ) as delete_response:
                runtime_page.runtime_action_button(runtime_id, "delete").click()
            assert delete_response.value.status < 400

            runtime_page.page.wait_for_timeout(1000)
            runtime_after_delete = runtime_page.api_get_runtime(runtime_id)
            assert runtime_after_delete.get("status") == "deleted"
        finally:
            if runtime_id:
                runtime_page.api_cleanup_runtime(runtime_id)

    def test_stop_action_when_running_runtime_is_available(
        self, runtime_page: RuntimePage
    ):
        """If a running/connected deployment exists, stop action should call /stop."""
        self._open_runtime_panel_or_skip(runtime_page)

        enabled_stop_buttons = runtime_page.enabled_runtime_action_buttons("stop")
        if enabled_stop_buttons.count() == 0:
            pytest.skip("No runtime in running/connected/deploying state available for stop action test")

        target_button = enabled_stop_buttons.first
        runtime_id = target_button.get_attribute("data-runtime-id")
        if not runtime_id:
            pytest.skip("Stop action button does not include runtime id")

        with runtime_page.page.expect_response(
            lambda response: f"/runtimes/{runtime_id}/stop" in response.url
            and response.request.method == "POST",
            timeout=30000,
        ) as stop_response:
            target_button.click()

        assert stop_response.value.status < 500
