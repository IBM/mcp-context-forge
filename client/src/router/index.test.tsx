import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthGuard, RouterProvider, Route, Redirect, useRouter } from ".";
import { I18nProvider } from "../i18n";
import type { ReactNode } from "react";

vi.mock("../auth/AuthContext", () => ({
  useAuthContext: vi.fn(),
}));

import { useAuthContext } from "../auth/AuthContext";

const mockUseAuthContext = useAuthContext as ReturnType<typeof vi.fn>;

function renderAuthGuard(
  path: string,
  authState: { isAuthenticated: boolean; isLoading: boolean } = {
    isAuthenticated: false,
    isLoading: false,
  },
) {
  mockUseAuthContext.mockReturnValue(authState);
  window.history.pushState({}, "", path);
  return render(
    <I18nProvider>
      <RouterProvider>
        <AuthGuard>
          <div>protected content</div>
        </AuthGuard>
      </RouterProvider>
    </I18nProvider>,
  );
}

function renderWithRouter(ui: ReactNode, path: string = "/app/test") {
  window.history.pushState({}, "", path);
  return render(
    <I18nProvider>
      <RouterProvider>{ui}</RouterProvider>
    </I18nProvider>,
  );
}

describe("AuthGuard", () => {
  beforeEach(() => {
    mockUseAuthContext.mockClear();
  });

  describe("public paths — AuthGuard returns null, not children", () => {
    // Regression: AuthGuard previously returned <>{children}</> on public paths.
    // That rendered AppShell (with TeamSwitcher) on /app/login, causing TeamSwitcher
    // to call /teams → 401 → window.location.replace("/app/login") → reload → repeat.
    // The fix is: if (isPublic) return null.
    it("does not render children on /app/login when unauthenticated", () => {
      renderAuthGuard("/app/login", { isAuthenticated: false, isLoading: false });
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });

    it("does not render children on /app/login even when authenticated", () => {
      renderAuthGuard("/app/login", { isAuthenticated: true, isLoading: false });
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });

    it("does not render children on /app/forgot-password", () => {
      renderAuthGuard("/app/forgot-password", { isAuthenticated: false, isLoading: false });
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });

    it("does not render children on /app/reset-password/:token prefix", () => {
      renderAuthGuard("/app/reset-password/abc123", { isAuthenticated: false, isLoading: false });
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });

    it("does not render children on /app/reset-password/ with any token", () => {
      renderAuthGuard("/app/reset-password/xyz789", { isAuthenticated: false, isLoading: false });
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });
  });

  describe("protected paths", () => {
    it("renders children when authenticated", () => {
      renderAuthGuard("/app/", { isAuthenticated: true, isLoading: false });
      expect(screen.getByText("protected content")).toBeInTheDocument();
    });

    it("renders nothing while auth is loading", () => {
      renderAuthGuard("/app/", { isAuthenticated: false, isLoading: true });
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });

    it("shows loading indicator while auth is loading", () => {
      renderAuthGuard("/app/", { isAuthenticated: false, isLoading: true });
      expect(screen.getByText("Context Forge")).toBeInTheDocument();
    });

    it("renders nothing when unauthenticated", () => {
      renderAuthGuard("/app/gateways", { isAuthenticated: false, isLoading: false });
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });

    it("renders children for authenticated /app/servers path", () => {
      renderAuthGuard("/app/servers", { isAuthenticated: true, isLoading: false });
      expect(screen.getByText("protected content")).toBeInTheDocument();
    });

    it("renders children for authenticated /app/tools path", () => {
      renderAuthGuard("/app/tools", { isAuthenticated: true, isLoading: false });
      expect(screen.getByText("protected content")).toBeInTheDocument();
    });

    it("renders children for authenticated /app/users path", () => {
      renderAuthGuard("/app/users", { isAuthenticated: true, isLoading: false });
      expect(screen.getByText("protected content")).toBeInTheDocument();
    });
  });

  describe("custom public paths", () => {
    it("accepts custom publicPaths", () => {
      mockUseAuthContext.mockReturnValue({ isAuthenticated: false, isLoading: false });
      window.history.pushState({}, "", "/app/custom-public");

      render(
        <I18nProvider>
          <RouterProvider>
            <AuthGuard publicPaths={["/app/custom-public"]}>
              <div>protected content</div>
            </AuthGuard>
          </RouterProvider>
        </I18nProvider>,
      );

      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });

    it("accepts custom publicPrefixes", () => {
      mockUseAuthContext.mockReturnValue({ isAuthenticated: false, isLoading: false });
      window.history.pushState({}, "", "/app/custom/path");

      render(
        <I18nProvider>
          <RouterProvider>
            <AuthGuard publicPrefixes={["/app/custom/"]}>
              <div>protected content</div>
            </AuthGuard>
          </RouterProvider>
        </I18nProvider>,
      );

      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });
  });
});

