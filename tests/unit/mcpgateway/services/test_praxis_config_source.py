# -*- coding: utf-8 -*-
"""Database contract tests for deterministic Praxis source assembly."""

import traceback

from cpex.framework import OnError
from pydantic import JsonValue
import pytest
from sqlalchemy import Engine, delete, event, insert, text
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.db import Gateway, PraxisTargetServer, Prompt, Resource, Server, Tool, server_prompt_association, server_tool_association
from mcpgateway.plugins.binding_compiler import RuntimeModeOverride
from mcpgateway.services.praxis_config_source import PraxisSourceError, PraxisSourceErrorCode, PraxisToolRuntimeOverrides
from mcpgateway.utils.url_auth import STATIC_SENSITIVE_PARAMS
from .test_praxis_config_source_support import seed_graph, source_factory, source_service


def test_snapshot_uses_assignments_scopes_enabled_entities_and_compiled_bindings(source_factory: sessionmaker[Session]) -> None:
    # Given
    seed_graph(source_factory)

    # When
    snapshot = source_service(source_factory).snapshot("target-alpha")

    # Then
    assert [server.id for server in snapshot.servers] == ["server-platform", "server-team"]
    assert [server.scope for server in snapshot.servers] == ["platform", "team-alpha"]
    team_server = snapshot.servers[1]
    assert [gateway.id for gateway in team_server.gateways] == ["gateway-stream"]
    assert [tool.id for tool in team_server.tools] == ["tool-1"]
    assert [resource.id for resource in team_server.resources] == ["resource-1"]
    assert [prompt.id for prompt in team_server.prompts] == ["prompt-1"]
    assert team_server.tools[0].compiled_config.plugins is not None
    assert team_server.tools[0].compiled_config.plugins[0].on_error is OnError.FAIL
    assert team_server.tools[0].compiled_config.plugins[0].config == {"policy": "bound"}


def test_fingerprint_is_stable_under_reordered_associations_and_changes_after_removal(source_factory: sessionmaker[Session]) -> None:
    # Given
    seed_graph(source_factory)
    service = source_service(source_factory)
    first = service.snapshot("target-alpha")
    with source_factory() as session:
        session.execute(delete(server_tool_association).where(server_tool_association.c.server_id == "server-team"))
        session.execute(
            insert(server_tool_association),
            [
                {"server_id": "server-team", "tool_id": "tool-sse"},
                {"server_id": "server-team", "tool_id": "tool-disabled"},
                {"server_id": "server-team", "tool_id": "tool-1"},
            ],
        )
        session.commit()

    # When
    reordered = service.snapshot("target-alpha")
    with source_factory() as session:
        session.execute(delete(server_prompt_association).where(server_prompt_association.c.server_id == "server-team"))
        session.commit()
    removed = service.snapshot("target-alpha")

    # Then
    assert reordered == first
    assert removed.source_fingerprint != first.source_fingerprint
    assert removed.servers[1].prompts == ()


def test_reassignment_and_server_deletion_change_the_next_full_snapshot(source_factory: sessionmaker[Session]) -> None:
    # Given
    seed_graph(source_factory)
    service = source_service(source_factory)
    initial = service.snapshot("target-alpha")
    with source_factory() as session:
        assignment = session.query(PraxisTargetServer).filter_by(server_id="server-platform").one()
        assignment.target_id = "target-beta"
        session.commit()

    # When
    reassigned = service.snapshot("target-alpha")
    with source_factory() as session:
        session.query(PraxisTargetServer).filter_by(server_id="server-team").delete()
        session.delete(session.get(Server, "server-team"))
        session.commit()
    deleted = service.snapshot("target-alpha")

    # Then
    assert reassigned.source_fingerprint != initial.source_fingerprint
    assert [server.id for server in reassigned.servers] == ["server-team"]
    assert deleted.servers == ()
    assert deleted.source_fingerprint != reassigned.source_fingerprint


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"url": "https://credential-sentinel@example.test/mcp"}, PraxisSourceErrorCode.URL_USERINFO),
        ({"url": "https://example.test/mcp?access_token=credential-sentinel"}, PraxisSourceErrorCode.CREDENTIAL_QUERY),
        ({"auth_type": "bearer", "auth_value": {"token": "credential-sentinel"}}, PraxisSourceErrorCode.AUTH_MATERIAL),
        ({"oauth_config": {"client_secret": "credential-sentinel"}}, PraxisSourceErrorCode.OAUTH_MATERIAL),  # pragma: allowlist secret
        ({"client_key": "credential-sentinel"}, PraxisSourceErrorCode.KEY_MATERIAL),
        ({"add_headers": {"Authorization": "credential-sentinel"}}, PraxisSourceErrorCode.SECRET_HEADER),
    ],
)
def test_credential_state_fails_with_fixed_sanitized_reason(source_factory: sessionmaker[Session], mutation: dict[str, JsonValue], expected: PraxisSourceErrorCode) -> None:
    # Given
    seed_graph(source_factory)
    with source_factory() as session:
        gateway = session.get(Gateway, "gateway-stream")
        assert gateway is not None
        for name, value in mutation.items():
            setattr(gateway, name, value)
        session.commit()

    # When
    with pytest.raises(PraxisSourceError) as captured:
        source_service(source_factory).snapshot("target-alpha")

    # Then
    assert captured.value.code is expected
    representations = str(captured.value) + repr(captured.value) + "".join(traceback.format_exception(captured.value))
    assert "credential-sentinel" not in representations


