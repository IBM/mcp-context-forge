import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { BackButton } from "./back-button";

describe("BackButton", () => {
  it("renders the localized Back label", () => {
    render(<BackButton onClick={vi.fn()} />);

    expect(screen.getByRole("button", { name: /back/i })).toBeInTheDocument();
  });

  it("calls onClick when activated", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<BackButton onClick={onClick} />);

    await user.click(screen.getByRole("button", { name: /back/i }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("is a non-submitting button so it never submits an enclosing form", () => {
    render(
      <form>
        <BackButton onClick={vi.fn()} />
      </form>,
    );

    expect(screen.getByRole("button", { name: /back/i })).toHaveAttribute("type", "button");
  });

  it("merges custom classes with the base styles", () => {
    render(<BackButton onClick={vi.fn()} className="custom-back-cls" />);

    expect(screen.getByRole("button", { name: /back/i })).toHaveClass("custom-back-cls");
  });
});
