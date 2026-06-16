import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ServerStatusBadge } from "./ServerStatusBadge";
import type { MCPServer } from "../../types/server";

describe("ServerStatusBadge", () => {
  const baseServer: MCPServer = {
    id: "test-id",
    name: "test-server",
    enabled: true,
    reachable: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    is_deleted: false,
    settings: {
      command: "node",
      args: ["test.js"],
      env: {},
    },
    client_count: 0,
    auth_type: "none",
    status: "active",
  };

  it("renders Draft when not enabled", () => {
    render(<ServerStatusBadge server={{ ...baseServer, enabled: false }} />);
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("renders Offline when enabled but not reachable", () => {
    render(<ServerStatusBadge server={{ ...baseServer, enabled: true, reachable: false }} />);
    expect(screen.getByText("Offline")).toBeInTheDocument();
  });

  it("renders Warning when last_seen is older than threshold", () => {
    const oldDate = new Date(Date.now() - 6 * 60 * 1000).toISOString();
    render(
      <ServerStatusBadge
        server={{ ...baseServer, enabled: true, reachable: true, lastSeen: oldDate }}
      />,
    );
    expect(screen.getByText("Warning")).toBeInTheDocument();
  });

  it("renders Active when reachable and recently seen", () => {
    const recentDate = new Date(Date.now() - 1 * 60 * 1000).toISOString();
    render(
      <ServerStatusBadge
        server={{ ...baseServer, enabled: true, reachable: true, lastSeen: recentDate }}
      />,
    );
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("renders Active when reachable and last_seen is undefined", () => {
    render(<ServerStatusBadge server={{ ...baseServer, enabled: true, reachable: true }} />);
    expect(screen.getByText("Active")).toBeInTheDocument();
  });
});