@pytest.mark.parametrize("query_name", sorted(STATIC_SENSITIVE_PARAMS))
def test_canonical_sensitive_query_names_are_rejected(source_factory: sessionmaker[Session], query_name: str) -> None:
    # Given
    seed_graph(source_factory)
    with source_factory() as session:
        gateway = session.get(Gateway, "gateway-stream")
        assert gateway is not None
        gateway.url = f"https://example.test/mcp?{query_name}=canonical-query-credential-sentinel"
        session.commit()

    # When
    with pytest.raises(PraxisSourceError) as captured:
        source_service(source_factory).snapshot("target-alpha")

    # Then
    assert captured.value.code is PraxisSourceErrorCode.CREDENTIAL_QUERY
    assert "canonical-query-credential-sentinel" not in str(captured.value)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"auth_type": "bearer", "auth_value": "sse-tool-credential-sentinel"}, PraxisSourceErrorCode.AUTH_MATERIAL),
        ({"headers": {"Authorization": "sse-tool-credential-sentinel"}}, PraxisSourceErrorCode.SECRET_HEADER),
        ({"plugin_chain_pre": ["sse-tool-credential-sentinel"]}, PraxisSourceErrorCode.RUNTIME_OVERRIDE),
        ({"visibility": "private", "owner_email": "sse-tool-credential-sentinel"}, PraxisSourceErrorCode.OWNER_PRIVATE),
        ({"visibility": "team", "team_id": None}, PraxisSourceErrorCode.SCOPE_MISMATCH),
    ],
)
def test_enabled_sse_tool_security_state_is_preflighted(source_factory: sessionmaker[Session], mutation: dict[str, JsonValue], expected: PraxisSourceErrorCode) -> None:
    # Given
    seed_graph(source_factory)
    with source_factory() as session:
        tool = session.get(Tool, "tool-sse")
        assert tool is not None
        for name, value in mutation.items():
            setattr(tool, name, value)
        session.commit()

    # When
    with pytest.raises(PraxisSourceError) as captured:
        source_service(source_factory).snapshot("target-alpha")

    # Then
    assert captured.value.code is expected
    assert "sse-tool-credential-sentinel" not in str(captured.value)


