import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { I18nProvider } from "@/i18n";
import { AuthProvider } from "@/auth/AuthContext";
import { TeamForm } from "./TeamForm";

function renderForm(props: Partial<React.ComponentProps<typeof TeamForm>> = {}) {
  return render(
    <AuthProvider>
      <I18nProvider>
        <TeamForm isOpen={true} onToggle={vi.fn()} onSuccess={vi.fn()} {...props} />
      </I18nProvider>
    </AuthProvider>,
  );
}

describe("TeamForm", () => {
  beforeEach(() => {
    server.resetHandlers();
    server.use(
      http.get("*/auth/email/admin/users", () => HttpResponse.json({ users: [] })),
      http.post("*/teams", () =>
        HttpResponse.json({ id: "team-1", name: "Engineering" }, { status: 201 }),
      ),
    );
  });

  describe("Rendering", () => {
    it("renders the heading, name field, and action buttons", () => {
      renderForm();
      expect(screen.getByRole("heading", { name: /create team/i })).toBeInTheDocument();
      expect(screen.getByPlaceholderText(/add team name/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^create team$/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^cancel$/i })).toBeInTheDocument();
    });

    it("gives the description field an accessible name without a visible label", () => {
      renderForm();
      // aria-label provides the accessible name; no visible "Description" text is rendered.
      expect(screen.getByRole("textbox", { name: /description/i })).toBeInTheDocument();
      expect(screen.queryByText("Description")).not.toBeInTheDocument();
    });

    it("returns null when isOpen is false", () => {
      const { container } = renderForm({ isOpen: false });
      expect(container.firstChild).toBeNull();
    });
  });

  describe("Cancel", () => {
    it("calls onToggle when Cancel is clicked", async () => {
      const onToggle = vi.fn();
      const user = userEvent.setup();
      renderForm({ onToggle });

      await user.click(screen.getByRole("button", { name: /^cancel$/i }));
      expect(onToggle).toHaveBeenCalledOnce();
    });
  });

  describe("Submit", () => {
    it("disables submit until a name is entered", async () => {
      const user = userEvent.setup();
      renderForm();

      const submit = screen.getByRole("button", { name: /^create team$/i });
      expect(submit).toBeDisabled();

      await user.type(screen.getByPlaceholderText(/add team name/i), "Engineering");
      expect(submit).toBeEnabled();
    });

    it("creates the team and calls onSuccess then onToggle", async () => {
      const onSuccess = vi.fn();
      const onToggle = vi.fn();
      const user = userEvent.setup();
      renderForm({ onSuccess, onToggle });

      await user.type(screen.getByPlaceholderText(/add team name/i), "Engineering");
      await user.click(screen.getByRole("button", { name: /^create team$/i }));

      await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
      expect(onToggle).toHaveBeenCalledOnce();
    });

    it("shows an error and does not close when creation fails", async () => {
      server.use(
        http.post("*/teams", () =>
          HttpResponse.json({ detail: "Team already exists" }, { status: 409 }),
        ),
      );
      const onSuccess = vi.fn();
      const user = userEvent.setup();
      renderForm({ onSuccess });

      await user.type(screen.getByPlaceholderText(/add team name/i), "Engineering");
      await user.click(screen.getByRole("button", { name: /^create team$/i }));

      await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/already exists/i));
      expect(onSuccess).not.toHaveBeenCalled();
    });
  });

  describe("Field interactions", () => {
    it("edits the description and toggles visibility", async () => {
      const user = userEvent.setup();
      renderForm();

      const description = screen.getByRole("textbox", { name: /description/i });
      await user.type(description, "The best team");
      expect(description).toHaveValue("The best team");

      // Private is the default and shows the lock hint.
      expect(screen.getByRole("radio", { name: /private/i })).toBeChecked();
      const publicRadio = screen.getByRole("radio", { name: /public/i });
      await user.click(publicRadio);
      expect(publicRadio).toBeChecked();
    });
  });

  describe("Members", () => {
    it("selects a member from the directory and changes their role", async () => {
      server.use(
        http.get("*/auth/email/admin/users", () =>
          HttpResponse.json({ users: [{ email: "alice@example.com", full_name: "Alice" }] }),
        ),
      );
      const user = userEvent.setup();
      renderForm();

      // Pick a member via the combobox (fires the member-email change handler).
      const memberInput = screen.getByPlaceholderText(/name or email/i);
      await user.click(memberInput);
      await user.keyboard("alice");
      await user.click(await screen.findByRole("option", { name: /alice/i }));

      await waitFor(() => {
        expect(memberInput).toHaveValue("Alice (alice@example.com)");
      });

      // Change the role from owner -> member (fires the role change handler).
      // The member row's role Select is the first select-trigger in the form.
      const roleTrigger = document.querySelectorAll<HTMLElement>('[data-slot="select-trigger"]')[0];
      expect(roleTrigger).toHaveTextContent("owner");

      await user.click(roleTrigger);
      const memberOption = await screen.findByRole("option", { name: /^member$/i });
      await user.click(memberOption);

      await waitFor(() => {
        expect(roleTrigger).toHaveTextContent("member");
      });
    });

    it("adds and removes member rows", async () => {
      const user = userEvent.setup();
      renderForm();

      // Starts with one owner row -> one Remove button.
      expect(screen.getAllByRole("button", { name: /remove/i })).toHaveLength(1);

      await user.click(screen.getByRole("button", { name: /add team member/i }));
      expect(screen.getAllByRole("button", { name: /remove/i })).toHaveLength(2);

      await user.click(screen.getAllByRole("button", { name: /remove/i })[0]);
      expect(screen.getAllByRole("button", { name: /remove/i })).toHaveLength(1);
    });
  });
});
