"""Task 19 staged Praxis rollout settings contracts."""

import base64
import json

import pytest

from mcpgateway.config import SecurityConfigurationError, Settings, validate_praxis_rollout_configuration

_JWT = "task19-jwt-secret-with-at-least-thirty-two-characters"
_AUTH = "task19-auth-secret-with-at-least-thirty-two-characters"  # pragma: allowlist secret
_KEYS = json.dumps({"active": base64.b64encode(b"k" * 32).decode()})


def _settings(**values: bool) -> Settings:
    return Settings(
        jwt_secret_key=_JWT,
        auth_encryption_secret=_AUTH,
        praxis_bundle_encryption_keys=_KEYS,
        praxis_bundle_active_key_id="active",
        _env_file=None,
        **values,
    )


def test_praxis_rollout_stages_default_off() -> None:
    configured = Settings(jwt_secret_key=_JWT, auth_encryption_secret=_AUTH, _env_file=None)

    assert configured.praxis_shadow_render_enabled is False
    assert configured.praxis_artifact_delivery_enabled is False
    assert configured.praxis_activation_enabled is False
    assert configured.praxis_traffic_enabled is False
    assert configured.dataplane_publisher is False


def test_off_and_shadow_only_do_not_require_bundle_keys() -> None:
    off = Settings(jwt_secret_key=_JWT, auth_encryption_secret=_AUTH, _env_file=None)
    shadow = Settings(jwt_secret_key=_JWT, auth_encryption_secret=_AUTH, praxis_shadow_render_enabled=True, _env_file=None)

    assert off.praxis_bundle_active_key_id == ""
    assert shadow.praxis_bundle_encryption_keys.get_secret_value() == ""


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"praxis_artifact_delivery_enabled": True}, "requires shadow rendering"),
        ({"praxis_activation_enabled": True}, "requires artifact delivery"),
        ({"praxis_traffic_enabled": True}, "not available in this release"),
    ],
)
def test_invalid_stage_chains_fail_closed(values: dict[str, bool], message: str) -> None:
    with pytest.raises(SecurityConfigurationError, match=message):
        configured = _settings(**values)
        validate_praxis_rollout_configuration(configured)


def test_valid_staged_activation_configuration() -> None:
    configured = _settings(
        praxis_shadow_render_enabled=True,
        praxis_artifact_delivery_enabled=True,
        praxis_activation_enabled=True,
    )

    validate_praxis_rollout_configuration(configured)
    assert configured.praxis_activation_enabled is True


@pytest.mark.parametrize("stage", ["praxis_artifact_delivery_enabled", "praxis_activation_enabled"])
def test_delivery_and_activation_require_well_formed_keys(stage: str) -> None:
    values = {"praxis_shadow_render_enabled": True, "praxis_artifact_delivery_enabled": True, stage: True}
    with pytest.raises(SecurityConfigurationError, match="encryption configuration is unavailable"):
        Settings(jwt_secret_key=_JWT, auth_encryption_secret=_AUTH, _env_file=None, **values)
