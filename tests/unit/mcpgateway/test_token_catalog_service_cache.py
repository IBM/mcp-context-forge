# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_token_catalog_service_cache.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for TokenCatalogService revocation caching (Issue #2692).

Verifies that is_token_revoked() and get_token_revocation() consult
auth_cache before hitting the database, and populate the cache after
a DB miss so subsequent calls skip the round-trip.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Base, TokenRevocation
from mcpgateway.services.token_catalog_service import TokenCatalogService


@pytest.fixture()
def db_session():
    """In-memory SQLite session with the TokenRevocation table."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def service(db_session):
    return TokenCatalogService(db_session)


@pytest.fixture()
def mock_auth_cache():
    cache = MagicMock()
    cache.is_token_revoked = AsyncMock(return_value=None)
    cache.set_not_revoked = AsyncMock()
    return cache


# ---------------------------------------------------------------------------
# is_token_revoked
# ---------------------------------------------------------------------------


class TestIsTokenRevokedCaching:
    @pytest.mark.asyncio
    async def test_cache_hit_true_skips_db(self, service, mock_auth_cache):
        """Cache returns True → DB is never queried."""
        mock_auth_cache.is_token_revoked.return_value = True

        with patch("mcpgateway.services.token_catalog_service.auth_cache", mock_auth_cache, create=True):
            with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth_cache, create=True):
                with patch.object(service.db, "execute", wraps=service.db.execute) as mock_execute:
                    result = await service.is_token_revoked("some-jti")

        assert result is True
        mock_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_hit_false_skips_db(self, service, mock_auth_cache):
        """Cache returns False → DB is never queried."""
        mock_auth_cache.is_token_revoked.return_value = False

        with patch("mcpgateway.services.token_catalog_service.auth_cache", mock_auth_cache, create=True):
            with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth_cache, create=True):
                with patch.object(service.db, "execute", wraps=service.db.execute) as mock_execute:
                    result = await service.is_token_revoked("some-jti")

        assert result is False
        mock_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_db_revoked_returns_true(self, service, db_session, mock_auth_cache):
        """Cache miss (None) + DB has revocation row → returns True."""
        jti = "revoked-jti"
        db_session.add(TokenRevocation(jti=jti, revoked_by="admin@example.com"))
        db_session.commit()

        mock_auth_cache.is_token_revoked.return_value = None

        with patch("mcpgateway.services.token_catalog_service.auth_cache", mock_auth_cache, create=True):
            with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth_cache, create=True):
                result = await service.is_token_revoked(jti)

        assert result is True

    @pytest.mark.asyncio
    async def test_cache_miss_db_clean_populates_not_revoked(self, service, mock_auth_cache):
        """Cache miss + DB has no revocation row → set_not_revoked called."""
        mock_auth_cache.is_token_revoked.return_value = None

        with patch("mcpgateway.services.token_catalog_service.auth_cache", mock_auth_cache, create=True):
            with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth_cache, create=True):
                result = await service.is_token_revoked("clean-jti")

        assert result is False
        mock_auth_cache.set_not_revoked.assert_called_once_with("clean-jti")

    @pytest.mark.asyncio
    async def test_cache_error_falls_back_to_db(self, service, db_session, mock_auth_cache):
        """Cache raises → falls back to DB, still returns correct result."""
        jti = "revoked-jti-fallback"
        db_session.add(TokenRevocation(jti=jti, revoked_by="admin@example.com"))
        db_session.commit()

        mock_auth_cache.is_token_revoked.side_effect = RuntimeError("redis down")

        with patch("mcpgateway.services.token_catalog_service.auth_cache", mock_auth_cache, create=True):
            with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth_cache, create=True):
                result = await service.is_token_revoked(jti)

        assert result is True

    @pytest.mark.asyncio
    async def test_set_not_revoked_error_is_silenced(self, service, mock_auth_cache):
        """set_not_revoked raises → exception is silenced, False still returned."""
        mock_auth_cache.is_token_revoked.return_value = None
        mock_auth_cache.set_not_revoked.side_effect = RuntimeError("redis write error")

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth_cache, create=True):
            result = await service.is_token_revoked("clean-jti-error")

        assert result is False


# ---------------------------------------------------------------------------
# get_token_revocation
# ---------------------------------------------------------------------------


class TestGetTokenRevocationCaching:
    @pytest.mark.asyncio
    async def test_cache_false_skips_db_returns_none(self, service, mock_auth_cache):
        """Cache returns False → None returned without a DB query."""
        mock_auth_cache.is_token_revoked.return_value = False

        with patch("mcpgateway.services.token_catalog_service.auth_cache", mock_auth_cache, create=True):
            with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth_cache, create=True):
                with patch.object(service.db, "execute", wraps=service.db.execute) as mock_execute:
                    result = await service.get_token_revocation("clean-jti")

        assert result is None
        mock_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_true_still_queries_db_for_orm_object(self, service, db_session, mock_auth_cache):
        """Cache returns True → DB queried to get the full TokenRevocation ORM object."""
        jti = "revoked-full"
        revocation = TokenRevocation(jti=jti, revoked_by="admin@example.com", reason="test")
        db_session.add(revocation)
        db_session.commit()

        mock_auth_cache.is_token_revoked.return_value = True

        with patch("mcpgateway.services.token_catalog_service.auth_cache", mock_auth_cache, create=True):
            with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth_cache, create=True):
                result = await service.get_token_revocation(jti)

        assert result is not None
        assert result.jti == jti
        assert result.revoked_by == "admin@example.com"

    @pytest.mark.asyncio
    async def test_cache_miss_db_miss_populates_not_revoked(self, service, mock_auth_cache):
        """Cache miss + DB miss → set_not_revoked called, None returned."""
        mock_auth_cache.is_token_revoked.return_value = None

        with patch("mcpgateway.services.token_catalog_service.auth_cache", mock_auth_cache, create=True):
            with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth_cache, create=True):
                result = await service.get_token_revocation("no-such-jti")

        assert result is None
        mock_auth_cache.set_not_revoked.assert_called_once_with("no-such-jti")

    @pytest.mark.asyncio
    async def test_cache_error_falls_back_to_db(self, service, db_session, mock_auth_cache):
        """Cache raises → falls back to DB and returns correct ORM object."""
        jti = "revoked-fallback"
        revocation = TokenRevocation(jti=jti, revoked_by="admin@example.com")
        db_session.add(revocation)
        db_session.commit()

        mock_auth_cache.is_token_revoked.side_effect = RuntimeError("redis down")

        with patch("mcpgateway.services.token_catalog_service.auth_cache", mock_auth_cache, create=True):
            with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth_cache, create=True):
                result = await service.get_token_revocation(jti)

        assert result is not None
        assert result.jti == jti

    @pytest.mark.asyncio
    async def test_set_not_revoked_error_is_silenced(self, service, mock_auth_cache):
        """set_not_revoked raises → exception is silenced, None still returned."""
        mock_auth_cache.is_token_revoked.return_value = None
        mock_auth_cache.set_not_revoked.side_effect = RuntimeError("redis write error")

        with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth_cache, create=True):
            result = await service.get_token_revocation("clean-jti-error")

        assert result is None
