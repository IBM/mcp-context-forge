import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "../../i18n";
import { LanguageSwitcher } from "./LanguageSwitcher";

describe("LanguageSwitcher", () => {
  beforeEach(() => {
    // Clear localStorage before each test to ensure clean state
    localStorage.clear();
    // Reset document lang attribute
    document.documentElement.lang = "en-US";
    // Clear any mocks
    vi.clearAllMocks();
  });

  describe("Rendering", () => {
    it("should render the select element", () => {
      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox");
      expect(select).toBeInTheDocument();
    });

    it("should have correct accessibility label", () => {
      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox");
      expect(select).toHaveAttribute("aria-label", "Select language");
    });

    it("should apply correct CSS classes for styling", () => {
      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox");
      expect(select).toHaveClass("rounded-md", "border", "px-3", "py-1.5", "text-sm");
    });
  });

  describe("Locale Options", () => {
    it("should render all supported locales as options", () => {
      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox") as HTMLSelectElement;
      const options = Array.from(select.options);

      expect(options).toHaveLength(3);
    });

    it("should render English (US) option with flag", () => {
      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const option = screen.getByRole("option", { name: /🇺🇸 English \(US\)/ });
      expect(option).toBeInTheDocument();
      expect(option).toHaveValue("en-US");
    });

    it("should render Portuguese (BR) option with flag", () => {
      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const option = screen.getByRole("option", { name: /🇧🇷 Português \(BR\)/ });
      expect(option).toBeInTheDocument();
      expect(option).toHaveValue("pt-BR");
    });

    it("should render Spanish (ES) option with flag", () => {
      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const option = screen.getByRole("option", { name: /🇪🇸 Español \(ES\)/ });
      expect(option).toBeInTheDocument();
      expect(option).toHaveValue("es-ES");
    });
  });

  describe("Initial Value", () => {
    it("should default to en-US when no preference is stored", () => {
      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox") as HTMLSelectElement;
      expect(select.value).toBe("en-US");
    });

    it("should use stored locale preference from localStorage", () => {
      localStorage.setItem("user-locale", "pt-BR");

      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox") as HTMLSelectElement;
      expect(select.value).toBe("pt-BR");
    });

    it("should use stored Spanish preference from localStorage", () => {
      localStorage.setItem("user-locale", "es-ES");

      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox") as HTMLSelectElement;
      expect(select.value).toBe("es-ES");
    });
  });

  describe("Locale Switching", () => {
    it("should update locale when English option is selected", async () => {
      const user = userEvent.setup();

      localStorage.setItem("user-locale", "pt-BR");

      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox") as HTMLSelectElement;
      expect(select.value).toBe("pt-BR");

      await user.selectOptions(select, "en-US");

      expect(select.value).toBe("en-US");
      expect(localStorage.getItem("user-locale")).toBe("en-US");
    });

    it("should update locale when Portuguese option is selected", async () => {
      const user = userEvent.setup();

      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox") as HTMLSelectElement;
      await user.selectOptions(select, "pt-BR");

      expect(select.value).toBe("pt-BR");
      expect(localStorage.getItem("user-locale")).toBe("pt-BR");
    });

    it("should update locale when Spanish option is selected", async () => {
      const user = userEvent.setup();

      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox") as HTMLSelectElement;
      await user.selectOptions(select, "es-ES");

      expect(select.value).toBe("es-ES");
      expect(localStorage.getItem("user-locale")).toBe("es-ES");
    });

    it("should persist locale selection to localStorage", async () => {
      const user = userEvent.setup();

      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox");
      await user.selectOptions(select, "pt-BR");

      const stored = localStorage.getItem("user-locale");
      expect(stored).toBe("pt-BR");
    });
  });

  describe("Multiple Switches", () => {
    it("should handle sequential locale changes", async () => {
      const user = userEvent.setup();

      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox") as HTMLSelectElement;

      // Change to Portuguese
      await user.selectOptions(select, "pt-BR");
      expect(select.value).toBe("pt-BR");
      expect(localStorage.getItem("user-locale")).toBe("pt-BR");

      // Change to Spanish
      await user.selectOptions(select, "es-ES");
      expect(select.value).toBe("es-ES");
      expect(localStorage.getItem("user-locale")).toBe("es-ES");

      // Change back to English
      await user.selectOptions(select, "en-US");
      expect(select.value).toBe("en-US");
      expect(localStorage.getItem("user-locale")).toBe("en-US");
    });
  });

  describe("HTML Lang Attribute", () => {
    it("should update document.documentElement.lang when locale changes", async () => {
      const user = userEvent.setup();

      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox");
      await user.selectOptions(select, "pt-BR");

      expect(document.documentElement.lang).toBe("pt-BR");
    });
  });

  describe("Option Accessibility", () => {
    it("should have proper option values", () => {
      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox") as HTMLSelectElement;
      const optionValues = Array.from(select.options).map((opt) => opt.value);

      expect(optionValues).toContain("en-US");
      expect(optionValues).toContain("pt-BR");
      expect(optionValues).toContain("es-ES");
    });

    it("should have unique option keys (no warnings in React)", () => {
      const { container } = render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const options = container.querySelectorAll("option");
      const values = Array.from(options).map((opt) => opt.value);

      // All values should be unique (keys used in map should be unique)
      expect(new Set(values).size).toBe(values.length);
    });
  });

  describe("Interaction Validation", () => {
    it("should be keyboard accessible", async () => {
      const user = userEvent.setup();

      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox");

      // Tab to the select
      await user.tab();
      expect(select).toHaveFocus();

      // Use keyboard to change selection
      await user.selectOptions(select, "pt-BR");

      expect(select).toHaveValue("pt-BR");
    });

    it("should be clickable", async () => {
      const user = userEvent.setup();

      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox");

      await user.click(select);
      await user.selectOptions(select, "es-ES");

      expect(select).toHaveValue("es-ES");
    });
  });

  describe("Edge Cases", () => {
    it("should handle selecting the same locale twice", async () => {
      const user = userEvent.setup();

      render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox");

      await user.selectOptions(select, "pt-BR");
      expect(select).toHaveValue("pt-BR");

      // Select the same option again
      await user.selectOptions(select, "pt-BR");
      expect(select).toHaveValue("pt-BR");
      expect(localStorage.getItem("user-locale")).toBe("pt-BR");
    });

    it("should maintain selected value after re-render", async () => {
      const user = userEvent.setup();

      const { rerender } = render(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const select = screen.getByRole("combobox");

      await user.selectOptions(select, "pt-BR");
      expect(select).toHaveValue("pt-BR");

      // Force a re-render
      rerender(
        <I18nProvider>
          <LanguageSwitcher />
        </I18nProvider>,
      );

      const updatedSelect = screen.getByRole("combobox") as HTMLSelectElement;
      expect(updatedSelect.value).toBe("pt-BR");
    });
  });
});
