import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { ResourceDetailsPanel } from "./ResourceDetailsPanel";
import type { ResourceRead } from "@/generated/types";

function mockResource(overrides?: Partial<NonNullable<ResourceRead>>): NonNullable<ResourceRead> {
  return {
    id: "42",
    uri: "file:///a.txt",
    name: "a.txt",
    description: null,
    mimeType: "text/plain",
    size: 10,
    createdAt: "2026-01-01T00:00:00",
    updatedAt: "2026-01-02T00:00:00",
    enabled: true,
    tags: ["alerts"],
    ...overrides,
  };
}

describe("ResourceDetailsPanel inline tag add", () => {
  it("calls onAddTag with the merged, de-duplicated tag list", async () => {
    const user = userEvent.setup();
    const onAddTag = vi.fn().mockResolvedValue(undefined);

    render(
      <ResourceDetailsPanel
        resources={[mockResource()]}
        gatewaySlug="local"
        open
        onClose={vi.fn()}
        onAddTag={onAddTag}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    await user.type(screen.getByPlaceholderText("Add tags separated with commas"), "dev, alerts");
    await user.click(screen.getByRole("button", { name: "Add" }));

    // "alerts" already exists and is dropped; "dev" is appended.
    expect(onAddTag).toHaveBeenCalledWith("42", ["alerts", "dev"]);
  });

  it("disables the add-tag trigger when onAddTag is omitted", () => {
    render(
      <ResourceDetailsPanel
        resources={[mockResource({ tags: [] })]}
        gatewaySlug="local"
        open
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Add tags" })).toBeDisabled();
  });
});
