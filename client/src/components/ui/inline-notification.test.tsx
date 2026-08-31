import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InlineNotification } from "./inline-notification";

describe("InlineNotification", () => {
  describe("success type", () => {
    it("renders with role='status'", () => {
      render(<InlineNotification type="success" message="All good" />);
      expect(screen.getByRole("status")).toBeInTheDocument();
    });

    it("displays the message text", () => {
      render(<InlineNotification type="success" message="Operation succeeded" />);
      expect(screen.getByText("Operation succeeded")).toBeInTheDocument();
    });

    it("applies green text class to the message", () => {
      render(<InlineNotification type="success" message="Done" />);
      expect(screen.getByText("Done")).toHaveClass("text-green-500");
    });
  });

  describe("error type", () => {
    it("renders with role='alert'", () => {
      render(<InlineNotification type="error" message="Something failed" />);
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    it("displays the message text", () => {
      render(<InlineNotification type="error" message="A server with this name already exists" />);
      expect(screen.getByText("A server with this name already exists")).toBeInTheDocument();
    });

    it("applies red text class to the message", () => {
      render(<InlineNotification type="error" message="Failed" />);
      expect(screen.getByText("Failed")).toHaveClass("text-red-600");
    });
  });

  describe("dismiss button", () => {
    it("renders dismiss button when onDismiss is provided", () => {
      render(<InlineNotification type="success" message="Done" onDismiss={vi.fn()} />);
      expect(screen.getByRole("button", { name: /dismiss notification/i })).toBeInTheDocument();
    });

    it("does not render dismiss button when onDismiss is not provided", () => {
      render(<InlineNotification type="success" message="Done" />);
      expect(screen.queryByRole("button", { name: /dismiss/i })).not.toBeInTheDocument();
    });

    it("calls onDismiss when dismiss button is clicked", async () => {
      const onDismiss = vi.fn();
      render(<InlineNotification type="error" message="Error" onDismiss={onDismiss} />);
      await userEvent.click(screen.getByRole("button", { name: /dismiss notification/i }));
      expect(onDismiss).toHaveBeenCalledTimes(1);
    });

    it("uses default dismissLabel when none is provided", () => {
      render(<InlineNotification type="success" message="Done" onDismiss={vi.fn()} />);
      expect(screen.getByRole("button", { name: "Dismiss notification" })).toBeInTheDocument();
    });

    it("uses custom dismissLabel when provided", () => {
      render(
        <InlineNotification
          type="error"
          message="OAuth failed"
          onDismiss={vi.fn()}
          dismissLabel="Dismiss OAuth notification"
        />,
      );
      expect(
        screen.getByRole("button", { name: "Dismiss OAuth notification" }),
      ).toBeInTheDocument();
    });
  });
});
