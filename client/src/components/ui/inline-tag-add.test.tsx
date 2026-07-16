import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { InlineTagAdd } from "./inline-tag-add";

const PLACEHOLDER = "Add tags separated with commas";

function renderControl(overrides: Partial<React.ComponentProps<typeof InlineTagAdd>> = {}) {
  const onAdd = overrides.onAdd ?? vi.fn().mockResolvedValue(undefined);
  // Labels rely on the component's built-in defaults ("add" trigger, "Add tags"
  // aria label, comma-separated placeholder, "Add" / "Cancel" buttons).
  render(
    <InlineTagAdd
      label="Tags"
      existingTags={overrides.existingTags ?? ["existing"]}
      onAdd={onAdd}
      {...overrides}
    />,
  );
  return { onAdd };
}

describe("InlineTagAdd", () => {
  it("renders only the trigger button initially", () => {
    renderControl();

    expect(screen.getByRole("button", { name: "Add tags" })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(PLACEHOLDER)).not.toBeInTheDocument();
  });

  it("shows the input and Cancel/Add buttons after clicking the trigger", async () => {
    const user = userEvent.setup();
    renderControl();

    await user.click(screen.getByRole("button", { name: "Add tags" }));

    expect(screen.getByPlaceholderText(PLACEHOLDER)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
    // Trigger is gone while editing.
    expect(screen.queryByRole("button", { name: "add" })).not.toBeInTheDocument();
  });

  it("Cancel collapses back to the trigger without calling onAdd", async () => {
    const user = userEvent.setup();
    const { onAdd } = renderControl();

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    await user.type(screen.getByPlaceholderText(PLACEHOLDER), "draft");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onAdd).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Add tags" })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(PLACEHOLDER)).not.toBeInTheDocument();
  });

  it("Add persists the trimmed tag and collapses on success", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn().mockResolvedValue(undefined);
    renderControl({ onAdd });

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    await user.type(screen.getByPlaceholderText(PLACEHOLDER), "  analytics  ");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(onAdd).toHaveBeenCalledWith(["analytics"]);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add tags" })).toBeInTheDocument(),
    );
  });

  it("splits a comma-separated list into trimmed, de-duplicated tags", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn().mockResolvedValue(undefined);
    renderControl({ onAdd, existingTags: ["existing"] });

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    // Blanks, an existing tag, and a repeat within the input are all filtered out.
    await user.type(
      screen.getByPlaceholderText(PLACEHOLDER),
      "  alpha , beta,, Existing, alpha ,gamma",
    );
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(onAdd).toHaveBeenCalledWith(["alpha", "beta", "gamma"]);
  });

  it("keeps the editor open when onAdd rejects so the user can retry", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn().mockRejectedValue(new Error("boom"));
    renderControl({ onAdd });

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    await user.type(screen.getByPlaceholderText(PLACEHOLDER), "ml");
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(onAdd).toHaveBeenCalled());
    // Still editing, value preserved.
    expect(screen.getByPlaceholderText(PLACEHOLDER)).toHaveValue("ml");
  });

  it("skips input that only repeats existing tags without calling onAdd", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn().mockResolvedValue(undefined);
    renderControl({ onAdd, existingTags: ["Analytics"] });

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    await user.type(screen.getByPlaceholderText(PLACEHOLDER), "analytics");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(onAdd).not.toHaveBeenCalled();
    // Nothing new to add collapses the editor.
    expect(screen.getByRole("button", { name: "Add tags" })).toBeInTheDocument();
  });

  it("submits on Enter and cancels on Escape", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn().mockResolvedValue(undefined);
    renderControl({ onAdd });

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    const input = screen.getByPlaceholderText(PLACEHOLDER);
    await user.type(input, "prod{Enter}");
    expect(onAdd).toHaveBeenCalledWith(["prod"]);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add tags" })).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    await user.type(screen.getByPlaceholderText(PLACEHOLDER), "temp{Escape}");
    expect(screen.getByRole("button", { name: "Add tags" })).toBeInTheDocument();
    expect(onAdd).toHaveBeenCalledTimes(1);
  });

  it("shows the pending label on the Add button while the request is in flight", async () => {
    const user = userEvent.setup();
    let resolveAdd: () => void = () => {};
    const onAdd = vi.fn().mockReturnValue(
      new Promise<void>((resolve) => {
        resolveAdd = resolve;
      }),
    );
    renderControl({ onAdd });

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    await user.type(screen.getByPlaceholderText(PLACEHOLDER), "beta");
    await user.click(screen.getByRole("button", { name: "Add" }));

    // While the promise is unresolved the button reads "Adding..." and is disabled.
    const pendingButton = await screen.findByRole("button", { name: "Adding..." });
    expect(pendingButton).toBeDisabled();

    resolveAdd();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add tags" })).toBeInTheDocument(),
    );
  });

  it("disables the Add button when the input is empty", async () => {
    const user = userEvent.setup();
    renderControl();

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });
});
