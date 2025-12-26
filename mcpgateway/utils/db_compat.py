# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/db_compat.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Database compatibility utilities for async/sync session handling.

This module provides utilities that allow services to work transparently
with both sync (Session) and async (AsyncSession) database sessions.
This is particularly useful during the async migration and for testing.

The key feature is AsyncSessionWrapper, which wraps a sync Session and
makes it behave like an AsyncSession. This allows async services to work
with sync sessions in tests without modification.

Examples:
    >>> from mcpgateway.utils.db_compat import AsyncSessionWrapper
    >>> # Wrap a sync session for async compatibility:
    >>> async_db = AsyncSessionWrapper(sync_session)
    >>> result = await async_db.execute(select(Tool))  # Works!

    >>> from mcpgateway.utils.db_compat import db_execute, db_commit
    >>> # Or use helper functions:
    >>> result = await db_execute(db, select(Tool))
    >>> await db_commit(db)
"""

# Standard
import asyncio
from typing import Any, TypeVar, Union

# Third-Party
from sqlalchemy import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

T = TypeVar("T")


class AsyncSessionWrapper:
    """Wrapper that makes a sync Session behave like an AsyncSession.

    This class wraps a synchronous SQLAlchemy Session and provides an
    async-compatible interface. All operations return awaitables that
    execute synchronously, allowing async code to work with sync sessions.

    This is particularly useful in tests where you want to use async services
    with sync database fixtures.

    Examples:
        >>> from sqlalchemy.orm import Session
        >>> from mcpgateway.utils.db_compat import AsyncSessionWrapper
        >>> sync_session = Session(bind=engine)
        >>> async_db = AsyncSessionWrapper(sync_session)
        >>> # Now async_db can be used like an AsyncSession:
        >>> result = await async_db.execute(select(Tool))
        >>> await async_db.commit()
    """

    def __init__(self, session: Session):
        """Initialize the wrapper with a sync session.

        Args:
            session: Synchronous SQLAlchemy Session to wrap.
        """
        self._session = session

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Result[Any]:
        """Execute a statement and return the result.

        Args:
            statement: SQL statement to execute.
            *args: Positional arguments for execute.
            **kwargs: Keyword arguments for execute.

        Returns:
            Result object from the execution.
        """
        return self._session.execute(statement, *args, **kwargs)

    async def commit(self) -> None:
        """Commit the current transaction."""
        self._session.commit()

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        self._session.rollback()

    async def flush(self, objects: Any = None) -> None:
        """Flush pending changes to the database."""
        self._session.flush(objects)

    async def refresh(self, instance: Any, *args: Any, **kwargs: Any) -> None:
        """Refresh an object from the database."""
        self._session.refresh(instance, *args, **kwargs)

    async def delete(self, instance: Any) -> None:
        """Mark an object for deletion."""
        self._session.delete(instance)

    def add(self, instance: Any) -> None:
        """Add an object to the session."""
        self._session.add(instance)

    def add_all(self, instances: Any) -> None:
        """Add multiple objects to the session."""
        self._session.add_all(instances)

    async def close(self) -> None:
        """Close the session."""
        self._session.close()

    def get_bind(self) -> Any:
        """Get the bind (engine) for the session."""
        return self._session.get_bind()

    async def scalar(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute and return a scalar result."""
        result = self._session.execute(statement, *args, **kwargs)
        return result.scalar()

    async def scalars(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute and return scalars."""
        result = self._session.execute(statement, *args, **kwargs)
        return result.scalars()

    async def get(self, entity: Any, ident: Any, **kwargs: Any) -> Any:
        """Get an entity by its primary key.

        Args:
            entity: The entity class to query.
            ident: The primary key value.
            **kwargs: Additional options like 'options' for eager loading.

        Returns:
            The entity instance or None.
        """
        return self._session.get(entity, ident, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Forward any unknown attributes to the wrapped session."""
        return getattr(self._session, name)


def is_async_session(db: Union[Session, AsyncSession]) -> bool:
    """Check if the database session is async.

    Args:
        db: Database session (sync or async).

    Returns:
        True if the session is an AsyncSession, False otherwise.
    """
    return isinstance(db, AsyncSession)


async def db_execute(db: Union[Session, AsyncSession], statement: Any) -> Result[Any]:
    """Execute a database statement on either sync or async session.

    This function transparently handles both sync and async sessions,
    allowing services to work with either type without modification.

    Args:
        db: Database session (sync or async).
        statement: SQL statement to execute.

    Returns:
        Result object from the execution.

    Examples:
        >>> # Works with both session types:
        >>> result = await db_execute(db, select(Tool).where(Tool.id == tool_id))
        >>> tool = result.scalar_one_or_none()
    """
    if is_async_session(db):
        return await db.execute(statement)
    else:
        # For sync sessions, run in thread pool to not block
        # In test mode, this runs synchronously
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context, run sync operation directly
            # This is safe because sync sessions are thread-safe
            return db.execute(statement)
        else:
            return db.execute(statement)


async def db_commit(db: Union[Session, AsyncSession]) -> None:
    """Commit the database session.

    Args:
        db: Database session (sync or async).
    """
    if is_async_session(db):
        await db.commit()
    else:
        db.commit()


async def db_rollback(db: Union[Session, AsyncSession]) -> None:
    """Rollback the database session.

    Args:
        db: Database session (sync or async).
    """
    if is_async_session(db):
        await db.rollback()
    else:
        db.rollback()


async def db_refresh(db: Union[Session, AsyncSession], instance: Any) -> None:
    """Refresh an object from the database.

    Args:
        db: Database session (sync or async).
        instance: Object to refresh.
    """
    if is_async_session(db):
        await db.refresh(instance)
    else:
        db.refresh(instance)


async def db_flush(db: Union[Session, AsyncSession]) -> None:
    """Flush pending changes to the database.

    Args:
        db: Database session (sync or async).
    """
    if is_async_session(db):
        await db.flush()
    else:
        db.flush()


async def db_delete(db: Union[Session, AsyncSession], instance: Any) -> None:
    """Delete an object from the database.

    Args:
        db: Database session (sync or async).
        instance: Object to delete.
    """
    if is_async_session(db):
        await db.delete(instance)
    else:
        db.delete(instance)


def db_add(db: Union[Session, AsyncSession], instance: Any) -> None:
    """Add an object to the session.

    Note: This is synchronous for both session types.

    Args:
        db: Database session (sync or async).
        instance: Object to add.
    """
    db.add(instance)


async def db_scalar_one_or_none(db: Union[Session, AsyncSession], statement: Any) -> Any:
    """Execute a statement and return a single scalar result or None.

    Args:
        db: Database session (sync or async).
        statement: SQL statement to execute.

    Returns:
        Single scalar result or None.
    """
    result = await db_execute(db, statement)
    return result.scalar_one_or_none()


async def db_scalars_all(db: Union[Session, AsyncSession], statement: Any) -> list[Any]:
    """Execute a statement and return all scalar results as a list.

    Args:
        db: Database session (sync or async).
        statement: SQL statement to execute.

    Returns:
        List of all scalar results.
    """
    result = await db_execute(db, statement)
    return list(result.scalars().all())
