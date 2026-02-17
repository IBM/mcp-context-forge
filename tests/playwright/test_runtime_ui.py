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


@pytest.mark.ui
@pytest.mark.e2e
class TestRuntimeUI:
    """Runtime UI end-to-end workflow tests."""

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

    def test_runtime_panel_loads_and_has_expected_controls(self, runtime_page: RuntimePage):
        """Load runtime panel and verify core controls are rendered."""
        self._open_runtime_panel_or_skip(runtime_page)

        expect(runtime_page.runtime_panel).to_be_visible()
        expect(runtime_page.deploy_form).to_be_visible()
        expect(runtime_page.refresh_all_button).to_be_visible()
        expect(runtime_page.compatibility_button).to_be_visible()
        expect(runtime_page.deploy_submit_button).to_be_visible()
        expect(runtime_page.backends_table_body).to_be_visible()
        expect(runtime_page.guardrails_table_body).to_be_visible()
        expect(runtime_page.runtimes_table_body).to_be_visible()
        expect(runtime_page.approvals_table_body).to_be_visible()
        expect(runtime_page.deploy_source_type_select.locator('option[value="docker"]')).to_be_attached()
        expect(runtime_page.deploy_source_type_select.locator('option[value="github"]')).to_be_attached()
        expect(runtime_page.deploy_source_type_select.locator('option[value="compose"]')).to_be_attached()
        expect(runtime_page.deploy_source_type_select.locator('option[value="catalog"]')).to_be_attached()

    def test_refresh_all_button_triggers_all_runtime_api_loaders(self, runtime_page: RuntimePage):
        """Verify Refresh All triggers backend, guardrail, runtimes, and approvals reload calls."""
        self._open_runtime_panel_or_skip(runtime_page)

        page = runtime_page.page
        with (
            page.expect_response(
                lambda response: "/runtimes/backends" in response.url and response.request.method == "GET",
                timeout=30000,
            ) as backends_response,
            page.expect_response(
                lambda response: "/runtimes/guardrails" in response.url
                and "/compatibility" not in response.url
                and response.request.method == "GET",
                timeout=30000,
            ) as guardrails_response,
            page.expect_response(
                lambda response: "/runtimes?" in response.url and response.request.method == "GET",
                timeout=30000,
            ) as runtimes_response,
            page.expect_response(
                lambda response: "/runtimes/approvals?" in response.url and response.request.method == "GET",
                timeout=30000,
            ) as approvals_response,
        ):
            runtime_page.refresh_all_button.click()

        assert backends_response.value.status < 400
        assert guardrails_response.value.status < 400
        assert runtimes_response.value.status < 400
        assert approvals_response.value.status < 400

    def test_check_compatibility_button_executes_and_renders_result(self, runtime_page: RuntimePage):
        """Run compatibility check and verify result is rendered in panel."""
        self._open_runtime_panel_or_skip(runtime_page)

        with runtime_page.page.expect_response(
            lambda response: "/runtimes/guardrails/" in response.url
            and "/compatibility?backend=" in response.url
            and response.request.method == "GET",
            timeout=30000,
        ) as compatibility_response:
            runtime_page.compatibility_button.click()

        assert compatibility_response.value.status < 400

        compatibility_text = runtime_page.compatibility_result.inner_text().strip()
        assert compatibility_text
        assert "compatible" in compatibility_text.lower() or "warning" in compatibility_text.lower()

    def test_deploy_validates_missing_and_invalid_docker_images_client_side(self, runtime_page: RuntimePage):
        """Verify deploy blocks missing/invalid docker images before POST /runtimes/deploy."""
        self._open_runtime_panel_or_skip(runtime_page)

        runtime_name = f"pw-runtime-ui-validation-{uuid.uuid4().hex[:8]}"
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

    def test_deploy_runtime_from_docker_source_creates_runtime_row(self, runtime_page: RuntimePage):
        """Submit runtime deploy request and verify deployment appears in runtime table."""
        self._open_runtime_panel_or_skip(runtime_page)

        runtime_name = f"pw-runtime-ui-deploy-{uuid.uuid4().hex[:8]}"
        created_runtime_id: str | None = None

        try:
            runtime_page.fill_docker_deploy_form(
                name=runtime_name,
                image="ghcr.io/ibm/fast-time-server:0.8.0",
            )

            with runtime_page.page.expect_response(
                lambda response: "/runtimes/deploy" in response.url and response.request.method == "POST",
                timeout=60000,
            ) as deploy_response:
                runtime_page.deploy_submit_button.click()

            assert deploy_response.value.status in {200, 201}

            deploy_message = runtime_page.wait_for_deploy_message(timeout=30000)
            assert "deployment" in deploy_message.lower()

            runtime_record = runtime_page.api_find_runtime_by_name(runtime_name, retries=15, wait_ms=500)
            assert runtime_record is not None

            created_runtime_id = str(runtime_record["id"])
            expect(runtime_page.runtime_row_by_name(runtime_name)).to_be_visible(timeout=20000)
        finally:
            if not created_runtime_id:
                runtime_record = runtime_page.api_find_runtime_by_name(runtime_name, retries=2, wait_ms=300)
                if runtime_record is not None:
                    created_runtime_id = str(runtime_record["id"])
            if created_runtime_id:
                runtime_page.api_cleanup_runtime(created_runtime_id)

    def test_reject_pending_approval_from_runtime_ui(self, runtime_page: RuntimePage):
        """Create pending deployment approval and reject it through UI action button."""
        self._open_runtime_panel_or_skip(runtime_page)

        runtime_name = f"pw-runtime-ui-approval-{uuid.uuid4().hex[:8]}"
        created_runtime_id: str | None = None

        try:
            runtime_page.fill_docker_deploy_form(
                name=runtime_name,
                image="ghcr.io/ibm/fast-time-server:0.8.0",
            )

            with runtime_page.page.expect_response(
                lambda response: "/runtimes/deploy" in response.url and response.request.method == "POST",
                timeout=60000,
            ):
                runtime_page.deploy_submit_button.click()

            runtime_record = runtime_page.api_find_runtime_by_name(runtime_name, retries=15, wait_ms=500)
            assert runtime_record is not None
            created_runtime_id = str(runtime_record["id"])

            pending_approval = runtime_page.api_find_pending_approval_for_runtime(
                created_runtime_id,
                retries=15,
                wait_ms=500,
            )
            if pending_approval is None:
                pytest.skip("Environment does not produce pending approvals for this deploy path")

            approval_id = str(pending_approval["id"])

            runtime_page.approval_filter_select.select_option("all")
            with runtime_page.page.expect_response(
                lambda response: "/runtimes/approvals?" in response.url and response.request.method == "GET",
                timeout=30000,
            ):
                runtime_page.refresh_approvals_button.click()

            reject_button = runtime_page.approval_action_button(approval_id, "reject")
            expect(reject_button).to_be_visible(timeout=20000)

            runtime_page.page.once(
                "dialog",
                lambda dialog: dialog.accept("Playwright rejection validation"),
            )
            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/approvals/{approval_id}/reject" in response.url
                and response.request.method == "POST",
                timeout=30000,
            ) as reject_response:
                reject_button.click()

            assert reject_response.value.status < 400

            runtime_page.page.wait_for_timeout(1000)
            assert runtime_page.approval_action_button(approval_id, "reject").count() == 0
        finally:
            if created_runtime_id:
                runtime_page.api_cleanup_runtime(created_runtime_id)

    def test_runtime_row_refresh_and_logs_actions_call_runtime_api(self, runtime_page: RuntimePage):
        """Verify runtime row action buttons call refresh and logs runtime APIs."""
        self._open_runtime_panel_or_skip(runtime_page)

        runtime_name = f"pw-runtime-ui-actions-{uuid.uuid4().hex[:8]}"
        created_runtime_id: str | None = None

        try:
            runtime_page.fill_docker_deploy_form(
                name=runtime_name,
                image="ghcr.io/ibm/fast-time-server:0.8.0",
            )

            with runtime_page.page.expect_response(
                lambda response: "/runtimes/deploy" in response.url and response.request.method == "POST",
                timeout=60000,
            ):
                runtime_page.deploy_submit_button.click()

            runtime_record = runtime_page.api_find_runtime_by_name(runtime_name, retries=15, wait_ms=500)
            assert runtime_record is not None
            created_runtime_id = str(runtime_record["id"])

            refresh_button = runtime_page.runtime_action_button(created_runtime_id, "refresh")
            logs_button = runtime_page.runtime_action_button(created_runtime_id, "logs")
            expect(refresh_button).to_be_visible(timeout=20000)
            expect(logs_button).to_be_visible(timeout=20000)

            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/{created_runtime_id}?refresh=true" in response.url
                and response.request.method == "GET",
                timeout=30000,
            ) as refresh_response:
                refresh_button.click()

            assert refresh_response.value.status < 500

            with runtime_page.page.expect_response(
                lambda response: f"/runtimes/{created_runtime_id}/logs?tail=200" in response.url
                and response.request.method == "GET",
                timeout=30000,
            ) as logs_response:
                logs_button.click()

            assert logs_response.value.status < 500
            expect(runtime_page.logs_output).to_be_visible()
        finally:
            if created_runtime_id:
                runtime_page.api_cleanup_runtime(created_runtime_id)
