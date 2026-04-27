# -*- coding: utf-8 -*-
"""Test helpers for mocking admin-user DB lookups.

The Layer-1 / Layer-2 admin check goes through
``mcpgateway.utils.admin_check.is_user_admin(db, email)``, which issues
``db.execute(select(EmailUser).where(...)).scalar_one_or_none()``.  Tests
that want to simulate "caller is an admin" need to prime the mock
``db.execute`` return chain — that setup was copy-pasted in ~15 call sites
prior to this helper.

Usage:

    from tests.helpers.admin_mocks import install_admin_user

    def test_something(mock_db):
        install_admin_user(mock_db, email="admin@test.com")
        # ... db.execute(...).scalar_one_or_none() now returns an admin EmailUser
"""

# Standard
from unittest.mock import MagicMock

# First-Party
from mcpgateway.db import EmailUser


def install_admin_user(mock_db: MagicMock, email: str = "admin@test.com") -> MagicMock:
    """Configure ``mock_db`` so the admin-check DB lookup returns an admin.

    Replaces the 6-line boilerplate:

        admin_user = MagicMock(spec=EmailUser)
        admin_user.email = "admin@test.com"
        admin_user.is_admin = True
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = admin_user
        mock_db.execute.return_value = mock_result

    Args:
        mock_db: A ``MagicMock`` (or ``MagicMock(spec=Session)``).
        email: Email address to stamp on the admin user.

    Returns:
        The admin user mock, so tests can assert on it if needed.
    """
    admin_user = MagicMock(spec=EmailUser)
    admin_user.email = email
    admin_user.is_admin = True

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = admin_user
    mock_db.execute.return_value = mock_result
    return admin_user
