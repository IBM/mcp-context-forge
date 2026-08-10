import { describe, it, expect, vi } from "vitest";
import { renderWithProviders } from "@/test/test-utils";
import { RouterProvider } from "@/router";

// Dashboard is rendered here as a smoke test, without an AuthProvider; stub the
// status hook (which reads auth/health) so it renders standalone.
vi.mock("@/hooks/useMiniCardStatuses", () => ({
  useMiniCardStatuses: () => {
    const offline = { kind: "dot", tone: "muted", labelId: "dashboard.home.status.offline" };
    return {
      statuses: {
        system: offline,
        activity: { kind: "activity", errors: 0, warnings: 0 },
        mcp: offline,
        a2a: offline,
        rest: offline,
        grpc: offline,
      },
      headlineCondition: {},
    };
  },
}));

import { Agents } from "./Agents";
import { ChangePassword } from "./ChangePassword";
import { Dashboard } from "./Dashboard";
import { ForgotPassword } from "./ForgotPassword";
import { Grpc } from "./Grpc";
import { LLMModels } from "./LLMModels";
import { LLMProviders } from "./LLMProviders";
import { Maintenance } from "./Maintenance";
import { Metrics } from "./Metrics";
import { Observability } from "./Observability";
import { Performance } from "./Performance";
import { Plugins } from "./Plugins";
import { Prompts } from "./Prompts";
import { ResetPassword } from "./ResetPassword";
import { Resources } from "./Resources";
import { RestApi } from "./RestApi";
import { ServerCatalog } from "./ServerCatalog";
import { Teams } from "./Teams";
import { Tokens } from "./Tokens";
describe("Simple Page Components", () => {
  it("renders Agents page", () => {
    renderWithProviders(<Agents />);
    expect(document.body).toBeTruthy();
  });

  it("renders ChangePassword page", () => {
    renderWithProviders(<ChangePassword />);
    expect(document.body).toBeTruthy();
  });

  it("renders Dashboard page", () => {
    renderWithProviders(
      <RouterProvider>
        <Dashboard />
      </RouterProvider>,
    );
    expect(document.body).toBeTruthy();
  });

  it("renders ForgotPassword page", () => {
    renderWithProviders(<ForgotPassword />);
    expect(document.body).toBeTruthy();
  });

  it("renders Grpc page", () => {
    renderWithProviders(<Grpc />);
    expect(document.body).toBeTruthy();
  });

  it("renders LLMModels page", () => {
    renderWithProviders(<LLMModels />);
    expect(document.body).toBeTruthy();
  });

  it("renders LLMProviders page", () => {
    renderWithProviders(<LLMProviders />);
    expect(document.body).toBeTruthy();
  });

  it("renders Maintenance page", () => {
    renderWithProviders(<Maintenance />);
    expect(document.body).toBeTruthy();
  });

  it("renders Metrics page", () => {
    renderWithProviders(<Metrics />);
    expect(document.body).toBeTruthy();
  });

  it("renders Observability page", () => {
    renderWithProviders(<Observability />);
    expect(document.body).toBeTruthy();
  });

  it("renders Performance page", () => {
    renderWithProviders(<Performance />);
    expect(document.body).toBeTruthy();
  });

  it("renders Plugins page", () => {
    renderWithProviders(<Plugins />);
    expect(document.body).toBeTruthy();
  });

  it("renders Prompts page", () => {
    renderWithProviders(<Prompts />);
    expect(document.body).toBeTruthy();
  });

  it("renders ResetPassword page", () => {
    renderWithProviders(<ResetPassword />);
    expect(document.body).toBeTruthy();
  });

  it("renders Resources page", () => {
    renderWithProviders(
      <RouterProvider>
        <Resources />
      </RouterProvider>,
    );
    expect(document.body).toBeTruthy();
  });

  it("renders RestApi page", () => {
    renderWithProviders(<RestApi />);
    expect(document.body).toBeTruthy();
  });

  it("renders ServerCatalog page", () => {
    renderWithProviders(
      <RouterProvider>
        <ServerCatalog />
      </RouterProvider>,
    );
    expect(document.body).toBeTruthy();
  });

  it("renders Teams page", () => {
    renderWithProviders(<Teams />);
    expect(document.body).toBeTruthy();
  });

  it("renders Tokens page", () => {
    renderWithProviders(<Tokens />);
    expect(document.body).toBeTruthy();
  });
});
