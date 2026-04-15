import { createContext, useContext, useState, useCallback, useMemo, ReactNode } from "react";
import { IntlProvider as ReactIntlProvider } from "react-intl";
import type { SupportedLocale } from "./types";
import { SUPPORTED_LOCALES } from "./types";

// Import locale messages
import enUS from "./locales/en-US";
import ptBR from "./locales/pt-BR";
import esES from "./locales/es-ES";

const messages: Record<SupportedLocale, Record<string, string>> = {
  "en-US": enUS,
  "pt-BR": ptBR,
  "es-ES": esES,
};

interface I18nContextValue {
  locale: SupportedLocale;
  setLocale: (locale: SupportedLocale) => void;
}

const I18nContext = createContext<I18nContextValue | undefined>(undefined);

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return context;
}

function detectUserLocale(): SupportedLocale {
  // 1. Check localStorage
  const stored = localStorage.getItem("user-locale") as SupportedLocale;
  if (stored && SUPPORTED_LOCALES.includes(stored)) {
    document.documentElement.lang = stored;
    return stored;
  }

  // 2. Check browser language
  const browserLang = navigator.language as SupportedLocale;
  if (SUPPORTED_LOCALES.includes(browserLang)) {
    document.documentElement.lang = browserLang;
    return browserLang;
  }

  // 3. Try language without region (en-US -> en)
  const langOnly = browserLang.split("-")[0];
  const match = SUPPORTED_LOCALES.find((l) => l.startsWith(langOnly));
  if (match) {
    document.documentElement.lang = match;
    return match;
  }

  // 4. Default fallback
  const defaultLocale = "en-US";
  document.documentElement.lang = defaultLocale;
  return defaultLocale;
}

interface I18nProviderProps {
  children: ReactNode;
}

export function I18nProvider({ children }: I18nProviderProps) {
  const [locale, setLocaleState] = useState<SupportedLocale>(detectUserLocale);

  const setLocale = useCallback((newLocale: SupportedLocale) => {
    setLocaleState(newLocale);
    localStorage.setItem("user-locale", newLocale);
    // Update HTML lang attribute for accessibility
    document.documentElement.lang = newLocale;
  }, []);

  const value = useMemo<I18nContextValue>(() => ({ locale, setLocale }), [locale, setLocale]);

  return (
    <I18nContext.Provider value={value}>
      <ReactIntlProvider locale={locale} messages={messages[locale]} defaultLocale="en-US">
        {children}
      </ReactIntlProvider>
    </I18nContext.Provider>
  );
}
