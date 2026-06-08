import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider, useI18n } from "./IntlProvider";

function LocaleConsumer() {
  const { locale, setLocale } = useI18n();
  return (
    <>
      <span>{locale}</span>
      <button type="button" onClick={() => setLocale("pt-BR")}>
        Set pt-BR
      </button>
    </>
  );
}

function NoProviderConsumer() {
  useI18n();
  return null;
}

describe("I18nProvider", () => {
  const originalLanguage = navigator.language;

  beforeEach(() => {
    localStorage.clear();
    document.documentElement.lang = "";
  });

  afterEach(() => {
    Object.defineProperty(window.navigator, "language", {
      value: originalLanguage,
      configurable: true,
    });
  });

  it("throws when useI18n is used outside the provider", () => {
    expect(() => render(<NoProviderConsumer />)).toThrow(
      "useI18n must be used within I18nProvider",
    );
  });

  it("uses localStorage locale when available and updates the html lang attribute", () => {
    localStorage.setItem("user-locale", "pt-BR");
    Object.defineProperty(window.navigator, "language", {
      value: "en-US",
      configurable: true,
    });

    render(
      <I18nProvider>
        <LocaleConsumer />
      </I18nProvider>,
    );

    expect(screen.getByText("pt-BR")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("pt-BR");
  });

  it("falls back to the browser locale when localStorage locale is missing", () => {
    localStorage.removeItem("user-locale");
    Object.defineProperty(window.navigator, "language", {
      value: "es-ES",
      configurable: true,
    });

    render(
      <I18nProvider>
        <LocaleConsumer />
      </I18nProvider>,
    );

    expect(screen.getByText("es-ES")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("es-ES");
  });

  it("falls back to a matching supported locale when only language matches", () => {
    localStorage.removeItem("user-locale");
    Object.defineProperty(window.navigator, "language", {
      value: "en-GB",
      configurable: true,
    });

    render(
      <I18nProvider>
        <LocaleConsumer />
      </I18nProvider>,
    );

    expect(screen.getByText("en-US")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en-US");
  });

  it("defaults to en-US when the browser locale is unsupported", () => {
    localStorage.removeItem("user-locale");
    Object.defineProperty(window.navigator, "language", {
      value: "fr-FR",
      configurable: true,
    });

    render(
      <I18nProvider>
        <LocaleConsumer />
      </I18nProvider>,
    );

    expect(screen.getByText("en-US")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en-US");
  });

  it("updates locale state, localStorage, and html lang when setLocale is called", async () => {
    localStorage.removeItem("user-locale");
    Object.defineProperty(window.navigator, "language", {
      value: "en-US",
      configurable: true,
    });

    render(
      <I18nProvider>
        <LocaleConsumer />
      </I18nProvider>,
    );

    expect(screen.getByText("en-US")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en-US");

    await userEvent.click(screen.getByRole("button", { name: "Set pt-BR" }));

    expect(screen.getByText("pt-BR")).toBeInTheDocument();
    expect(localStorage.getItem("user-locale")).toBe("pt-BR");
    expect(document.documentElement.lang).toBe("pt-BR");
  });
});
