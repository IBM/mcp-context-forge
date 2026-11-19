# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_oauth_secret_reentry.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

The client secret must be sent again when an update moves its token endpoint.

The React form submits the mask on every edit, and a masked secret keeps the
stored value. If the same update also changes ``token_url``, the gateway would
send that stored secret to a different host. The guard compares the effective
endpoint of the top-level config and of the nested discovery and actor clients,
because each of those clients can carry its own secret.
"""

# First-Party
from mcpgateway.common.oauth import oauth_secret_reentry_required, oauth_token_urls
from mcpgateway.config import settings

MASK = settings.masked_auth_value
OLD_TOKEN = "https://old.example.com/token"
NEW_TOKEN = "https://new.example.com/token"


def _config(token_url=OLD_TOKEN, **overrides):
    """A client-credentials config the update path receives from the form."""
    config = {"grant_type": "client_credentials", "client_id": "svc", "token_url": token_url}
    config.update(overrides)
    return config


class TestOauthTokenUrls:
    """Effective endpoint resolution, including inheritance from the parent."""

    def test_nested_clients_inherit_the_parent_endpoint(self):
        assert oauth_token_urls(_config()) == {
            "token_url": OLD_TOKEN,
            "discovery.token_url": OLD_TOKEN,
            "actor.token_url": OLD_TOKEN,
        }

    def test_nested_client_override_wins(self):
        urls = oauth_token_urls(_config(actor={"client_id": "cf", "token_url": "https://actor.example.com/token"}))
        assert urls["actor.token_url"] == "https://actor.example.com/token"
        assert urls["discovery.token_url"] == OLD_TOKEN

    def test_missing_config_has_no_endpoints(self):
        assert oauth_token_urls(None) == {}


class TestOauthSecretReentryRequired:
    """The guard refuses only the combination that leaks a stored secret."""

    def test_masked_secret_with_a_changed_token_url_is_refused(self):
        assert oauth_secret_reentry_required(_config(NEW_TOKEN, client_secret=MASK), _config(), MASK) is True

    def test_masked_secret_with_the_same_token_url_is_kept(self):
        assert oauth_secret_reentry_required(_config(OLD_TOKEN, client_secret=MASK), _config(), MASK) is False

    def test_new_secret_with_a_changed_token_url_is_accepted(self):
        assert oauth_secret_reentry_required(_config(NEW_TOKEN, client_secret="new-secret"), _config(), MASK) is False  # pragma: allowlist secret

    def test_masked_secret_in_discovery_with_a_changed_discovery_endpoint_is_refused(self):
        new = _config(discovery={"grant_type": "client_credentials", "token_url": NEW_TOKEN, "client_secret": MASK})
        stored = _config(discovery={"grant_type": "client_credentials", "token_url": OLD_TOKEN})
        assert oauth_secret_reentry_required(new, stored, MASK) is True

    def test_masked_secret_in_actor_with_a_changed_actor_endpoint_is_refused(self):
        new = _config(actor={"client_id": "cf", "token_url": NEW_TOKEN, "client_secret": MASK})
        stored = _config(actor={"client_id": "cf", "token_url": OLD_TOKEN})
        assert oauth_secret_reentry_required(new, stored, MASK) is True

    def test_masked_parent_secret_with_a_changed_discovery_endpoint_is_refused(self):
        # The discovery client inherits the parent secret, so a discovery
        # endpoint change moves that masked secret to the new host.
        new = _config(client_secret=MASK, discovery={"grant_type": "client_credentials", "token_url": NEW_TOKEN})
        assert oauth_secret_reentry_required(new, _config(), MASK) is True

    def test_masked_nested_secret_with_a_changed_parent_endpoint_is_refused(self):
        new = _config(NEW_TOKEN, actor={"client_id": "cf", "client_secret": MASK})
        stored = _config(actor={"client_id": "cf"})
        assert oauth_secret_reentry_required(new, stored, MASK) is True

    def test_a_masked_non_secret_field_is_not_refused(self):
        # client_id is public, so a mask there does not carry stored secret material.
        assert oauth_secret_reentry_required(_config(NEW_TOKEN, client_id=MASK), _config(), MASK) is False

    def test_missing_stored_config_accepts_the_update(self):
        assert oauth_secret_reentry_required(_config(NEW_TOKEN, client_secret=MASK), None, MASK) is False

    def test_missing_new_config_accepts_the_update(self):
        assert oauth_secret_reentry_required(None, _config(), MASK) is False
