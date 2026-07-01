import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { I18nProvider } from "@/i18n";
import { usePromptPreview } from "./usePromptPreview";
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

function setup(promptId = "greet", args: Record<string, string> = {}) {
  return renderHook(() => usePromptPreview(promptId, args), {
    wrapper: ({ children }) => <I18nProvider>{children}</I18nProvider>,
  });
}

describe("usePromptPreview", () => {
  it("starts in an idle state with no result and no error", () => {
    const { result } = setup();
    expect(result.current).toMatchObject({
      isLoading: false,
      result: null,
      error: null,
      hasRun: false,
    });
  });

  it("captures a successful render with a measured renderTimeMs", async () => {
    vi.mocked(promptsApi.render).mockResolvedValue({ messages: [] });
    const { result } = setup("greet", { user: "Alice" });

    await act(async () => {
      await result.current.run();
    });

    expect(promptsApi.render).toHaveBeenCalledWith("greet", { user: "Alice" });
    expect(result.current.result).not.toBeNull();
    expect(result.current.result?.renderTimeMs).toBeGreaterThanOrEqual(0);
    expect(result.current.hasRun).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it("unwraps ApiError.detail into a readable failure message and toasts", async () => {
    const { toast } = await import("sonner");
    vi.mocked(promptsApi.render).mockRejectedValue(
      new ApiError(422, { detail: "missing required arg `user`" }, "Unprocessable"),
    );
    const { result } = setup();

    await act(async () => {
      await result.current.run();
    });

    expect(result.current.error?.message).toBe("missing required arg `user`");
    expect(result.current.result).toBeNull();
    expect(result.current.hasRun).toBe(true);
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("clears result and error when promptId changes", async () => {
    vi.mocked(promptsApi.render).mockResolvedValue({ messages: [] });
    const { result, rerender } = renderHook(({ id }: { id: string }) => usePromptPreview(id, {}), {
      initialProps: { id: "p1" },
      wrapper: ({ children }) => <I18nProvider>{children}</I18nProvider>,
    });

    await act(async () => {
      await result.current.run();
    });
    expect(result.current.hasRun).toBe(true);

    rerender({ id: "p2" });
    expect(result.current.result).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.hasRun).toBe(false);
  });

  it("flips isLoading while the request is in flight", async () => {
    let resolve: ((value: { messages: never[] }) => void) | undefined;
    vi.mocked(promptsApi.render).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const { result } = setup();

    let pending: Promise<void>;
    act(() => {
      pending = result.current.run();
    });
    await waitFor(() => expect(result.current.isLoading).toBe(true));
    resolve?.({ messages: [] });
    await act(async () => {
      await pending!;
    });
    expect(result.current.isLoading).toBe(false);
  });
});
