import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useIsMobile } from "./use-mobile";

describe("useIsMobile", () => {
  let addEventListenerMock: any;
  let removeEventListenerMock: any;
  let changeHandler: any;

  beforeEach(() => {
    addEventListenerMock = vi.fn((event, handler) => {
      if (event === "change") {
        changeHandler = handler;
      }
    });
    removeEventListenerMock = vi.fn();

    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockImplementation((query) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(), // deprecated
        removeListener: vi.fn(), // deprecated
        addEventListener: addEventListenerMock,
        removeEventListener: removeEventListenerMock,
        dispatchEvent: vi.fn(),
      })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    changeHandler = null;
  });

  it("should initialize based on innerWidth", () => {
    vi.stubGlobal("innerWidth", 500); // Mobile
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);

    vi.stubGlobal("innerWidth", 1024); // Desktop
    const { result: resultDesktop } = renderHook(() => useIsMobile());
    expect(resultDesktop.current).toBe(false);
  });

  it("should update when resize event triggers matchMedia change", () => {
    vi.stubGlobal("innerWidth", 1024);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);

    act(() => {
      vi.stubGlobal("innerWidth", 500);
      if (changeHandler) changeHandler();
    });

    expect(result.current).toBe(true);
  });

  it("should clean up event listener on unmount", () => {
    const { unmount } = renderHook(() => useIsMobile());
    expect(addEventListenerMock).toHaveBeenCalled();
    unmount();
    expect(removeEventListenerMock).toHaveBeenCalled();
  });
});
