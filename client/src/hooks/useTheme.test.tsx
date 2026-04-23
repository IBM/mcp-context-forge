import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { ThemeProvider, useTheme } from "./useTheme";

describe("useTheme", () => {
  beforeEach(() => {
    // Clear localStorage manually
    Object.keys(localStorage).forEach((key) => localStorage.removeItem(key));
    document.documentElement.className = "";
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("should throw error when used outside ThemeProvider", () => {
    // Suppress console.error for this test
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => {
      renderHook(() => useTheme());
    }).toThrow("useTheme must be used within a ThemeProvider");

    consoleError.mockRestore();
  });

  it("should initialize with system theme by default", () => {
    // Mock matchMedia to return a valid object
    const mockMatchMedia = vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    vi.stubGlobal("matchMedia", mockMatchMedia);

    const { result } = renderHook(() => useTheme(), {
      wrapper: ThemeProvider,
    });

    expect(result.current.theme).toBe("system");
    expect(["light", "dark"]).toContain(result.current.resolvedTheme);
  });

  it("should load theme from localStorage if available", () => {
    localStorage.setItem("theme-preference", "dark");

    const { result } = renderHook(() => useTheme(), {
      wrapper: ThemeProvider,
    });

    expect(result.current.theme).toBe("dark");
    expect(result.current.resolvedTheme).toBe("dark");
  });

  it("should apply dark class to document when theme is dark", () => {
    const { result } = renderHook(() => useTheme(), {
      wrapper: ThemeProvider,
    });

    act(() => {
      result.current.setTheme("dark");
    });

    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.classList.contains("light")).toBe(false);
  });

  it("should apply light class to document when theme is light", () => {
    const { result } = renderHook(() => useTheme(), {
      wrapper: ThemeProvider,
    });

    act(() => {
      result.current.setTheme("light");
    });

    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("should persist theme to localStorage when changed", () => {
    const { result } = renderHook(() => useTheme(), {
      wrapper: ThemeProvider,
    });

    act(() => {
      result.current.setTheme("dark");
    });

    expect(localStorage.getItem("theme-preference")).toBe("dark");

    act(() => {
      result.current.setTheme("light");
    });

    expect(localStorage.getItem("theme-preference")).toBe("light");
  });

  it("should handle system theme based on media query", () => {
    // Mock matchMedia to return dark mode
    const mockMatchMedia = vi.fn().mockImplementation((query) => ({
      matches: query === "(prefers-color-scheme: dark)",
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    vi.stubGlobal("matchMedia", mockMatchMedia);

    const { result } = renderHook(() => useTheme(), {
      wrapper: ThemeProvider,
    });

    act(() => {
      result.current.setTheme("system");
    });

    expect(result.current.theme).toBe("system");
    expect(result.current.resolvedTheme).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it.skip("should update resolved theme when system preference changes", async () => {
    let mediaQueryListener: ((e: MediaQueryListEvent) => void) | null = null;

    const mockMatchMedia = vi.fn().mockImplementation((query) => ({
      matches: false, // Start with light mode
      media: query,
      addEventListener: vi.fn((event, listener) => {
        if (event === "change") {
          mediaQueryListener = listener;
        }
      }),
      removeEventListener: vi.fn(),
    }));
    vi.stubGlobal("matchMedia", mockMatchMedia);

    const { result } = renderHook(() => useTheme(), {
      wrapper: ThemeProvider,
    });

    act(() => {
      result.current.setTheme("system");
    });

    expect(result.current.resolvedTheme).toBe("light");

    // Simulate system preference change to dark
    if (mediaQueryListener) {
      act(() => {
        mediaQueryListener!({ matches: true } as MediaQueryListEvent);
      });

      // Wait for state update
      await waitFor(
        () => {
          expect(result.current.resolvedTheme).toBe("dark");
        },
        { timeout: 2000 },
      );
    }
  });

  it("should handle localStorage unavailability gracefully", () => {
    // Mock matchMedia
    const mockMatchMedia = vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    vi.stubGlobal("matchMedia", mockMatchMedia);

    const setItemSpy = vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("localStorage unavailable");
    });

    const { result } = renderHook(() => useTheme(), {
      wrapper: ThemeProvider,
    });

    // Should not throw error
    expect(() => {
      act(() => {
        result.current.setTheme("dark");
      });
    }).not.toThrow();

    expect(result.current.theme).toBe("dark");
    setItemSpy.mockRestore();
  });

  it("should cycle through themes correctly", () => {
    // Mock matchMedia
    const mockMatchMedia = vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    vi.stubGlobal("matchMedia", mockMatchMedia);

    const { result } = renderHook(() => useTheme(), {
      wrapper: ThemeProvider,
    });

    // Start with system
    expect(result.current.theme).toBe("system");

    // Change to light
    act(() => {
      result.current.setTheme("light");
    });
    expect(result.current.theme).toBe("light");

    // Change to dark
    act(() => {
      result.current.setTheme("dark");
    });
    expect(result.current.theme).toBe("dark");

    // Change back to system
    act(() => {
      result.current.setTheme("system");
    });
    expect(result.current.theme).toBe("system");
  });
});
