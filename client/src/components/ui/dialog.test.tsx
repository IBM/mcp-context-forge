import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import {
  Dialog,
  DialogTrigger,
  DialogPortal,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
  DialogOverlay,
  DialogClose,
} from "./dialog";

describe("Dialog Components", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Dialog Root", () => {
    it("should render Dialog root component", () => {
      const { container } = render(
        <Dialog open>
          <div data-testid="dialog-child">Content</div>
        </Dialog>,
      );

      const child = screen.getByTestId("dialog-child");
      expect(child).toBeInTheDocument();
    });

    it("should handle open state prop", () => {
      const handleOpenChange = vi.fn();
      const { rerender } = render(
        <Dialog open={true} onOpenChange={handleOpenChange}>
          <div data-testid="content">Dialog is open</div>
        </Dialog>,
      );

      expect(screen.getByTestId("content")).toBeInTheDocument();

      rerender(
        <Dialog open={false} onOpenChange={handleOpenChange}>
          <div data-testid="content">Dialog is open</div>
        </Dialog>,
      );
    });
  });

  describe("DialogTrigger", () => {
    it("should render DialogTrigger button", () => {
      render(
        <Dialog open={true}>
          <DialogTrigger data-testid="trigger">Open Dialog</DialogTrigger>
        </Dialog>,
      );

      const trigger = screen.getByTestId("trigger");
      expect(trigger).toBeInTheDocument();
    });

    it("should render DialogTrigger as button element", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogTrigger data-testid="trigger">Open</DialogTrigger>
        </Dialog>,
      );

      const trigger = screen.getByTestId("trigger");
      expect(trigger.tagName).toBe("BUTTON");
    });

    it("should accept children as text", () => {
      render(
        <Dialog open={true}>
          <DialogTrigger>Click to open</DialogTrigger>
        </Dialog>,
      );

      expect(screen.getByText("Click to open")).toBeInTheDocument();
    });
  });

  describe("DialogOverlay", () => {
    it("should render DialogOverlay", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle>Test</DialogTitle>
            <DialogOverlay data-testid="overlay" />
          </DialogContent>
        </Dialog>,
      );

      const overlay = screen.getByTestId("overlay");
      expect(overlay).toBeInTheDocument();
    });

    it("should have fixed positioning classes", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle>Test</DialogTitle>
            <DialogOverlay data-testid="overlay" />
          </DialogContent>
        </Dialog>,
      );

      const overlay = screen.getByTestId("overlay");
      expect(overlay).toHaveClass("fixed");
      expect(overlay).toHaveClass("inset-0");
      expect(overlay).toHaveClass("z-50");
    });

    it("should have semi-transparent background color", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle>Test</DialogTitle>
            <DialogOverlay data-testid="overlay" />
          </DialogContent>
        </Dialog>,
      );

      const overlay = screen.getByTestId("overlay");
      expect(overlay).toHaveClass("bg-black/80");
    });

    it("should accept custom className", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle>Test</DialogTitle>
            <DialogOverlay data-testid="overlay" className="custom-overlay" />
          </DialogContent>
        </Dialog>,
      );

      const overlay = screen.getByTestId("overlay");
      expect(overlay).toHaveClass("custom-overlay");
    });

    it("should accept ref forwarding", () => {
      const ref = React.createRef<HTMLDivElement>();
      render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle>Test</DialogTitle>
            <DialogOverlay ref={ref} data-testid="overlay" />
          </DialogContent>
        </Dialog>,
      );

      expect(ref.current).toBeInTheDocument();
    });
  });

  describe("DialogContent", () => {
    it("should render DialogContent without crashing", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle>Test</DialogTitle>
            <span>Dialog content</span>
          </DialogContent>
        </Dialog>,
      );

      expect(screen.getByText("Dialog content")).toBeInTheDocument();
    });

    it("should render DialogContent with children", () => {
      render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle>Test</DialogTitle>
            <div data-testid="dialog-body">Test content</div>
          </DialogContent>
        </Dialog>,
      );

      expect(screen.getByTestId("dialog-body")).toBeInTheDocument();
    });

    it("should have fixed positioning classes", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogContent data-testid="content">
            <DialogTitle>Test</DialogTitle>
            Content
          </DialogContent>
        </Dialog>,
      );

      const content = screen.getByTestId("content");
      expect(content).toHaveClass("fixed");
      expect(content).toHaveClass("left-[50%]");
      expect(content).toHaveClass("top-[50%]");
      expect(content).toHaveClass("z-50");
    });

    it("should include close button", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle>Test</DialogTitle>
            Content
          </DialogContent>
        </Dialog>,
      );

      // Look for close button (X icon) - rendered in portal
      const closeButton = document.querySelector("[role='dialog'] button[type='button']");
      expect(closeButton).toBeInTheDocument();
    });

    it("should render X icon for close button", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle>Test</DialogTitle>
            Content
          </DialogContent>
        </Dialog>,
      );

      // Check for SVG icon (X from lucide-react) - rendered in portal
      const svg = document.querySelector("[role='dialog'] svg");
      expect(svg).toBeInTheDocument();
    });

    it("should render accessibility label for close button", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogContent>Content</DialogContent>
        </Dialog>,
      );

      // Look for sr-only span with "Close" - rendered in portal
      const srOnly = document.querySelector("span.sr-only");
      expect(srOnly?.textContent).toBe("Close");
    });

    it("should accept custom className", () => {
      render(
        <Dialog open={true}>
          <DialogContent data-testid="content" className="custom-dialog">
            <DialogTitle>Test</DialogTitle>
            Content
          </DialogContent>
        </Dialog>,
      );

      const content = screen.getByTestId("content");
      expect(content).toHaveClass("custom-dialog");
    });

    it("should accept ref forwarding", () => {
      const ref = React.createRef<HTMLDivElement>();
      render(
        <Dialog open={true}>
          <DialogContent ref={ref}>
            <DialogTitle>Test</DialogTitle>
            Content
          </DialogContent>
        </Dialog>,
      );

      expect(ref.current).toBeInTheDocument();
    });

    it("should render overlay inside content", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle>Test</DialogTitle>
            Content
          </DialogContent>
        </Dialog>,
      );

      // Should have overlay before content (overlay is rendered in a portal)
      const overlay = document.querySelector('[class*="bg-black"]');
      expect(overlay).toBeInTheDocument();
    });
  });

  describe("DialogHeader", () => {
    it("should render DialogHeader", () => {
      const { container } = render(
        <DialogHeader data-testid="header">
          <span>Header content</span>
        </DialogHeader>,
      );

      expect(screen.getByTestId("header")).toBeInTheDocument();
      expect(screen.getByText("Header content")).toBeInTheDocument();
    });

    it("should render as div element", () => {
      const { container } = render(
        <DialogHeader data-testid="header">Content</DialogHeader>,
      );

      const header = screen.getByTestId("header");
      expect(header.tagName).toBe("DIV");
    });

    it("should have flex layout classes", () => {
      render(
        <DialogHeader data-testid="header">Content</DialogHeader>,
      );

      const header = screen.getByTestId("header");
      expect(header).toHaveClass("flex");
      expect(header).toHaveClass("flex-col");
    });

    it("should accept custom className", () => {
      render(
        <DialogHeader data-testid="header" className="custom-header">
          Content
        </DialogHeader>,
      );

      const header = screen.getByTestId("header");
      expect(header).toHaveClass("custom-header");
    });

    it("should have displayName property", () => {
      expect(DialogHeader.displayName).toBe("DialogHeader");
    });
  });

  describe("DialogFooter", () => {
    it("should render DialogFooter", () => {
      const { container } = render(
        <DialogFooter data-testid="footer">
          <button>Action</button>
        </DialogFooter>,
      );

      expect(screen.getByTestId("footer")).toBeInTheDocument();
    });

    it("should render as div element", () => {
      const { container } = render(
        <DialogFooter data-testid="footer">Content</DialogFooter>,
      );

      const footer = screen.getByTestId("footer");
      expect(footer.tagName).toBe("DIV");
    });

    it("should have flex layout classes", () => {
      render(
        <DialogFooter data-testid="footer">Content</DialogFooter>,
      );

      const footer = screen.getByTestId("footer");
      expect(footer).toHaveClass("flex");
      expect(footer).toHaveClass("flex-col-reverse");
    });

    it("should contain buttons", () => {
      render(
        <Dialog open={true}>
          <DialogContent>
            <DialogFooter data-testid="footer">
              <button>Cancel</button>
              <button>Save</button>
            </DialogFooter>
          </DialogContent>
        </Dialog>,
      );

      expect(screen.getByText("Cancel")).toBeInTheDocument();
      expect(screen.getByText("Save")).toBeInTheDocument();
    });

    it("should accept custom className", () => {
      render(
        <DialogFooter data-testid="footer" className="custom-footer">
          Content
        </DialogFooter>,
      );

      const footer = screen.getByTestId("footer");
      expect(footer).toHaveClass("custom-footer");
    });

    it("should have displayName property", () => {
      expect(DialogFooter.displayName).toBe("DialogFooter");
    });
  });

  describe("DialogTitle", () => {
    it("should render DialogTitle", () => {
      render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle>Dialog Title</DialogTitle>
          </DialogContent>
        </Dialog>,
      );

      expect(screen.getByText("Dialog Title")).toBeInTheDocument();
    });

    it("should render as h2 element", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle data-testid="title">Title</DialogTitle>
          </DialogContent>
        </Dialog>,
      );

      const title = screen.getByTestId("title");
      expect(title.tagName).toBe("H2");
    });

    it("should have semantic heading classes", () => {
      render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle data-testid="title">Title</DialogTitle>
          </DialogContent>
        </Dialog>,
      );

      const title = screen.getByTestId("title");
      expect(title).toHaveClass("text-lg");
      expect(title).toHaveClass("font-semibold");
    });

    it("should accept custom className", () => {
      render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle data-testid="title" className="custom-title">
              Title
            </DialogTitle>
          </DialogContent>
        </Dialog>,
      );

      const title = screen.getByTestId("title");
      expect(title).toHaveClass("custom-title");
    });

    it("should accept ref forwarding", () => {
      const ref = React.createRef<HTMLHeadingElement>();
      render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle ref={ref}>Title</DialogTitle>
          </DialogContent>
        </Dialog>,
      );

      expect(ref.current).toBeInTheDocument();
      expect(ref.current?.tagName).toBe("H2");
    });

    it("should have displayName property", () => {
      expect(DialogTitle.displayName).toBe("DialogTitle");
    });
  });

  describe("DialogDescription", () => {
    it("should render DialogDescription", () => {
      render(
        <Dialog open={true}>
          <DialogContent>
            <DialogDescription>Dialog description</DialogDescription>
          </DialogContent>
        </Dialog>,
      );

      expect(screen.getByText("Dialog description")).toBeInTheDocument();
    });

    it("should render as paragraph element", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogContent>
            <DialogDescription data-testid="desc">Description</DialogDescription>
          </DialogContent>
        </Dialog>,
      );

      const desc = screen.getByTestId("desc");
      expect(desc.tagName).toBe("P");
    });

    it("should have muted text color classes", () => {
      render(
        <Dialog open={true}>
          <DialogContent>
            <DialogDescription data-testid="desc">Description</DialogDescription>
          </DialogContent>
        </Dialog>,
      );

      const desc = screen.getByTestId("desc");
      expect(desc).toHaveClass("text-sm");
      expect(desc).toHaveClass("text-muted-foreground");
    });

    it("should accept custom className", () => {
      render(
        <Dialog open={true}>
          <DialogContent>
            <DialogDescription data-testid="desc" className="custom-desc">
              Description
            </DialogDescription>
          </DialogContent>
        </Dialog>,
      );

      const desc = screen.getByTestId("desc");
      expect(desc).toHaveClass("custom-desc");
    });

    it("should accept ref forwarding", () => {
      const ref = React.createRef<HTMLParagraphElement>();
      render(
        <Dialog open={true}>
          <DialogContent>
            <DialogDescription ref={ref}>Description</DialogDescription>
          </DialogContent>
        </Dialog>,
      );

      expect(ref.current).toBeInTheDocument();
      expect(ref.current?.tagName).toBe("P");
    });

    it("should have displayName property", () => {
      expect(DialogDescription.displayName).toBe("DialogDescription");
    });
  });

  describe("DialogClose", () => {
    it("should render DialogClose button", () => {
      render(
        <Dialog open={true}>
          <DialogContent>
            <DialogClose data-testid="close-btn">Close</DialogClose>
          </DialogContent>
        </Dialog>,
      );

      expect(screen.getByTestId("close-btn")).toBeInTheDocument();
    });

    it("should render as button element", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogContent>
            <DialogClose data-testid="close-btn">Close</DialogClose>
          </DialogContent>
        </Dialog>,
      );

      const closeBtn = screen.getByTestId("close-btn");
      expect(closeBtn.tagName).toBe("BUTTON");
    });
  });

  describe("DialogPortal", () => {
    it("should render DialogPortal", () => {
      render(
        <Dialog open={true}>
          <DialogPortal>
            <div data-testid="portal-content">Portal content</div>
          </DialogPortal>
        </Dialog>,
      );

      expect(screen.getByTestId("portal-content")).toBeInTheDocument();
    });
  });

  describe("Full Dialog Integration", () => {
    it("should render complete dialog structure", () => {
      const { container } = render(
        <Dialog open={true}>
          <DialogTrigger>Open</DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Title</DialogTitle>
              <DialogDescription>Description</DialogDescription>
            </DialogHeader>
            <div>Main content</div>
            <DialogFooter>
              <button>Cancel</button>
              <button>Save</button>
            </DialogFooter>
          </DialogContent>
        </Dialog>,
      );

      expect(screen.getByText("Title")).toBeInTheDocument();
      expect(screen.getByText("Description")).toBeInTheDocument();
      expect(screen.getByText("Main content")).toBeInTheDocument();
      expect(screen.getByText("Cancel")).toBeInTheDocument();
      expect(screen.getByText("Save")).toBeInTheDocument();
    });

    it("should render multiple dialogs independently", () => {
      const { container } = render(
        <div>
          <Dialog open={true}>
            <DialogContent>
              <DialogTitle>Dialog 1</DialogTitle>
            </DialogContent>
          </Dialog>
          <Dialog open={true}>
            <DialogContent>
              <DialogTitle>Dialog 2</DialogTitle>
            </DialogContent>
          </Dialog>
        </div>,
      );

      expect(screen.getByText("Dialog 1")).toBeInTheDocument();
      expect(screen.getByText("Dialog 2")).toBeInTheDocument();
    });

    it("should handle dialog state changes", () => {
      const { rerender } = render(
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle>Open Dialog</DialogTitle>
          </DialogContent>
        </Dialog>,
      );

      expect(screen.getByText("Open Dialog")).toBeInTheDocument();

      rerender(
        <Dialog open={false}>
          <DialogContent>
            <DialogTitle>Open Dialog</DialogTitle>
          </DialogContent>
        </Dialog>,
      );
    });
  });
});
