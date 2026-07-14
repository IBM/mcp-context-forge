import { describe, expect, it, vi } from "vitest";
import { copyToClipboard } from "./clipboard";

describe("copyToClipboard", () => {
  it("calls navigator.clipboard.writeText if available", () => {
    const writeTextMock = vi.fn();
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    copyToClipboard("test-text");
    expect(writeTextMock).toHaveBeenCalledWith("test-text");
  });

  it("does not throw if clipboard is undefined", () => {
    const originalClipboard = navigator.clipboard;
    // @ts-expect-error - testing missing clipboard
    delete navigator.clipboard;

    expect(() => copyToClipboard("test")).not.toThrow();

    // @ts-expect-error - restoring clipboard
    navigator.clipboard = originalClipboard;
  });
});
