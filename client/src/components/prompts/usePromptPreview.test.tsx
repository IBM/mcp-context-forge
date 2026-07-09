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

function setup(promptName = "greet", args: Record<string, string> = {}) {
  return renderHook(() => usePromptPreview(promptName, args), {
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

  it("captures a successful render with a measured renderTimeMs and the HTTP status", async () => {
    vi.mocked(promptsApi.render).mockResolvedValue({ rendered: { messages: [] }, status: 200 });
    const { result } = setup("greet", { user: "Alice" });

    await act(async () => {
      await result.current.run();
    });

    expect(promptsApi.render).toHaveBeenCalledWith("greet", { user: "Alice" });
    expect(result.current.result).not.toBeNull();
    expect(result.current.result?.renderTimeMs).toBeGreaterThanOrEqual(0);
    expect(result.current.result?.status).toBe(200);
    expect(result.current.hasRun).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it("unwraps ApiError.detail into a readable failure message, captures the status, and toasts", async () => {
    const { toast } = await import("sonner");
    vi.mocked(promptsApi.render).mockRejectedValue(
      new ApiError(422, { detail: "missing required arg `user`" }, "Unprocessable"),
    );
    const { result } = setup();

    await act(async () => {
      await result.current.run();
    });

    expect(result.current.error?.message).toBe("missing required arg `user`");
    expect(result.current.error?.status).toBe(422);
    expect(result.current.result).toBeNull();
    expect(result.current.hasRun).toBe(true);
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("leaves error.status as null for non-Api errors (e.g. network failures)", async () => {
    vi.mocked(promptsApi.render).mockRejectedValue(new Error("network offline"));
    const { result } = setup();

    await act(async () => {
      await result.current.run();
    });

    expect(result.current.error?.message).toBe("network offline");
    expect(result.current.error?.status).toBeNull();
  });

  it("clears result and error when promptName changes", async () => {
    vi.mocked(promptsApi.render).mockResolvedValue({ rendered: { messages: [] }, status: 200 });
    const { result, rerender } = renderHook(
      ({ name }: { name: string }) => usePromptPreview(name, {}),
      {
        initialProps: { name: "greet_a" },
        wrapper: ({ children }) => <I18nProvider>{children}</I18nProvider>,
      },
    );

    await act(async () => {
      await result.current.run();
    });
    expect(result.current.hasRun).toBe(true);

    rerender({ name: "greet_b" });
    expect(result.current.result).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.hasRun).toBe(false);
  });

  it("flips isLoading while the request is in flight", async () => {
    let resolve: ((value: { rendered: { messages: never[] }; status: number }) => void) | undefined;
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
    resolve?.({ rendered: { messages: [] }, status: 200 });
    await act(async () => {
      await pending!;
    });
    expect(result.current.isLoading).toBe(false);
  });
});
