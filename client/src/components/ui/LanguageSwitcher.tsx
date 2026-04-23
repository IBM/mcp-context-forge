import { useI18n } from "../../i18n";
import { SUPPORTED_LOCALES, SupportedLocale } from "../../i18n/types";

const LOCALE_NAMES: Record<string, string> = {
  "en-US": "English (US)",
  "pt-BR": "Português (BR)",
  "es-ES": "Español (ES)",
};

const LOCALE_FLAGS: Record<string, string> = {
  "en-US": "🇺🇸",
  "pt-BR": "🇧🇷",
  "es-ES": "🇪🇸",
};

export function LanguageSwitcher() {
  const { locale, setLocale } = useI18n();

  return (
    <select
      value={locale}
      onChange={(e) => setLocale(e.target.value as SupportedLocale)}
      className="rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 dark:focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:focus:ring-blue-400"
      aria-label="Select language"
    >
      {SUPPORTED_LOCALES.map((loc) => (
        <option key={loc} value={loc}>
          {LOCALE_FLAGS[loc]} {LOCALE_NAMES[loc]}
        </option>
      ))}
    </select>
  );
}
