import { describe, expect, it, vi } from "vitest";
import {
  formatServerTimestamp,
  formatServerDateTime,
  truncateMiddle,
  getVirtualServerEndpoint,
  copyToClipboard,
  getTagDisplay,
  getVirtualServerComponentCounts,
  hasVirtualServerComponents,
  buildComponentItems,
} from "./utils";
import type { VirtualServer, VirtualServerTag } from "@/types/server";

describe("Gateways Utils", () => {
  describe("formatServerTimestamp", () => {
    it("returns emptyLabel when value is empty", () => {
      expect(formatServerTimestamp()).toBe("Not synced yet");
      expect(formatServerTimestamp("", "Empty")).toBe("Empty");
    });

    it("returns original value if date parsing fails", () => {
      expect(formatServerTimestamp("invalid-date")).toBe("invalid-date");
    });

    it("returns locale string for valid dates", () => {
      const dateString = "2023-01-01T12:00:00.000Z";
      expect(formatServerTimestamp(dateString)).toBe(new Date(dateString).toLocaleString());
    });
  });

  describe("formatServerDateTime", () => {
    it("delegates to formatServerTimestamp", () => {
      expect(formatServerDateTime()).toBe("Not synced yet");
    });
  });

  describe("truncateMiddle", () => {
    it("returns original value if shorter than maxLength", () => {
      expect(truncateMiddle("short", 10)).toBe("short");
    });

    it("truncates middle if longer than maxLength", () => {
      const longStr = "123456789012345678901234567890"; // pragma: allowlist secret
      const result = truncateMiddle(longStr, 24);
      expect(result.length).toBeLessThan(longStr.length);
      expect(result).toContain("...");
    });
  });

  describe("getVirtualServerEndpoint", () => {
    it("returns relative path if window or origin is not available", () => {
      // Mock window.location to simulate missing origin
      const originalLocation = window.location;
      // @ts-expect-error - invalid url - testing missing window.location
      delete window.location;

      expect(getVirtualServerEndpoint("test-id")).toBe("/servers/test-id/mcp");

      // Restore window.location
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      window.location = originalLocation as any;
    });

    it("returns absolute URL if window.location.origin is available", () => {
      expect(getVirtualServerEndpoint("test-id")).toBe("http://localhost:3000/servers/test-id/mcp");
    });
  });

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
      // @ts-expect-error - invalid url - testing missing clipboard
      delete navigator.clipboard;

      expect(() => copyToClipboard("test")).not.toThrow();

      // @ts-expect-error - invalid url - restoring clipboard
      navigator.clipboard = originalClipboard;
    });
  });

  describe("getTagDisplay", () => {
    it("handles string tags", () => {
      expect(getTagDisplay("my-tag", 0)).toEqual({ key: "my-tag-0", label: "my-tag" });
    });

    it("handles object tags with label", () => {
      expect(getTagDisplay({ label: "tag-label" } as unknown as VirtualServerTag, 1)).toEqual({
        key: "tag-label-1",
        label: "tag-label",
      });
    });

    it("handles object tags with various fallbacks", () => {
      expect(getTagDisplay({ name: "tag-name" } as unknown as VirtualServerTag, 2)).toEqual({
        key: "tag-name-2",
        label: "tag-name",
      });
      expect(getTagDisplay({ value: "tag-value" } as unknown as VirtualServerTag, 3)).toEqual({
        key: "tag-value-3",
        label: "tag-value",
      });
      expect(getTagDisplay({ id: "tag-id" } as unknown as VirtualServerTag, 4)).toEqual({
        key: "tag-id-4",
        label: "tag-id",
      });
      expect(getTagDisplay({} as unknown as VirtualServerTag, 5, "Fallback")).toEqual({
        key: "Fallback-5",
        label: "Fallback",
      });
    });
  });

  describe("Virtual Server Components", () => {
    const serverWithTools: VirtualServer = {
      id: "1",
      name: "test",
      target_type: "mcp",
      associatedTools: ["tool1", "tool2"],
      associatedToolIds: ["id1", "id2"],
      associatedResources: ["res1"],
      associatedPrompts: ["prompt1"],
    } as unknown as VirtualServer;

    const serverWithoutTools: VirtualServer = {
      id: "2",
      name: "empty",
      target_type: "mcp",
    } as unknown as VirtualServer;

    it("getVirtualServerComponentCounts", () => {
      expect(getVirtualServerComponentCounts(serverWithTools)).toEqual({
        toolCount: 2,
        resourceCount: 1,
        promptCount: 1,
        total: 4,
      });

      expect(getVirtualServerComponentCounts(serverWithoutTools)).toEqual({
        toolCount: 0,
        resourceCount: 0,
        promptCount: 0,
        total: 0,
      });

      // Test fallback to associatedTools length
      const serverToolsOnly = {
        id: "3",
        name: "test",
        target_type: "mcp",
        associatedTools: ["tool1", "tool2"],
      } as unknown as VirtualServer;
      expect(getVirtualServerComponentCounts(serverToolsOnly).toolCount).toBe(2);
    });

    it("hasVirtualServerComponents", () => {
      expect(hasVirtualServerComponents(serverWithTools)).toBe(true);
      expect(hasVirtualServerComponents(serverWithoutTools)).toBe(false);
    });

    it("buildComponentItems", () => {
      const items = buildComponentItems(serverWithTools);
      expect(items).toHaveLength(4);
      expect(items[0]).toEqual({
        id: "tool-id1-0",
        name: "tool1",
        secondary: "id1",
        type: "tools",
      });
      expect(items[2]).toEqual({ id: "resource-res1-0", name: "res1", type: "resources" });
      expect(items[3]).toEqual({ id: "prompt-prompt1-0", name: "prompt1", type: "prompts" });

      const emptyItems = buildComponentItems(serverWithoutTools);
      expect(emptyItems).toHaveLength(0);

      // Test when toolIds is empty but toolNames is populated
      const serverNamesOnly = {
        associatedTools: ["toolA"],
      } as unknown as VirtualServer;
      const itemsNames = buildComponentItems(serverNamesOnly);
      expect(itemsNames[0]).toEqual({
        id: "tool-toolA-0",
        name: "toolA",
        secondary: undefined,
        type: "tools",
      });
    });
  });
});
