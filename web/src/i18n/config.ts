import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enUS from "./locales/en-US.json";
import zhTW from "./locales/zh-TW.json";

export const SUPPORTED_LANGUAGES = ["zh-TW", "en-US"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

export const DEFAULT_LANGUAGE: SupportedLanguage = "zh-TW";

const LANGUAGE_KEY = "ui_language";

function readPersistedLanguage(): SupportedLanguage {
  try {
    const raw = localStorage.getItem(LANGUAGE_KEY);
    if (raw && (SUPPORTED_LANGUAGES as readonly string[]).includes(raw)) {
      return raw as SupportedLanguage;
    }
  } catch {
    // Ignore storage failures (private mode, etc.)
  }
  return DEFAULT_LANGUAGE;
}

void i18n.use(initReactI18next).init({
  resources: {
    "zh-TW": { translation: zhTW },
    "en-US": { translation: enUS },
  },
  lng: readPersistedLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  interpolation: {
    escapeValue: false,
  },
});

export { LANGUAGE_KEY };
export default i18n;