describe("RouterProvider and useRouter", () => {
  it("provides router context to children", () => {
    const TestComponent = () => {
      const router = useRouter();
      return <div>path: {router.path}</div>;
    };

    renderWithRouter(<TestComponent />, "/app/test");

    expect(screen.getByText(/path: \/app\/test/)).toBeInTheDocument();
  });

  it("throws error when useRouter is used outside RouterProvider", () => {
    const TestComponent = () => {
      const router = useRouter();
      return <div>{router.path}</div>;
    };

    expect(() => {
      render(<TestComponent />);
    }).toThrow("useRouter must be used inside <RouterProvider>");
  });

  it("captures query string in path", () => {
    const TestComponent = () => {
      const router = useRouter();
      return <div>path: {router.path}</div>;
    };

    renderWithRouter(<TestComponent />, "/app/test?foo=bar&baz=qux");

    expect(screen.getByText(/path: \/app\/test\?foo=bar&baz=qux/)).toBeInTheDocument();
  });

  it("updates path on popstate", async () => {
    const TestComponent = () => {
      const router = useRouter();
      return <div>path: {router.path}</div>;
    };

    renderWithRouter(<TestComponent />, "/app/test");
    expect(screen.getByText(/path: \/app\/test/)).toBeInTheDocument();

    act(() => {
      window.history.pushState({}, "", "/app/other");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    await waitFor(() => {
      expect(screen.getByText(/path: \/app\/other/)).toBeInTheDocument();
    });
  });
});

describe("Route component", () => {
  it("renders component when pattern matches", () => {
    const TestComponent = () => (
      <Route path="/app/test" component={() => <div>route matched</div>} />
    );

    renderWithRouter(<TestComponent />, "/app/test");

    expect(screen.getByText("route matched")).toBeInTheDocument();
  });

  it("does not render component when pattern does not match", () => {
    const TestComponent = () => (
      <Route path="/app/test" component={() => <div>route matched</div>} />
    );

    renderWithRouter(<TestComponent />, "/app/other");

    expect(screen.queryByText("route matched")).not.toBeInTheDocument();
  });

  it("ignores query string when matching", () => {
    const TestComponent = () => (
      <Route path="/app/test" component={() => <div>route matched</div>} />
    );

    renderWithRouter(<TestComponent />, "/app/test?foo=bar");

    expect(screen.getByText("route matched")).toBeInTheDocument();
  });

  it("passes route params to component", () => {
    const TestComponent = () => (
      <Route path="/app/users/:id" component={({ id }) => <div>user id: {id}</div>} />
    );

    renderWithRouter(<TestComponent />, "/app/users/123");

    expect(screen.getByText("user id: 123")).toBeInTheDocument();
  });

  it("decodes URL-encoded params", () => {
    const TestComponent = () => (
      <Route path="/app/search/:query" component={({ query }) => <div>query: {query}</div>} />
    );

    renderWithRouter(<TestComponent />, "/app/search/hello%20world");

    expect(screen.getByText("query: hello world")).toBeInTheDocument();
  });

  it("does not match when params are malformed", () => {
    const TestComponent = () => (
      <Route path="/app/search/:query" component={({ query }) => <div>query: {query}</div>} />
    );

    renderWithRouter(<TestComponent />, "/app/search/%");

    expect(screen.queryByText(/query:/)).not.toBeInTheDocument();
  });

  it("matches multiple params", () => {
    const TestComponent = () => (
      <Route
        path="/app/users/:userId/posts/:postId"
        component={({ userId, postId }) => (
          <div>
            user: {userId}, post: {postId}
          </div>
        )}
      />
    );

    renderWithRouter(<TestComponent />, "/app/users/456/posts/789");

    expect(screen.getByText("user: 456, post: 789")).toBeInTheDocument();
  });
});

describe("Redirect component", () => {
  it("navigates to valid destination on mount", async () => {
    const TestComponent = () => (
      <>
        <Redirect to="/app/redirected" />
        <div>original path</div>
      </>
    );

    renderWithRouter(<TestComponent />, "/app/test");

    await waitFor(() => {
      expect(window.location.pathname).toBe("/app/redirected");
    });
  });

  it("does not redirect to invalid destination", () => {
    const TestComponent = () => (
      <>
        <Redirect to="https://evil.com" />
        <div>original path</div>
      </>
    );

    renderWithRouter(<TestComponent />, "/app/test");

    expect(window.location.pathname).not.toBe("https://evil.com");
  });
});

describe("Destination validation", () => {
  it("accepts /app paths", async () => {
    const TestComponent = () => {
      const router = useRouter();
      return <button onClick={() => router.navigate("/app/test")}>navigate</button>;
    };

    renderWithRouter(<TestComponent />, "/app");
    const user = userEvent.setup();

    const button = screen.getByRole("button", { name: "navigate" });
    await user.click(button);

    await waitFor(() => {
      expect(window.location.pathname).toBe("/app/test");
    });
  });

  it("rejects paths with ..", () => {
    const TestComponent = () => {
      const router = useRouter();
      router.navigate("/app/../admin");
      return <div>path: {router.path}</div>;
    };

    renderWithRouter(<TestComponent />, "/app");

    expect(window.location.pathname).not.toContain("admin");
  });

  it("rejects protocol URLs", () => {
    const TestComponent = () => {
      const router = useRouter();
      router.navigate("https://example.com");
      return <div>path: {router.path}</div>;
    };

    renderWithRouter(<TestComponent />, "/app");

    expect(window.location.pathname).not.toContain("example.com");
  });

  it("rejects protocol-relative URLs", () => {
    const TestComponent = () => {
      const router = useRouter();
      router.navigate("//example.com");
      return <div>path: {router.path}</div>;
    };

    renderWithRouter(<TestComponent />, "/app");

    expect(window.location.pathname).not.toContain("example.com");
  });

  it("rejects non-/app paths", () => {
    const TestComponent = () => {
      const router = useRouter();
      router.navigate("/admin");
      return <div>path: {router.path}</div>;
    };

    renderWithRouter(<TestComponent />, "/app");

    expect(window.location.pathname).not.toBe("/admin");
  });

  it("accepts /app with query string", async () => {
    const TestComponent = () => {
      const router = useRouter();
      return <button onClick={() => router.navigate("/app/test?foo=bar")}>navigate</button>;
    };

    renderWithRouter(<TestComponent />, "/app");
    const user = userEvent.setup();

    const button = screen.getByRole("button", { name: "navigate" });
    await user.click(button);

    await waitFor(() => {
      expect(window.location.search).toContain("foo=bar");
    });
  });

  it("accepts exactly /app", async () => {
    const TestComponent = () => {
      const router = useRouter();
      return <button onClick={() => router.navigate("/app")}>navigate</button>;
    };

    renderWithRouter(<TestComponent />, "/app/test");
    const user = userEvent.setup();

    const button = screen.getByRole("button", { name: "navigate" });
    await user.click(button);

    await waitFor(() => {
      expect(window.location.pathname).toBe("/app");
    });
  });

  it("accepts /app/", async () => {
    const TestComponent = () => {
      const router = useRouter();
      return <button onClick={() => router.navigate("/app/")}>navigate</button>;
    };

    renderWithRouter(<TestComponent />, "/app/test");
    const user = userEvent.setup();

    const button = screen.getByRole("button", { name: "navigate" });
    await user.click(button);

    await waitFor(() => {
      expect(window.location.pathname).toBe("/app/");
    });
  });

  it("rejects non-string destinations", () => {
    const TestComponent = () => {
      const router = useRouter();
      router.navigate(undefined as unknown as string);
      return <div>path: {router.path}</div>;
    };

    renderWithRouter(<TestComponent />, "/app");

    expect(window.location.pathname).toBe("/app");
  });
});
