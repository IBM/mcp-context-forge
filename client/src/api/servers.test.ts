import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { serversApi, type OAuthCallbackResult } from "./servers";

describe("serversApi", () => {
  describe("triggerOAuthAuthorization", () => {
    let mockWindow: Window | null;
    let messageListeners: Array<(event: MessageEvent) => void> = [];
    let intervalIds: number[] = [];

    beforeEach(() => {
      // Mock window.open
      mockWindow = {
        closed: false,
        close: vi.fn(),
      } as unknown as Window;

      vi.spyOn(window, "open").mockReturnValue(mockWindow);

      // Mock window.addEventListener to capture message listeners
      const originalAddEventListener = window.addEventListener;
      vi.spyOn(window, "addEventListener").mockImplementation((event, listener) => {
        if (event === "message" && typeof listener === "function") {
          messageListeners.push(listener as (event: MessageEvent) => void);
        }
        return originalAddEventListener.call(window, event, listener);
      });

      // Mock window.removeEventListener
      vi.spyOn(window, "removeEventListener").mockImplementation((event, listener) => {
        if (event === "message") {
          messageListeners = messageListeners.filter((l) => l !== listener);
        }
      });

      // Mock setInterval to track interval IDs
      const originalSetInterval = global.setInterval;
      vi.spyOn(global, "setInterval").mockImplementation((...args: Parameters<typeof setInterval>) => {
        const id = originalSetInterval(...args);
        intervalIds.push(id as unknown as number);
        return id;
      });

      // Mock clearInterval
      const originalClearInterval = global.clearInterval;
      vi.spyOn(global, "clearInterval").mockImplementation((id) => {
        intervalIds = intervalIds.filter((i) => i !== (id as unknown as number));
        originalClearInterval(id);
      });
    });

    afterEach(() => {
      vi.restoreAllMocks();
      messageListeners = [];
      intervalIds.forEach((id) => clearInterval(id));
      intervalIds = [];
    });

    it("should open a popup window with correct URL and dimensions", () => {
      const gatewayId = "test-gateway-123";
      serversApi.triggerOAuthAuthorization(gatewayId);

      expect(window.open).toHaveBeenCalledWith(
        `/oauth/authorize/${gatewayId}?popup=true`,
        "oauth_authorization",
        expect.stringContaining("width=600"),
      );
      expect(window.open).toHaveBeenCalledWith(
        expect.any(String),
        expect.any(String),
        expect.stringContaining("height=700"),
      );
    });

    it("should reject if window.open returns null (popup blocked)", async () => {
      vi.spyOn(window, "open").mockReturnValue(null);

      await expect(serversApi.triggerOAuthAuthorization("test-gateway")).rejects.toThrow(
        "Failed to open OAuth authorization window. Please check your popup blocker settings.",
      );
    });

    it("should resolve when receiving a success message from the popup", async () => {
      const gatewayId = "test-gateway-123";
      const promise = serversApi.triggerOAuthAuthorization(gatewayId);

      // Simulate successful OAuth callback message
      const successMessage: OAuthCallbackResult = {
        type: "oauth_callback",
        status: "success",
        gatewayId: gatewayId,
        gatewayName: "Test Gateway",
      };

      // Trigger the message event
      setTimeout(() => {
        messageListeners.forEach((listener) => {
          listener(
            new MessageEvent("message", {
              data: successMessage,
              source: mockWindow,
            }),
          );
        });
      }, 10);

      const result = await promise;
      expect(result).toEqual(successMessage);
    });

    it("should reject when receiving an error message from the popup", async () => {
      const promise = serversApi.triggerOAuthAuthorization("test-gateway");

      // Simulate error OAuth callback message
      const errorMessage: OAuthCallbackResult = {
        type: "oauth_callback",
        status: "error",
        error: "access_denied",
        errorDescription: "User denied authorization",
      };

      setTimeout(() => {
        messageListeners.forEach((listener) => {
          listener(
            new MessageEvent("message", {
              data: errorMessage,
              source: mockWindow,
            }),
          );
        });
      }, 10);

      await expect(promise).rejects.toThrow("User denied authorization");
    });

    it("should reject when popup is closed without completing OAuth", async () => {
      const promise = serversApi.triggerOAuthAuthorization("test-gateway");

      // Simulate popup being closed
      setTimeout(() => {
        if (mockWindow) {
          (mockWindow as { closed: boolean }).closed = true;
        }
      }, 50);

      await expect(promise).rejects.toThrow("OAuth authorization was cancelled");
    });

    it("should ignore messages from wrong source", async () => {
      const promise = serversApi.triggerOAuthAuthorization("test-gateway");

      // Simulate message from different source
      const wrongSourceMessage: OAuthCallbackResult = {
        type: "oauth_callback",
        status: "success",
        gatewayId: "test-gateway",
      };

      setTimeout(() => {
        messageListeners.forEach((listener) => {
          listener(
            new MessageEvent("message", {
              data: wrongSourceMessage,
              source: window, // Wrong source
            }),
          );
        });
      }, 10);

      // Close popup to trigger cancellation
      setTimeout(() => {
        if (mockWindow) {
          (mockWindow as { closed: boolean }).closed = true;
        }
      }, 100);

      await expect(promise).rejects.toThrow("OAuth authorization was cancelled");
    });

    it("should ignore messages with wrong type", async () => {
      const promise = serversApi.triggerOAuthAuthorization("test-gateway");

      // Simulate message with wrong type
      setTimeout(() => {
        messageListeners.forEach((listener) => {
          listener(
            new MessageEvent("message", {
              data: { type: "other_message", status: "success" },
              source: mockWindow,
            }),
          );
        });
      }, 10);

      // Close popup to trigger cancellation
      setTimeout(() => {
        if (mockWindow) {
          (mockWindow as { closed: boolean }).closed = true;
        }
      }, 100);

      await expect(promise).rejects.toThrow("OAuth authorization was cancelled");
    });

    it("should cleanup event listeners and intervals on success", async () => {
      const promise = serversApi.triggerOAuthAuthorization("test-gateway");

      const successMessage: OAuthCallbackResult = {
        type: "oauth_callback",
        status: "success",
        gatewayId: "test-gateway",
      };

      setTimeout(() => {
        messageListeners.forEach((listener) => {
          listener(
            new MessageEvent("message", {
              data: successMessage,
              source: mockWindow,
            }),
          );
        });
      }, 10);

      await promise;

      expect(window.removeEventListener).toHaveBeenCalledWith("message", expect.any(Function));
      expect(intervalIds.length).toBe(0); // All intervals should be cleared
    });

    it("should cleanup event listeners and intervals on error", async () => {
      const promise = serversApi.triggerOAuthAuthorization("test-gateway");

      const errorMessage: OAuthCallbackResult = {
        type: "oauth_callback",
        status: "error",
        error: "server_error",
      };

      setTimeout(() => {
        messageListeners.forEach((listener) => {
          listener(
            new MessageEvent("message", {
              data: errorMessage,
              source: mockWindow,
            }),
          );
        });
      }, 10);

      await expect(promise).rejects.toThrow();

      expect(window.removeEventListener).toHaveBeenCalledWith("message", expect.any(Function));
      expect(intervalIds.length).toBe(0);
    });

    it("should validate gateway ID before opening popup", () => {
      expect(() => serversApi.triggerOAuthAuthorization("")).toThrow("Invalid server ID");
      expect(() => serversApi.triggerOAuthAuthorization("invalid/id")).toThrow("Invalid server ID format");
    });

    it("should handle multiple rapid messages (only first should settle)", async () => {
      const promise = serversApi.triggerOAuthAuthorization("test-gateway");

      const successMessage: OAuthCallbackResult = {
        type: "oauth_callback",
        status: "success",
        gatewayId: "test-gateway",
      };

      const errorMessage: OAuthCallbackResult = {
        type: "oauth_callback",
        status: "error",
        error: "test_error",
      };

      setTimeout(() => {
        // Send success message first
        messageListeners.forEach((listener) => {
          listener(
            new MessageEvent("message", {
              data: successMessage,
              source: mockWindow,
            }),
          );
        });

        // Try to send error message immediately after (should be ignored)
        messageListeners.forEach((listener) => {
          listener(
            new MessageEvent("message", {
              data: errorMessage,
              source: mockWindow,
            }),
          );
        });
      }, 10);

      const result = await promise;
      expect(result).toEqual(successMessage); // Should resolve with first message
    });
  });
});
