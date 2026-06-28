# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/common/test_elicitation_models.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Stefano Amorelli

Unit tests for elicitation Pydantic models, including URL-mode (SEP-1036).
"""

import pytest
from pydantic import ValidationError

from mcpgateway.common.models import (
    ElicitationCapability,
    ElicitationRequiredErrorData,
    ElicitCompleteNotificationParams,
    ElicitRequestParams,
    ElicitRequestURLParams,
    ElicitResult,
    URL_ELICITATION_REQUIRED,
)


def test_url_elicitation_required_error_code():
    """SEP-1036 defines URLElicitationRequiredError as JSON-RPC code -32042."""
    assert URL_ELICITATION_REQUIRED == -32042


# --------------------------------------------------------------------------- #
# FORM MODE
# --------------------------------------------------------------------------- #


def test_form_params_default_mode_and_requires_schema():
    """Form params default to mode='form' and require requestedSchema."""
    params = ElicitRequestParams(message="hi", requestedSchema={"type": "object", "properties": {}})
    assert params.mode == "form"
    assert params.requestedSchema == {"type": "object", "properties": {}}

    with pytest.raises(ValidationError):
        ElicitRequestParams(message="hi")  # requestedSchema is required


# --------------------------------------------------------------------------- #
# URL MODE (SEP-1036)
# --------------------------------------------------------------------------- #


def test_url_params_valid_and_alias_roundtrip():
    """URL params expose mode='url' and round-trip the camelCase elicitationId alias."""
    params = ElicitRequestURLParams(message="Sign in", url="https://auth.example.com/x", elicitationId="elc_1")
    assert params.mode == "url"
    assert params.url == "https://auth.example.com/x"
    assert params.elicitationId == "elc_1"

    dumped = params.model_dump(by_alias=True)
    assert dumped["mode"] == "url"
    assert dumped["elicitationId"] == "elc_1"


def test_url_params_require_url_and_id():
    """URL params must carry both url and elicitationId."""
    with pytest.raises(ValidationError):
        ElicitRequestURLParams(message="Sign in")  # missing url + elicitationId
    with pytest.raises(ValidationError):
        ElicitRequestURLParams(message="Sign in", url="https://e.example.com/x")  # missing elicitationId


def test_elicitation_required_error_data_holds_url_params():
    """ElicitationRequiredErrorData carries a list of URL-mode elicitations."""
    data = ElicitationRequiredErrorData(elicitations=[ElicitRequestURLParams(message="m", url="https://e.example.com/x", elicitationId="e1")])
    assert len(data.elicitations) == 1
    assert data.elicitations[0].mode == "url"


def test_elicit_complete_notification_params():
    """Completion-notification params surface the elicitationId being completed."""
    params = ElicitCompleteNotificationParams(elicitationId="elc_99")
    assert params.elicitationId == "elc_99"


# --------------------------------------------------------------------------- #
# CAPABILITY + RESULT
# --------------------------------------------------------------------------- #


def test_elicitation_capability_subcapabilities():
    """Capability honours form/url sub-capabilities and the legacy empty declaration."""
    cap = ElicitationCapability(form={}, url={})
    assert cap.form is not None
    assert cap.url is not None

    # Legacy empty declaration still validates (form/url default to None).
    legacy = ElicitationCapability()
    assert legacy.form is None
    assert legacy.url is None


def test_elicit_result_actions_and_list_content():
    """ElicitResult accepts list[str] content, allows url-mode consent without content, and rejects unknown actions."""
    accept = ElicitResult(action="accept", content={"tags": ["a", "b"], "name": "x"})
    assert accept.content["tags"] == ["a", "b"]

    # URL-mode consent: accept with no content is valid.
    consent = ElicitResult(action="accept")
    assert consent.content is None

    with pytest.raises(ValidationError):
        ElicitResult(action="bogus")