def test_enabled_sse_tool_runtime_drift_is_preflighted(source_factory: sessionmaker[Session]) -> None:
    # Given
    seed_graph(source_factory)
    overrides = PraxisToolRuntimeOverrides(
        scope="team-alpha",
        tool_name="legacy",
        overrides=(RuntimeModeOverride(plugin_id="SecurityPlugin", redis_mode="sequential", local_mode="disabled"),),
    )

    # When / Then
    with pytest.raises(PraxisSourceError) as captured:
        source_service(source_factory, (overrides,)).snapshot("target-alpha")
    assert captured.value.code is PraxisSourceErrorCode.RUNTIME_OVERRIDE


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_runtime_observations_are_rejected_independent_of_order(source_factory: sessionmaker[Session], reverse: bool) -> None:
    # Given
    seed_graph(source_factory)
    observations = [
        PraxisToolRuntimeOverrides(scope="team-alpha", tool_name="summarize", overrides=(RuntimeModeOverride(plugin_id="SecurityPlugin", redis_mode="sequential"),)),
        PraxisToolRuntimeOverrides(scope="team-alpha", tool_name="summarize", overrides=(RuntimeModeOverride(plugin_id="SecurityPlugin", local_mode="disabled"),)),
    ]
    if reverse:
        observations.reverse()

    # When
    with pytest.raises(PraxisSourceError) as captured:
        source_service(source_factory, tuple(observations)).snapshot("target-alpha")

    # Then
    assert captured.value.code is PraxisSourceErrorCode.RUNTIME_OVERRIDE
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_public_error_traceback_does_not_retain_sensitive_orm_graph(source_factory: sessionmaker[Session]) -> None:
    # Given
    sentinel = "traceback-local-credential-sentinel"
    seed_graph(source_factory)
    with source_factory() as session:
        gateway = session.get(Gateway, "gateway-stream")
        assert gateway is not None
        gateway.add_headers = {"Authorization": sentinel}
        session.commit()

    # When
    with pytest.raises(PraxisSourceError) as captured:
        source_service(source_factory).snapshot("target-alpha")

    # Then
    service_frames = [frame for frame, _ in traceback.walk_tb(captured.value.__traceback__) if frame.f_globals.get("__name__") == "mcpgateway.services.praxis_config_source"]
    pending = [value for frame in service_frames for value in frame.f_locals.values()]
    seen: set[int] = set()
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        assert not isinstance(value, (Gateway, Server, Tool, Resource, Prompt, Session))
        if isinstance(value, str):
            assert sentinel not in value
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        if isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_private_state_and_runtime_drift_are_sanitized_in_render_and_shadow(source_factory: sessionmaker[Session]) -> None:
    # Given
    seed_graph(source_factory)
    with source_factory() as session:
        resource = session.get(Resource, "resource-1")
        assert resource is not None
        resource.visibility = "private"
        resource.owner_email = "credential-sentinel@example.test"
        session.commit()
    service = source_service(source_factory)

    # When
    with pytest.raises(PraxisSourceError) as private_error:
        service.snapshot("target-alpha")
    status = service.shadow_status("target-alpha")
    with source_factory() as session:
        resource = session.get(Resource, "resource-1")
        assert resource is not None
        resource.visibility = "public"
        resource.owner_email = None
        session.commit()
    drift_service = source_service(
        source_factory,
        (
            PraxisToolRuntimeOverrides(
                scope="team-alpha",
                tool_name="summarize",
                overrides=(RuntimeModeOverride(plugin_id="SecurityPlugin", redis_mode="sequential", local_mode="disabled"),),
            ),
        ),
    )

    # Then
    assert private_error.value.code is PraxisSourceErrorCode.OWNER_PRIVATE
    assert status.representable is False
    assert status.reasons == (PraxisSourceErrorCode.OWNER_PRIVATE,)
    assert "credential-sentinel" not in str(private_error.value)
    with pytest.raises(PraxisSourceError) as drift_error:
        drift_service.snapshot("target-alpha")
    assert drift_error.value.code is PraxisSourceErrorCode.RUNTIME_OVERRIDE


def test_dangling_association_is_rejected_instead_of_silently_omitted(source_factory: sessionmaker[Session], test_engine: Engine) -> None:
    # Given
    seed_graph(source_factory)
    with test_engine.connect() as connection:
        sqlite_foreign_keys = None
        if test_engine.dialect.name == "postgresql":
            connection.execute(text("ALTER TABLE server_tool_association DISABLE TRIGGER ALL"))
        else:
            sqlite_foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            connection.execute(insert(server_tool_association), {"server_id": "server-team", "tool_id": "missing-tool"})
            connection.commit()
        finally:
            if test_engine.dialect.name == "postgresql":
                connection.execute(text("ALTER TABLE server_tool_association ENABLE TRIGGER ALL"))
                connection.commit()
            else:
                connection.exec_driver_sql(f"PRAGMA foreign_keys={sqlite_foreign_keys}")

    # When
    with pytest.raises(PraxisSourceError) as captured:
        source_service(source_factory).snapshot("target-alpha")

    # Then
    assert captured.value.code is PraxisSourceErrorCode.DANGLING_ASSOCIATION


def test_snapshot_opens_backend_specific_consistent_read_transaction(source_factory: sessionmaker[Session], test_engine: Engine) -> None:
    # Given
    seed_graph(source_factory)
    statements: list[str] = []

    def capture_statement(_connection, _cursor, statement: str, _parameters, _context, _executemany) -> None:
        statements.append(statement.upper())

    event.listen(test_engine, "before_cursor_execute", capture_statement)
    try:
        # When
        source_service(source_factory).snapshot("target-alpha")
    finally:
        event.remove(test_engine, "before_cursor_execute", capture_statement)

    # Then
    if test_engine.dialect.name == "postgresql":
        assert any("REPEATABLE READ" in statement for statement in statements)
    else:
        assert any(statement.strip() == "BEGIN" for statement in statements)
