import { describe, it, expect, vi } from "vitest";
import { renderWithProviders } from "@/test/test-utils";
import { screen } from "@testing-library/react";
import { AppShell } from "./AppShell";

// Mock the heavy sidebar/header components to keep tests fast
vi.mock("./Sidebar", () => ({
  AppSidebar: () => <aside data-testid="app-sidebar">Sidebar</aside>,
}));

vi.mock("./Header", () => ({
  Header: () => <header data-testid="app-header">Header</header>,
}));

vi.mock("../ui/sidebar", () => ({
  SidebarProvider: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="sidebar-provider">{children}</div>
  ),
  SidebarInset: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="sidebar-inset">{children}</div>
  ),
}));

import React from "react";

describe("AppShell", () => {
  it("renders without crashing", () => {
    renderWithProviders(<AppShell>Content</AppShell>);
    expect(document.body).toBeTruthy();
  });

  it("renders the sidebar", () => {
    renderWithProviders(<AppShell>Content</AppShell>);
    expect(screen.getByTestId("app-sidebar")).toBeTruthy();
  });

  it("renders the header", () => {
    renderWithProviders(<AppShell>Content</AppShell>);
    expect(screen.getByTestId("app-header")).toBeTruthy();
  });

  it("renders children inside the shell", () => {
    renderWithProviders(
      <AppShell>
        <div data-testid="page-content">Page Content</div>
      </AppShell>,
    );
    expect(screen.getByTestId("page-content")).toBeTruthy();
    expect(screen.getByText("Page Content")).toBeTruthy();
  });

  it("renders multiple children", () => {
    renderWithProviders(
      <AppShell>
        <div>Child 1</div>
        <div>Child 2</div>
      </AppShell>,
    );
    expect(screen.getByText("Child 1")).toBeTruthy();
    expect(screen.getByText("Child 2")).toBeTruthy();
  });
});
