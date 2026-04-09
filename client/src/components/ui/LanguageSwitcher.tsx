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
      className="rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
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
