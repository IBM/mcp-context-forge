export const SUPPORTED_LOCALES = ["en-US", "pt-BR", "es-ES"] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export interface LocaleMessages {
  [key: string]: string;
}
