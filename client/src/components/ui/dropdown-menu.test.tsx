import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuRadioItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuGroup,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuRadioGroup,
  DropdownMenuPortal,
} from "./dropdown-menu";

describe("DropdownMenu Components", () => {
  let user: ReturnType<typeof userEvent.setup>;

  beforeEach(() => {
    user = userEvent.setup();
  });

  it("renders DropdownMenu with trigger", () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
      </DropdownMenu>
    );
    expect(screen.getByText("Open")).toBeInTheDocument();
  });

  it("renders DropdownMenuLabel with correct text", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuLabel>My Label</DropdownMenuLabel>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByText("My Label")).toBeInTheDocument());
  });

  it("renders DropdownMenuSeparator as visual separator", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuSeparator />
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => expect(document.querySelector('[role="separator"]')).toBeInTheDocument());
  });

  it("renders multiple DropdownMenuItems", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem>Item 1</DropdownMenuItem>
          <DropdownMenuItem>Item 2</DropdownMenuItem>
          <DropdownMenuItem>Item 3</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getAllByRole("menuitem")).toHaveLength(3));
  });

  it("renders DropdownMenuShortcut with correct styling", () => {
    render(
      <DropdownMenuShortcut>⌘K</DropdownMenuShortcut>
    );
    expect(screen.getByText("⌘K")).toBeInTheDocument();
  });

  it("renders DropdownMenuShortcut within menu context", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem>
            Save
            <DropdownMenuShortcut>⌘S</DropdownMenuShortcut>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByText("⌘S")).toBeInTheDocument());
  });

  it("renders DropdownMenuGroup", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuGroup>
            <DropdownMenuItem>Item 1</DropdownMenuItem>
            <DropdownMenuItem>Item 2</DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getAllByRole("menuitem")).toHaveLength(2));
  });

  it("renders DropdownMenuCheckboxItem when checked", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuCheckboxItem checked={true}>
            Checkbox
          </DropdownMenuCheckboxItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => {
      const checkbox = screen.getByRole("menuitemcheckbox");
      expect(checkbox).toHaveAttribute("data-state", "checked");
    });
  });

  it("renders DropdownMenuCheckboxItem when unchecked", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuCheckboxItem checked={false}>
            Unchecked
          </DropdownMenuCheckboxItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => {
      const checkbox = screen.getByRole("menuitemcheckbox");
      expect(checkbox).toHaveAttribute("data-state", "unchecked");
    });
  });

  it("renders DropdownMenuRadioGroup with RadioItems", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuRadioGroup value="a">
            <DropdownMenuRadioItem value="a">Option A</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="b">Option B</DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getAllByRole("menuitemradio")).toHaveLength(2));
  });

  it("renders DropdownMenuRadioItem with checked state", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuRadioGroup value="a">
            <DropdownMenuRadioItem value="a">Selected</DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => {
      const radio = screen.getByRole("menuitemradio");
      expect(radio).toHaveAttribute("data-state", "checked");
    });
  });

  it("renders DropdownMenuSub with SubTrigger and SubContent", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>Sub Menu</DropdownMenuSubTrigger>
            <DropdownMenuPortal>
              <DropdownMenuSubContent>
                <DropdownMenuItem>Sub Item</DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuPortal>
          </DropdownMenuSub>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByText("Sub Menu")).toBeInTheDocument());
  });

  it("renders DropdownMenuSubTrigger with inset prop", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger inset>Inset Sub</DropdownMenuSubTrigger>
          </DropdownMenuSub>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByText("Inset Sub")).toBeInTheDocument());
  });

  it("renders DropdownMenuItem with inset prop", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem inset>Inset Item</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByText("Inset Item")).toBeInTheDocument());
  });

  it("renders DropdownMenuLabel with inset prop", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuLabel inset>Inset Label</DropdownMenuLabel>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByText("Inset Label")).toBeInTheDocument());
  });

  it("renders Portal to ensure content renders outside DOM tree", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuPortal>
          <DropdownMenuContent>
            <DropdownMenuItem>Item</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenuPortal>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByText("Item")).toBeInTheDocument());
  });

  it("applies custom className to MenuItem", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem className="custom-class">Styled Item</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => {
      const item = screen.getByText("Styled Item");
      expect(item).toHaveClass("custom-class");
    });
  });

  it("applies custom className to CheckboxItem", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuCheckboxItem className="custom-class">Styled Checkbox</DropdownMenuCheckboxItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => {
      const checkbox = screen.getByText("Styled Checkbox");
      expect(checkbox.closest('[role="menuitemcheckbox"]')).toHaveClass("custom-class");
    });
  });

  it("applies custom className to Label", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuLabel className="custom-label">Custom Label</DropdownMenuLabel>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => {
      const label = screen.getByText("Custom Label");
      expect(label).toHaveClass("custom-label");
    });
  });

  it("applies custom className to SubTrigger", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger className="custom-sub">Sub</DropdownMenuSubTrigger>
          </DropdownMenuSub>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => {
      const subTrigger = screen.getByText("Sub");
      expect(subTrigger).toHaveClass("custom-sub");
    });
  });

  it("renders disabled MenuItem", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem disabled>Disabled Item</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => {
      const item = screen.getByText("Disabled Item");
      expect(item).toHaveAttribute("data-disabled");
    });
  });

  it("renders disabled CheckboxItem", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuCheckboxItem disabled>Disabled Checkbox</DropdownMenuCheckboxItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => {
      const checkbox = screen.getByText("Disabled Checkbox");
      expect(checkbox.closest('[role="menuitemcheckbox"]')).toHaveAttribute("data-disabled");
    });
  });

  it("renders multiple menu items with mixed content", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Menu</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuLabel>Options</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem>Edit</DropdownMenuItem>
          <DropdownMenuItem>Delete</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuCheckboxItem checked={true}>Show Details</DropdownMenuCheckboxItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
    await user.click(screen.getByRole("button"));
    await waitFor(() => {
      expect(screen.getByText("Options")).toBeInTheDocument();
      expect(screen.getByText("Edit")).toBeInTheDocument();
      expect(screen.getByText("Delete")).toBeInTheDocument();
      expect(screen.getByText("Show Details")).toBeInTheDocument();
    });
  });
});