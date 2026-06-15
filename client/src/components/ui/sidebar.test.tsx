import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "./tooltip";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInput,
  SidebarInset,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarProvider,
  SidebarRail,
  SidebarSeparator,
  SidebarTrigger,
  useSidebar,
} from "./sidebar";

// Add mock for useIsMobile
vi.mock("../../hooks/use-mobile", () => ({
  useIsMobile: vi.fn(() => false),
}));

const renderWithProvider = (ui: React.ReactElement) => {
  return render(<TooltipProvider>{ui}</TooltipProvider>);
};

describe("Sidebar Components", () => {
  it("renders SidebarProvider and Sidebar", () => {
    renderWithProvider(
      <SidebarProvider>
        <Sidebar data-testid="sidebar">
          <SidebarContent>
            <SidebarGroup>
              <SidebarGroupLabel>Label</SidebarGroupLabel>
              <SidebarGroupContent>Content</SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
        </Sidebar>
      </SidebarProvider>,
    );

    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByText("Label")).toBeInTheDocument();
    expect(screen.getByText("Content")).toBeInTheDocument();
  });

  it("renders Sidebar with collapsible=none", () => {
    renderWithProvider(
      <SidebarProvider>
        <Sidebar collapsible="none" data-testid="sidebar-none">
          Content
        </Sidebar>
      </SidebarProvider>,
    );

    expect(screen.getByTestId("sidebar-none")).toBeInTheDocument();
  });

  it("renders Sidebar components properly", () => {
    renderWithProvider(
      <SidebarProvider>
        <SidebarHeader data-testid="header" />
        <SidebarContent data-testid="content">
          <SidebarGroup data-testid="group">
            <SidebarGroupLabel data-testid="group-label" />
            <SidebarGroupAction data-testid="group-action" />
            <SidebarGroupContent data-testid="group-content">
              <SidebarMenu data-testid="menu">
                <SidebarMenuItem data-testid="menu-item">
                  <SidebarMenuButton data-testid="menu-button">Button</SidebarMenuButton>
                  <SidebarMenuAction data-testid="menu-action" />
                  <SidebarMenuBadge data-testid="menu-badge" />
                </SidebarMenuItem>
              </SidebarMenu>
              <SidebarMenuSub data-testid="menu-sub">
                <SidebarMenuSubItem data-testid="menu-sub-item">
                  <SidebarMenuSubButton data-testid="menu-sub-button">
                    SubButton
                  </SidebarMenuSubButton>
                </SidebarMenuSubItem>
              </SidebarMenuSub>
            </SidebarGroupContent>
          </SidebarGroup>
          <SidebarSeparator data-testid="separator" />
          <SidebarInput data-testid="input" />
          <SidebarMenuSkeleton data-testid="skeleton" />
          <SidebarMenuSkeleton data-testid="skeleton-icon" showIcon />
        </SidebarContent>
        <SidebarFooter data-testid="footer" />
        <SidebarRail data-testid="rail" />
        <SidebarInset data-testid="inset" />
        <SidebarTrigger data-testid="trigger" />
      </SidebarProvider>,
    );

    expect(screen.getByTestId("header")).toBeInTheDocument();
  });

  it("handles SidebarTrigger click", async () => {
    const user = userEvent.setup();
    renderWithProvider(
      <SidebarProvider defaultOpen={true}>
        <Sidebar data-testid="sidebar" />
        <SidebarTrigger data-testid="trigger" />
      </SidebarProvider>,
    );

    const trigger = screen.getByTestId("trigger");
    const sidebarContainer = screen.getByTestId("sidebar");
    const sidebar = sidebarContainer.closest('[data-slot="sidebar"]');

    // Default open
    expect(sidebar).toHaveAttribute("data-state", "expanded");

    await user.click(trigger);

    // After click
    expect(sidebar).toHaveAttribute("data-state", "collapsed");
  });

  it("renders mobile sidebar using Sheet when isMobile is true", async () => {
    const user = userEvent.setup();
    // Override the mock for this test
    const { useIsMobile } = await import("../../hooks/use-mobile");
    vi.mocked(useIsMobile).mockReturnValue(true);

    renderWithProvider(
      <SidebarProvider>
        <Sidebar data-testid="mobile-sidebar" />
        <SidebarTrigger data-testid="mobile-trigger" />
      </SidebarProvider>,
    );

    const trigger = screen.getByTestId("mobile-trigger");
    await user.click(trigger);

    // It should render a dialog/sheet element with mobile="true"
    await waitFor(() => {
      const mobileSidebar = document.querySelector('[data-mobile="true"]');
      expect(mobileSidebar).toBeInTheDocument();
    });
  });

  it("renders with floating variant", async () => {
    // Reset the mock
    const { useIsMobile } = await import("../../hooks/use-mobile");
    vi.mocked(useIsMobile).mockReturnValue(false);

    renderWithProvider(
      <SidebarProvider>
        <Sidebar variant="floating" data-testid="floating-sidebar" />
      </SidebarProvider>,
    );

    const sidebarContainer = screen.getByTestId("floating-sidebar");
    const sidebar = sidebarContainer.closest('[data-slot="sidebar"]');
    expect(sidebar).toHaveAttribute("data-variant", "floating");
  });

  it("handles SidebarMenuButton variants and sizes", () => {
    renderWithProvider(
      <SidebarProvider>
        <SidebarMenuButton variant="outline" size="sm" data-testid="btn-outline-sm">
          Outline SM
        </SidebarMenuButton>
        <SidebarMenuButton variant="default" size="lg" data-testid="btn-default-lg">
          Default LG
        </SidebarMenuButton>
        <SidebarMenuButton isActive data-testid="btn-active">
          Active
        </SidebarMenuButton>
        <SidebarMenuButton asChild data-testid="btn-as-child">
          <a href="#">Link</a>
        </SidebarMenuButton>
        <SidebarMenuButton tooltip="My tooltip" data-testid="btn-tooltip">
          Tooltip
        </SidebarMenuButton>
      </SidebarProvider>,
    );

    expect(screen.getByTestId("btn-outline-sm")).toBeInTheDocument();
    expect(screen.getByTestId("btn-tooltip")).toBeInTheDocument();
  });

  it("handles SidebarMenuAction variants", () => {
    renderWithProvider(
      <SidebarProvider>
        <SidebarMenuAction showOnHover data-testid="action-hover" />
        <SidebarMenuAction asChild data-testid="action-child">
          <span>Action</span>
        </SidebarMenuAction>
      </SidebarProvider>,
    );

    expect(screen.getByTestId("action-hover")).toBeInTheDocument();
  });

  it("throws error when useSidebar is used outside of SidebarProvider", () => {
    const TestComponent = () => {
      useSidebar();
      return <div>Test</div>;
    };

    const consoleSpy = vi.spyOn(console, "error");
    consoleSpy.mockImplementation(() => {});

    expect(() => renderWithProvider(<TestComponent />)).toThrow(
      "useSidebar must be used within a SidebarProvider.",
    );

    consoleSpy.mockRestore();
  });

  it("supports controlled state via open and onOpenChange props", async () => {
    const user = userEvent.setup();
    const handleOpenChange = vi.fn();
    renderWithProvider(
      <SidebarProvider open={true} onOpenChange={handleOpenChange}>
        <Sidebar data-testid="controlled-sidebar" />
        <SidebarTrigger data-testid="controlled-trigger" />
      </SidebarProvider>,
    );

    const sidebarContainer = screen.getByTestId("controlled-sidebar");
    const sidebar = sidebarContainer.closest('[data-slot="sidebar"]');
    expect(sidebar).toHaveAttribute("data-state", "expanded");

    const trigger = screen.getByTestId("controlled-trigger");
    await user.click(trigger);
    expect(handleOpenChange).toHaveBeenCalledWith(false);
  });

  it("handles keyboard shortcut to toggle sidebar", () => {
    renderWithProvider(
      <SidebarProvider>
        <Sidebar data-testid="kbd-sidebar" />
      </SidebarProvider>,
    );

    const sidebarContainer = screen.getByTestId("kbd-sidebar");
    const sidebar = sidebarContainer.closest('[data-slot="sidebar"]');
    expect(sidebar).toHaveAttribute("data-state", "expanded");

    // Press Ctrl+B
    act(() => {
      const event = new KeyboardEvent("keydown", {
        key: "b",
        ctrlKey: true,
        bubbles: true,
      });
      window.dispatchEvent(event);
    });

    expect(sidebar).toHaveAttribute("data-state", "collapsed");
  });
});
