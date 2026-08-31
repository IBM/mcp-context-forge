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

    expect(promptsApi.render).toHaveBeenCalledWith(
      "greet",
      { user: "Alice" },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
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

  it("unwraps ApiError.body.message when body.detail is absent", async () => {
    const { toast } = await import("sonner");
    vi.mocked(promptsApi.render).mockRejectedValue(
      new ApiError(
        422,
        {
          message:
            "Failed to fetch prompt 'web_search_help' from gateway: unhandled errors in a TaskGroup (1 sub-exception)",
        },
        "HTTP 422",
      ),
    );
    const { result } = setup();

    await act(async () => {
      await result.current.run();
    });

    expect(result.current.error?.message).toBe(
      "Failed to fetch prompt 'web_search_help' from gateway: unhandled errors in a TaskGroup (1 sub-exception)",
    );
    expect(result.current.error?.status).toBe(422);
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

  it("aborts an in-flight preview when the hook unmounts and drops the late resolution", async () => {
    let resolve: ((v: { rendered: { messages: never[] }; status: number }) => void) | undefined;
    let capturedSignal: AbortSignal | undefined;
    vi.mocked(promptsApi.render).mockImplementation((_name, _args, opts) => {
      capturedSignal = opts?.signal;
      return new Promise((r) => {
        resolve = r;
      });
    });
    const { toast } = await import("sonner");
    const { result, unmount } = setup();

    act(() => {
      void result.current.run();
    });
    await waitFor(() => expect(result.current.isLoading).toBe(true));
    expect(capturedSignal?.aborted).toBe(false);

    unmount();
    expect(capturedSignal?.aborted).toBe(true);

    // Late resolution after unmount must not toast or otherwise surface.
    resolve?.({ rendered: { messages: [] }, status: 200 });
    await new Promise((r) => setTimeout(r, 0));
    expect(toast.error).not.toHaveBeenCalled();
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

  it("reset() clears a completed run so hasRun returns to false", async () => {
    vi.mocked(promptsApi.render).mockResolvedValue({ rendered: { messages: [] }, status: 200 });
    const { result } = setup();

    await act(async () => {
      await result.current.run();
    });
    expect(result.current.hasRun).toBe(true);

    act(() => {
      result.current.reset();
    });
    expect(result.current.result).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.hasRun).toBe(false);
    expect(result.current.isLoading).toBe(false);
  });

  it("reset() clears a captured error", async () => {
    vi.mocked(promptsApi.render).mockRejectedValue(new Error("boom"));
    const { result } = setup();

    await act(async () => {
      await result.current.run();
    });
    expect(result.current.error).not.toBeNull();

    act(() => {
      result.current.reset();
    });
    expect(result.current.error).toBeNull();
    expect(result.current.hasRun).toBe(false);
  });

  it("reset() aborts an in-flight request and clears isLoading", async () => {
    let capturedSignal: AbortSignal | undefined;
    let resolve: ((v: { rendered: { messages: never[] }; status: number }) => void) | undefined;
    vi.mocked(promptsApi.render).mockImplementation((_name, _args, opts) => {
      capturedSignal = opts?.signal;
      return new Promise((r) => {
        resolve = r;
      });
    });
    const { result } = setup();

    act(() => {
      void result.current.run();
    });
    await waitFor(() => expect(result.current.isLoading).toBe(true));
    expect(capturedSignal?.aborted).toBe(false);

    act(() => {
      result.current.reset();
    });
    expect(capturedSignal?.aborted).toBe(true);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.result).toBeNull();
    expect(result.current.error).toBeNull();

    // Late resolution after reset must not repopulate state.
    resolve?.({ rendered: { messages: [] }, status: 200 });
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.result).toBeNull();
    expect(result.current.hasRun).toBe(false);
  });
});
