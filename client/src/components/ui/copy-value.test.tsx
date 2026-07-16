import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { CopyValue } from "./copy-value";
import { copyToClipboard } from "@/lib/clipboard";

vi.mock("@/lib/clipboard", () => ({ copyToClipboard: vi.fn() }));

describe("CopyValue", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("builds the copy button's accessible label from the provided label", () => {
    render(<CopyValue label="Prompt ID" value="p-1" />);

    expect(screen.getByRole("button", { name: "Copy Prompt ID" })).toBeInTheDocument();
  });

  it("shows short values verbatim", () => {
    render(<CopyValue label="Prompt ID" value="p-1" />);

    expect(screen.getByText("p-1")).toBeInTheDocument();
  });

  it("middle-truncates long values in the display", () => {
    const longValue = "abcdefghijklmnopqrstuvwxyz0123456789";
    render(<CopyValue label="ID" value={longValue} />);

    // The visible text is truncated (default max 24 chars), not the raw value.
    expect(screen.queryByText(longValue)).not.toBeInTheDocument();
  });

  it("copies the full value (not the truncated display) when clicked", async () => {
    const user = userEvent.setup();
    const longValue = "abcdefghijklmnopqrstuvwxyz0123456789";
    render(<CopyValue label="ID" value={longValue} />);

    await user.click(screen.getByRole("button", { name: /copy id/i }));
    expect(copyToClipboard).toHaveBeenCalledWith(longValue);
  });
});
