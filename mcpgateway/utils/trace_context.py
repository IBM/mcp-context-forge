# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/trace_context.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Trace context helpers for OpenTelemetry span enrichment.
"""

# Standard
from contextvars import ContextVar
import re
from typing import Any, Iterable, Optional

_trace_user_email: ContextVar[Optional[str]] = ContextVar("trace_user_email", default=None)
_trace_user_is_admin: ContextVar[bool] = ContextVar("trace_user_is_admin", default=False)
_trace_team_scope: ContextVar[Optional[str]] = ContextVar("trace_team_scope", default=None)
_trace_team_name: ContextVar[Optional[str]] = ContextVar("trace_team_name", default=None)
_trace_auth_method: ContextVar[Optional[str]] = ContextVar("trace_auth_method", default=None)
_trace_session_id: ContextVar[Optional[str]] = ContextVar("trace_session_id", default=None)

_TEAM_SCOPE_SEPARATOR = ","
_ELLIPSIS_MARKER = "..."


def get_trace_user_email() -> Optional[str]:
    """Return the current trace user email.

    Returns:
        Email address recorded in the current trace context, if any.
    """
    return _trace_user_email.get()


def set_trace_user_email(value: Optional[str]) -> None:
    """Set the current trace user email.

    Args:
        value: Email address to store for the current trace context.
    """
    _trace_user_email.set(value)


def get_trace_user_is_admin() -> bool:
    """Return whether the current trace user is an admin.

    Returns:
        ``True`` when the current trace context represents an admin user.
    """
    return _trace_user_is_admin.get()


def set_trace_user_is_admin(value: bool) -> None:
    """Set whether the current trace user is an admin.

    Args:
        value: Admin flag to store for the current trace context.
    """
    _trace_user_is_admin.set(bool(value))


def get_trace_team_scope() -> Optional[str]:
    """Return the current trace team scope label.

    Returns:
        Serialized team scope label for the current trace context, if any.
    """
    return _trace_team_scope.get()


def set_trace_team_scope(value: Optional[str]) -> None:
    """Set the current trace team scope label.

    Args:
        value: Serialized team scope label to store for the current trace context.
    """
    _trace_team_scope.set(value)


def get_trace_team_name() -> Optional[str]:
    """Return the current primary trace team name.

    Returns:
        Team display name recorded for the primary team in the current trace context, if any.
    """
    return _trace_team_name.get()


def set_trace_team_name(value: Optional[str]) -> None:
    """Set the current primary trace team name.

    Args:
        value: Team display name to store for the current trace context.
    """
    _trace_team_name.set(value)


def get_trace_auth_method() -> Optional[str]:
    """Return the current trace auth method.

    Returns:
        Authentication method label for the current trace context, if any.
    """
    return _trace_auth_method.get()


def set_trace_auth_method(value: Optional[str]) -> None:
    """Set the current trace auth method.

    Args:
        value: Authentication method label to store for the current trace context.
    """
    _trace_auth_method.set(value)


def get_trace_session_id() -> Optional[str]:
    """Return the current trace session identifier.

    Returns:
        Session identifier recorded in the current trace context, if any.
    """
    return _trace_session_id.get()


def set_trace_session_id(value: Optional[str]) -> None:
    """Set the current trace session identifier.

    Args:
        value: Session identifier to store for the current trace context.
    """
    _trace_session_id.set(value)


def clear_trace_context() -> None:
    """Clear all trace context values for the current execution context."""
    set_trace_user_email(None)
    set_trace_user_is_admin(False)
    set_trace_team_scope(None)
    set_trace_team_name(None)
    set_trace_auth_method(None)
    set_trace_session_id(None)


def _normalize_team_id(team: Any) -> Optional[str]:
    """Normalize a team identifier from mixed token formats.

    Args:
        team: Team identifier in string, object, or mapping form.

    Returns:
        Normalized team identifier string, or ``None`` when no usable value exists.
    """
    if isinstance(team, dict):
        team = team.get("id")
    if team is None:
        return None
    team_id = str(team).strip()
    return team_id or None


def _normalize_team_name(team: Any) -> Optional[str]:
    """Normalize a team display name from mixed token formats.

    Args:
        team: Team value in mapping or scalar form.

    Returns:
        Normalized team display name string, or ``None`` when unavailable.
    """
    if not isinstance(team, dict):
        return None

    team_name = team.get("name")
    if team_name is None:
        return None

    normalized_name = str(team_name).strip()
    return normalized_name or None


def format_trace_team_scope(token_teams: Optional[Iterable[Any]], *, max_teams: int = 5) -> str:
    """Format token team scope for trace labels.

    Args:
        token_teams: Iterable of token team values, or ``None`` to represent admin scope.
        max_teams: Maximum number of explicit team identifiers to include before truncating.

    Returns:
        Serialized team scope label for use in span attributes.
    """
    if token_teams is None:
        return "admin"

    normalized: list[str] = []
    for team in token_teams:
        team_id = _normalize_team_id(team)
        if team_id:
            normalized.append(team_id)

    if not normalized:
        return "public"

    if len(normalized) <= max_teams:
        return _TEAM_SCOPE_SEPARATOR.join(normalized)

    limited = normalized[:max_teams]
    limited.append(_ELLIPSIS_MARKER)
    return _TEAM_SCOPE_SEPARATOR.join(limited)


def primary_team_from_scope(team_scope: Optional[str]) -> Optional[str]:
    """Return the first team id from a formatted trace team scope label.

    Args:
        team_scope: Serialized team scope label produced by ``format_trace_team_scope``.

    Returns:
        First concrete team identifier in the scope, or ``None`` for admin/public scopes.
    """
    if not team_scope or team_scope in {"admin", "public"}:
        return None

    for candidate in re.split(r"\s*,\s*", team_scope):
        if candidate and candidate != _ELLIPSIS_MARKER:
            return candidate
    return None


def primary_team_name_from_teams(token_teams: Optional[Iterable[Any]]) -> Optional[str]:
    """Return the primary team display name from raw team values.

    The primary team is defined by the first concrete team identifier that would
    appear in ``team.scope``. A name is only returned when that same team value
    also includes a non-empty display name.

    Args:
        token_teams: Iterable of raw token team values, or ``None`` for admin scope.

    Returns:
        Team display name for the primary concrete team, or ``None`` when unavailable.
    """
    if token_teams is None:
        return None

    for team in token_teams:
        team_id = _normalize_team_id(team)
        if not team_id:
            continue
        return _normalize_team_name(team)
    return None


def set_trace_context_from_teams(
    token_teams: Optional[Iterable[Any]],
    *,
    user_email: Optional[str] = None,
    is_admin: bool = False,
    auth_method: Optional[str] = None,
    team_name: Optional[str] = None,
    max_teams: int = 5,
) -> None:
    """Populate trace context using the canonical token-teams model.

    Args:
        token_teams: Iterable of team identifiers, or ``None`` for admin scope.
        user_email: Optional user email to record on the trace.
        is_admin: Whether the trace context should be marked as admin.
        auth_method: Optional authentication method label to record.
        team_name: Optional display name for the primary concrete team.
        max_teams: Maximum number of team identifiers to include in the scope label.
    """
    if user_email is not None:
        set_trace_user_email(user_email)
    set_trace_user_is_admin(is_admin)
    if auth_method is not None:
        set_trace_auth_method(auth_method)
    set_trace_team_name(team_name or primary_team_name_from_teams(token_teams))
    set_trace_team_scope(format_trace_team_scope(token_teams, max_teams=max_teams))
