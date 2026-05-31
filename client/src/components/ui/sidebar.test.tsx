import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
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

describe("Sidebar Components", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("SidebarProvider", () => {
    it("should render SidebarProvider", () => {
      const { container } = render(
        <SidebarProvider>
          <div data-testid="child">Content</div>
        </SidebarProvider>,
      );

      expect(screen.getByTestId("child")).toBeInTheDocument();
    });

    it("should render with default open state", () => {
      const { container } = render(
        <SidebarProvider defaultOpen={true}>
          <div>Content</div>
        </SidebarProvider>,
      );

      const wrapper = container.querySelector('[data-slot="sidebar-wrapper"]');
      expect(wrapper).toBeInTheDocument();
    });

    it("should render with collapsed state", () => {
      const { container } = render(
        <SidebarProvider defaultOpen={false}>
          <div>Content</div>
        </SidebarProvider>,
      );

      const wrapper = container.querySelector('[data-slot="sidebar-wrapper"]');
      expect(wrapper).toBeInTheDocument();
    });

    it("should set CSS variables for sidebar width", () => {
      const { container } = render(
        <SidebarProvider>
          <div>Content</div>
        </SidebarProvider>,
      );

      const wrapper = container.querySelector('[data-slot="sidebar-wrapper"]');
      const styles = wrapper?.getAttribute("style");
      expect(styles).toContain("--sidebar-width");
    });

    it("should accept onOpenChange callback", () => {
      const handleOpenChange = vi.fn();
      render(
        <SidebarProvider open={true} onOpenChange={handleOpenChange}>
          <div>Content</div>
        </SidebarProvider>,
      );

      expect(screen.getByText("Content")).toBeInTheDocument();
    });

    it("should handle controlled open prop", () => {
      const { rerender } = render(
        <SidebarProvider open={true}>
          <div>Content</div>
        </SidebarProvider>,
      );

      expect(screen.getByText("Content")).toBeInTheDocument();

      rerender(
        <SidebarProvider open={false}>
          <div>Content</div>
        </SidebarProvider>,
      );

      expect(screen.getByText("Content")).toBeInTheDocument();
    });
  });

  describe("useSidebar Hook", () => {
    it("should throw error when used outside SidebarProvider", () => {
      const TestComponent = () => {
        useSidebar();
        return <div>Test</div>;
      };

      expect(() => render(<TestComponent />)).toThrow("useSidebar must be used within a SidebarProvider");
    });

    it("should provide sidebar context", () => {
      let contextValue: any;

      const TestComponent = () => {
        contextValue = useSidebar();
        return <div>Test</div>;
      };

      render(
        <SidebarProvider>
          <TestComponent />
        </SidebarProvider>,
      );

      expect(contextValue).toHaveProperty("state");
      expect(contextValue).toHaveProperty("open");
      expect(contextValue).toHaveProperty("setOpen");
      expect(contextValue).toHaveProperty("isMobile");
      expect(contextValue).toHaveProperty("toggleSidebar");
    });
  });

  describe("Sidebar", () => {
    it("should render Sidebar with collapsible=none", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <div data-testid="sidebar-content">Content</div>
          </Sidebar>
        </SidebarProvider>,
      );

      expect(screen.getByTestId("sidebar-content")).toBeInTheDocument();
      expect(container.querySelector('[data-slot="sidebar"]')).toBeInTheDocument();
    });

    it("should render Sidebar with default props", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar>
            <div>Content</div>
          </Sidebar>
        </SidebarProvider>,
      );

      const sidebar = container.querySelector('[data-slot="sidebar"]');
      expect(sidebar).toBeInTheDocument();
    });

    it("should render Sidebar with left side", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar side="left">
            <div>Content</div>
          </Sidebar>
        </SidebarProvider>,
      );

      const sidebar = container.querySelector('[data-side="left"]');
      expect(sidebar).toBeInTheDocument();
    });

    it("should render Sidebar with right side", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar side="right">
            <div>Content</div>
          </Sidebar>
        </SidebarProvider>,
      );

      const sidebar = container.querySelector('[data-side="right"]');
      expect(sidebar).toBeInTheDocument();
    });

    it("should accept custom className", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar className="custom-sidebar">
            <div>Content</div>
          </Sidebar>
        </SidebarProvider>,
      );

      const container2 = container.querySelector('[data-slot="sidebar-container"]');
      expect(container2).toHaveClass("custom-sidebar");
    });
  });

  describe("SidebarTrigger", () => {
    it("should render SidebarTrigger button", () => {
      const { container } = render(
        <SidebarProvider>
          <SidebarTrigger data-testid="trigger" />
        </SidebarProvider>,
      );

      const trigger = screen.getByTestId("trigger");
      expect(trigger).toBeInTheDocument();
      expect(trigger.tagName).toBe("BUTTON");
    });

    it("should render with accessibility label", () => {
      const { container } = render(
        <SidebarProvider>
          <SidebarTrigger />
        </SidebarProvider>,
      );

      // Check for sr-only span with "Toggle Sidebar"
      const srOnly = container.querySelector("span.sr-only");
      expect(srOnly?.textContent).toBe("Toggle Sidebar");
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <SidebarTrigger data-testid="trigger" />
        </SidebarProvider>,
      );

      const trigger = screen.getByTestId("trigger");
      expect(trigger).toHaveAttribute("data-sidebar", "trigger");
      expect(trigger).toHaveAttribute("data-slot", "sidebar-trigger");
    });

    it("should accept custom className", () => {
      render(
        <SidebarProvider>
          <SidebarTrigger data-testid="trigger" className="custom-trigger" />
        </SidebarProvider>,
      );

      const trigger = screen.getByTestId("trigger");
      expect(trigger).toHaveClass("custom-trigger");
    });

    it("should call custom onClick handler", async () => {
      const handleClick = vi.fn();
      render(
        <SidebarProvider>
          <SidebarTrigger onClick={handleClick} data-testid="trigger" />
        </SidebarProvider>,
      );

      const trigger = screen.getByTestId("trigger");
      await userEvent.click(trigger);

      expect(handleClick).toHaveBeenCalled();
    });
  });

  describe("SidebarRail", () => {
    it("should render SidebarRail button", () => {
      const { container } = render(
        <SidebarProvider>
          <SidebarRail data-testid="rail" />
        </SidebarProvider>,
      );

      const rail = screen.getByTestId("rail");
      expect(rail).toBeInTheDocument();
      expect(rail.tagName).toBe("BUTTON");
    });

    it("should have accessibility attributes", () => {
      render(
        <SidebarProvider>
          <SidebarRail data-testid="rail" />
        </SidebarProvider>,
      );

      const rail = screen.getByTestId("rail");
      expect(rail).toHaveAttribute("aria-label", "Toggle Sidebar");
      expect(rail).toHaveAttribute("title", "Toggle Sidebar");
    });

    it("should have tabIndex -1", () => {
      render(
        <SidebarProvider>
          <SidebarRail data-testid="rail" />
        </SidebarProvider>,
      );

      const rail = screen.getByTestId("rail");
      expect(rail).toHaveAttribute("tabindex", "-1");
    });

    it("should accept custom className", () => {
      render(
        <SidebarProvider>
          <SidebarRail data-testid="rail" className="custom-rail" />
        </SidebarProvider>,
      );

      const rail = screen.getByTestId("rail");
      expect(rail).toHaveClass("custom-rail");
    });
  });

  describe("SidebarInset", () => {
    it("should render SidebarInset as main element", () => {
      const { container } = render(
        <SidebarInset data-testid="inset">Content</SidebarInset>,
      );

      const inset = screen.getByTestId("inset");
      expect(inset).toBeInTheDocument();
      expect(inset.tagName).toBe("MAIN");
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarInset data-testid="inset">Content</SidebarInset>,
      );

      const inset = screen.getByTestId("inset");
      expect(inset).toHaveAttribute("data-slot", "sidebar-inset");
    });

    it("should accept custom className", () => {
      render(
        <SidebarInset data-testid="inset" className="custom-inset">
          Content
        </SidebarInset>,
      );

      const inset = screen.getByTestId("inset");
      expect(inset).toHaveClass("custom-inset");
    });
  });

  describe("SidebarHeader", () => {
    it("should render SidebarHeader", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarHeader data-testid="header">Header</SidebarHeader>
          </Sidebar>
        </SidebarProvider>,
      );

      expect(screen.getByTestId("header")).toBeInTheDocument();
    });

    it("should render as div element", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarHeader data-testid="header">Header</SidebarHeader>
          </Sidebar>
        </SidebarProvider>,
      );

      const header = screen.getByTestId("header");
      expect(header.tagName).toBe("DIV");
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarHeader data-testid="header">Header</SidebarHeader>
          </Sidebar>
        </SidebarProvider>,
      );

      const header = screen.getByTestId("header");
      expect(header).toHaveAttribute("data-sidebar", "header");
      expect(header).toHaveAttribute("data-slot", "sidebar-header");
    });
  });

  describe("SidebarFooter", () => {
    it("should render SidebarFooter", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarFooter data-testid="footer">Footer</SidebarFooter>
          </Sidebar>
        </SidebarProvider>,
      );

      expect(screen.getByTestId("footer")).toBeInTheDocument();
    });

    it("should render as div element", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarFooter data-testid="footer">Footer</SidebarFooter>
          </Sidebar>
        </SidebarProvider>,
      );

      const footer = screen.getByTestId("footer");
      expect(footer.tagName).toBe("DIV");
    });
  });

  describe("SidebarContent", () => {
    it("should render SidebarContent", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarContent data-testid="content">Content</SidebarContent>
          </Sidebar>
        </SidebarProvider>,
      );

      expect(screen.getByTestId("content")).toBeInTheDocument();
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarContent data-testid="content">Content</SidebarContent>
          </Sidebar>
        </SidebarProvider>,
      );

      const content = screen.getByTestId("content");
      expect(content).toHaveAttribute("data-sidebar", "content");
      expect(content).toHaveAttribute("data-slot", "sidebar-content");
    });
  });

  describe("SidebarInput", () => {
    it("should render SidebarInput as input element", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarInput data-testid="input" placeholder="Search" />
          </Sidebar>
        </SidebarProvider>,
      );

      const input = screen.getByTestId("input") as HTMLInputElement;
      expect(input).toBeInTheDocument();
      expect(input.tagName).toBe("INPUT");
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarInput data-testid="input" />
          </Sidebar>
        </SidebarProvider>,
      );

      const input = screen.getByTestId("input");
      expect(input).toHaveAttribute("data-sidebar", "input");
      expect(input).toHaveAttribute("data-slot", "sidebar-input");
    });

    it("should accept placeholder text", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarInput data-testid="input" placeholder="Search items" />
          </Sidebar>
        </SidebarProvider>,
      );

      const input = screen.getByPlaceholderText("Search items") as HTMLInputElement;
      expect(input).toBeInTheDocument();
    });
  });

  describe("SidebarGroup", () => {
    it("should render SidebarGroup", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarGroup data-testid="group">Group</SidebarGroup>
          </Sidebar>
        </SidebarProvider>,
      );

      expect(screen.getByTestId("group")).toBeInTheDocument();
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarGroup data-testid="group">Group</SidebarGroup>
          </Sidebar>
        </SidebarProvider>,
      );

      const group = screen.getByTestId("group");
      expect(group).toHaveAttribute("data-sidebar", "group");
      expect(group).toHaveAttribute("data-slot", "sidebar-group");
    });
  });

  describe("SidebarGroupLabel", () => {
    it("should render SidebarGroupLabel", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarGroupLabel data-testid="label">Label</SidebarGroupLabel>
          </Sidebar>
        </SidebarProvider>,
      );

      expect(screen.getByTestId("label")).toBeInTheDocument();
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarGroupLabel data-testid="label">Label</SidebarGroupLabel>
          </Sidebar>
        </SidebarProvider>,
      );

      const label = screen.getByTestId("label");
      expect(label).toHaveAttribute("data-sidebar", "group-label");
      expect(label).toHaveAttribute("data-slot", "sidebar-group-label");
    });
  });

  describe("SidebarGroupContent", () => {
    it("should render SidebarGroupContent", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarGroupContent data-testid="group-content">Content</SidebarGroupContent>
          </Sidebar>
        </SidebarProvider>,
      );

      expect(screen.getByTestId("group-content")).toBeInTheDocument();
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarGroupContent data-testid="group-content">Content</SidebarGroupContent>
          </Sidebar>
        </SidebarProvider>,
      );

      const content = screen.getByTestId("group-content");
      expect(content).toHaveAttribute("data-sidebar", "group-content");
      expect(content).toHaveAttribute("data-slot", "sidebar-group-content");
    });
  });

  describe("SidebarGroupAction", () => {
    it("should render SidebarGroupAction button", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarGroupAction data-testid="action">Action</SidebarGroupAction>
          </Sidebar>
        </SidebarProvider>,
      );

      const action = screen.getByTestId("action");
      expect(action).toBeInTheDocument();
      expect(action.tagName).toBe("BUTTON");
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarGroupAction data-testid="action">Action</SidebarGroupAction>
          </Sidebar>
        </SidebarProvider>,
      );

      const action = screen.getByTestId("action");
      expect(action).toHaveAttribute("data-sidebar", "group-action");
      expect(action).toHaveAttribute("data-slot", "sidebar-group-action");
    });
  });

  describe("SidebarMenu", () => {
    it("should render SidebarMenu as ul element", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenu data-testid="menu">
              <li>Item</li>
            </SidebarMenu>
          </Sidebar>
        </SidebarProvider>,
      );

      const menu = screen.getByTestId("menu");
      expect(menu).toBeInTheDocument();
      expect(menu.tagName).toBe("UL");
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenu data-testid="menu">
              <li>Item</li>
            </SidebarMenu>
          </Sidebar>
        </SidebarProvider>,
      );

      const menu = screen.getByTestId("menu");
      expect(menu).toHaveAttribute("data-sidebar", "menu");
      expect(menu).toHaveAttribute("data-slot", "sidebar-menu");
    });
  });

  describe("SidebarMenuItem", () => {
    it("should render SidebarMenuItem as li element", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenu>
              <SidebarMenuItem data-testid="menu-item">Item</SidebarMenuItem>
            </SidebarMenu>
          </Sidebar>
        </SidebarProvider>,
      );

      const item = screen.getByTestId("menu-item");
      expect(item).toBeInTheDocument();
      expect(item.tagName).toBe("LI");
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenu>
              <SidebarMenuItem data-testid="menu-item">Item</SidebarMenuItem>
            </SidebarMenu>
          </Sidebar>
        </SidebarProvider>,
      );

      const item = screen.getByTestId("menu-item");
      expect(item).toHaveAttribute("data-sidebar", "menu-item");
      expect(item).toHaveAttribute("data-slot", "sidebar-menu-item");
    });
  });

  describe("SidebarMenuButton", () => {
    it("should render SidebarMenuButton button", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton data-testid="menu-button">Button</SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </Sidebar>
        </SidebarProvider>,
      );

      const button = screen.getByTestId("menu-button");
      expect(button).toBeInTheDocument();
      expect(button.tagName).toBe("BUTTON");
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton data-testid="menu-button">Button</SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </Sidebar>
        </SidebarProvider>,
      );

      const button = screen.getByTestId("menu-button");
      expect(button).toHaveAttribute("data-sidebar", "menu-button");
      expect(button).toHaveAttribute("data-slot", "sidebar-menu-button");
    });

    it("should handle isActive prop", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton data-testid="menu-button" isActive={true}>
                  Active
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </Sidebar>
        </SidebarProvider>,
      );

      const button = screen.getByTestId("menu-button");
      expect(button).toHaveAttribute("data-active", "true");
    });
  });

  describe("SidebarMenuBadge", () => {
    it("should render SidebarMenuBadge", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuBadge data-testid="badge">5</SidebarMenuBadge>
              </SidebarMenuItem>
            </SidebarMenu>
          </Sidebar>
        </SidebarProvider>,
      );

      expect(screen.getByTestId("badge")).toBeInTheDocument();
      expect(screen.getByText("5")).toBeInTheDocument();
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuBadge data-testid="badge">5</SidebarMenuBadge>
              </SidebarMenuItem>
            </SidebarMenu>
          </Sidebar>
        </SidebarProvider>,
      );

      const badge = screen.getByTestId("badge");
      expect(badge).toHaveAttribute("data-sidebar", "menu-badge");
      expect(badge).toHaveAttribute("data-slot", "sidebar-menu-badge");
    });
  });

  describe("SidebarMenuAction", () => {
    it("should render SidebarMenuAction button", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuAction data-testid="menu-action">Action</SidebarMenuAction>
              </SidebarMenuItem>
            </SidebarMenu>
          </Sidebar>
        </SidebarProvider>,
      );

      const action = screen.getByTestId("menu-action");
      expect(action).toBeInTheDocument();
      expect(action.tagName).toBe("BUTTON");
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuAction data-testid="menu-action">Action</SidebarMenuAction>
              </SidebarMenuItem>
            </SidebarMenu>
          </Sidebar>
        </SidebarProvider>,
      );

      const action = screen.getByTestId("menu-action");
      expect(action).toHaveAttribute("data-sidebar", "menu-action");
      expect(action).toHaveAttribute("data-slot", "sidebar-menu-action");
    });
  });

  describe("SidebarMenuSkeleton", () => {
    it("should render SidebarMenuSkeleton", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenuSkeleton data-testid="skeleton" />
          </Sidebar>
        </SidebarProvider>,
      );

      expect(screen.getByTestId("skeleton")).toBeInTheDocument();
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenuSkeleton data-testid="skeleton" />
          </Sidebar>
        </SidebarProvider>,
      );

      const skeleton = screen.getByTestId("skeleton");
      expect(skeleton).toHaveAttribute("data-sidebar", "menu-skeleton");
      expect(skeleton).toHaveAttribute("data-slot", "sidebar-menu-skeleton");
    });

    it("should render with showIcon prop", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenuSkeleton data-testid="skeleton" showIcon={true} />
          </Sidebar>
        </SidebarProvider>,
      );

      const iconSkeleton = container.querySelector('[data-sidebar="menu-skeleton-icon"]');
      expect(iconSkeleton).toBeInTheDocument();
    });
  });

  describe("SidebarMenuSub", () => {
    it("should render SidebarMenuSub as ul element", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenuSub data-testid="menu-sub">
              <li>SubItem</li>
            </SidebarMenuSub>
          </Sidebar>
        </SidebarProvider>,
      );

      const sub = screen.getByTestId("menu-sub");
      expect(sub).toBeInTheDocument();
      expect(sub.tagName).toBe("UL");
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenuSub data-testid="menu-sub">
              <li>SubItem</li>
            </SidebarMenuSub>
          </Sidebar>
        </SidebarProvider>,
      );

      const sub = screen.getByTestId("menu-sub");
      expect(sub).toHaveAttribute("data-sidebar", "menu-sub");
      expect(sub).toHaveAttribute("data-slot", "sidebar-menu-sub");
    });
  });

  describe("SidebarMenuSubItem", () => {
    it("should render SidebarMenuSubItem as li element", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenuSub>
              <SidebarMenuSubItem data-testid="menu-sub-item">Item</SidebarMenuSubItem>
            </SidebarMenuSub>
          </Sidebar>
        </SidebarProvider>,
      );

      const item = screen.getByTestId("menu-sub-item");
      expect(item).toBeInTheDocument();
      expect(item.tagName).toBe("LI");
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenuSub>
              <SidebarMenuSubItem data-testid="menu-sub-item">Item</SidebarMenuSubItem>
            </SidebarMenuSub>
          </Sidebar>
        </SidebarProvider>,
      );

      const item = screen.getByTestId("menu-sub-item");
      expect(item).toHaveAttribute("data-sidebar", "menu-sub-item");
      expect(item).toHaveAttribute("data-slot", "sidebar-menu-sub-item");
    });
  });

  describe("SidebarMenuSubButton", () => {
    it("should render SidebarMenuSubButton as anchor element", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenuSub>
              <SidebarMenuSubItem>
                <SidebarMenuSubButton data-testid="menu-sub-button" href="#">
                  Link
                </SidebarMenuSubButton>
              </SidebarMenuSubItem>
            </SidebarMenuSub>
          </Sidebar>
        </SidebarProvider>,
      );

      const button = screen.getByTestId("menu-sub-button");
      expect(button).toBeInTheDocument();
      expect(button.tagName).toBe("A");
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarMenuSub>
              <SidebarMenuSubItem>
                <SidebarMenuSubButton data-testid="menu-sub-button" href="#">
                  Link
                </SidebarMenuSubButton>
              </SidebarMenuSubItem>
            </SidebarMenuSub>
          </Sidebar>
        </SidebarProvider>,
      );

      const button = screen.getByTestId("menu-sub-button");
      expect(button).toHaveAttribute("data-sidebar", "menu-sub-button");
      expect(button).toHaveAttribute("data-slot", "sidebar-menu-sub-button");
    });
  });

  describe("SidebarSeparator", () => {
    it("should render SidebarSeparator", () => {
      render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarSeparator data-testid="separator" />
          </Sidebar>
        </SidebarProvider>,
      );

      expect(screen.getByTestId("separator")).toBeInTheDocument();
    });

    it("should have correct data attributes", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarSeparator data-testid="separator" />
          </Sidebar>
        </SidebarProvider>,
      );

      const separator = screen.getByTestId("separator");
      expect(separator).toHaveAttribute("data-sidebar", "separator");
      expect(separator).toHaveAttribute("data-slot", "sidebar-separator");
    });
  });

  describe("Full Sidebar Integration", () => {
    it("should render complete sidebar structure", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarHeader>Header</SidebarHeader>
            <SidebarContent>
              <SidebarGroup>
                <SidebarGroupLabel>Label</SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    <SidebarMenuItem>
                      <SidebarMenuButton>Menu Item</SidebarMenuButton>
                    </SidebarMenuItem>
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            </SidebarContent>
            <SidebarFooter>Footer</SidebarFooter>
          </Sidebar>
          <SidebarInset>Main Content</SidebarInset>
        </SidebarProvider>,
      );

      expect(screen.getByText("Header")).toBeInTheDocument();
      expect(screen.getByText("Label")).toBeInTheDocument();
      expect(screen.getByText("Menu Item")).toBeInTheDocument();
      expect(screen.getByText("Footer")).toBeInTheDocument();
      expect(screen.getByText("Main Content")).toBeInTheDocument();
    });

    it("should render sidebar with menu hierarchy", () => {
      const { container } = render(
        <SidebarProvider>
          <Sidebar collapsible="none">
            <SidebarContent>
              <SidebarGroup>
                <SidebarMenu>
                  <SidebarMenuItem>
                    <SidebarMenuButton>Parent Item</SidebarMenuButton>
                    <SidebarMenuSub>
                      <SidebarMenuSubItem>
                        <SidebarMenuSubButton href="#">Sub Item</SidebarMenuSubButton>
                      </SidebarMenuSubItem>
                    </SidebarMenuSub>
                  </SidebarMenuItem>
                </SidebarMenu>
              </SidebarGroup>
            </SidebarContent>
          </Sidebar>
        </SidebarProvider>,
      );

      expect(screen.getByText("Parent Item")).toBeInTheDocument();
      expect(screen.getByText("Sub Item")).toBeInTheDocument();
    });
  });
});
