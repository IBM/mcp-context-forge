import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { PromptPreviewPanel } from "./PromptPreviewPanel";
import { promptsApi } from "@/api/prompts";
import { ApiError } from "@/api/client";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/api/prompts", () => ({
  promptsApi: { render: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PromptPreviewPanel", () => {
  it("renders the empty-state and Preview button before any run", () => {
    render(<PromptPreviewPanel promptId="greet" args={{}} />);
    expect(screen.getByRole("button", { name: /preview/i })).toBeInTheDocument();
    expect(screen.getByText(/No preview yet/i)).toBeInTheDocument();
  });

  it("calls the render API with the supplied args and shows status + messages", async () => {
    const rendered = {
      messages: [{ role: "user" as const, content: { type: "text" as const, text: "hi Alice" } }],
    };
    vi.mocked(promptsApi.render).mockResolvedValue(rendered);

    const user = userEvent.setup();
    render(<PromptPreviewPanel promptId="greet" args={{ user: "Alice" }} />);
    await user.click(screen.getByRole("button", { name: /preview/i }));

    expect(promptsApi.render).toHaveBeenCalledWith("greet", { user: "Alice" });
    await waitFor(() => expect(screen.getByText("200 OK")).toBeInTheDocument());
    expect(screen.getByText(/Render time:/)).toBeInTheDocument();
    expect(screen.getByText(/Rendered messages/)).toBeInTheDocument();
    // The serialized messages array contains the rendered text.
    expect(screen.getByText(/hi Alice/)).toBeInTheDocument();
  });

  it("toggles the button label to Re-run after the first successful render", async () => {
    vi.mocked(promptsApi.render).mockResolvedValue({ messages: [] });
    const user = userEvent.setup();
    render(<PromptPreviewPanel promptId="greet" args={{}} />);

    await user.click(screen.getByRole("button", { name: /^preview$/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /re-run/i })).toBeInTheDocument(),
    );
  });

  it("shows the failure state and surfaces an error toast when the render fails", async () => {
    const { toast } = await import("sonner");
    vi.mocked(promptsApi.render).mockRejectedValue(
      new ApiError(422, { detail: "missing required arg `user`" }, "Unprocessable"),
    );

    const user = userEvent.setup();
    render(<PromptPreviewPanel promptId="greet" args={{}} />);
    await user.click(screen.getByRole("button", { name: /preview/i }));

    await waitFor(() => expect(screen.getByText(/Render failed/i)).toBeInTheDocument());
    expect(screen.getByText(/missing required arg `user`/)).toBeInTheDocument();
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("disables the button while a render is in flight", async () => {
    let resolve: ((value: { messages: never[] }) => void) | undefined;
    vi.mocked(promptsApi.render).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );

    const user = userEvent.setup();
    render(<PromptPreviewPanel promptId="greet" args={{}} />);
    await user.click(screen.getByRole("button", { name: /preview/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /rendering/i })).toBeDisabled(),
    );
    resolve?.({ messages: [] });
  });
});
