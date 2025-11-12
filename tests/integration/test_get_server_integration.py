import asyncio
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mcpgateway.db import Base, Gateway as DbGateway, Tool as DbTool, Server as DbServer
from mcpgateway.services.server_service import ServerService


def test_get_server_integration_in_memory_sqlite():
    """Integration test using an in-memory SQLite DB to exercise ServerService.get_server

    Creates a Gateway, Tool (attached to Gateway) and a Server that references the Tool.
    Verifies that get_server returns a ServerRead whose associatedGateways contains the gateway name.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    session = SessionLocal()

    # Create gateway, tool and server
    gw = DbGateway(name="gw-integ", slug="gw-integ", url="https://gw-integ.example", capabilities={})
    session.add(gw)
    session.flush()  # assign gw.id

    tool = DbTool(original_name="tool-integ", input_schema={}, custom_name="tool-integ", custom_name_slug="tool-integ", gateway=gw)
    # Ensure the non-nullable computed 'name' column is set
    tool._computed_name = "tool-integ"
    session.add(tool)
    session.flush()

    server = DbServer(name="server-integ")
    server.tools.append(tool)
    session.add(server)
    session.commit()

    svc = ServerService()
    result = asyncio.run(svc.get_server(session, server.id))
    data = result.model_dump(by_alias=True)

    assert "associatedGateways" in data
    assert data["associatedGateways"] == [gw.name]
