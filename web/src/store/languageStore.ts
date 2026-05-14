import { create } from "zustand";

import i18n, {
  DEFAULT_LANGUAGE,
  LANGUAGE_KEY,
  SUPPORTED_LANGUAGES,
  type SupportedLanguage,
} from "../i18n/config";

interface LanguageState {
  language: SupportedLanguage;
  setLanguage: (lang: SupportedLanguage) => void;
}

function readPersistedLanguage(): SupportedLanguage {
  try {
    const raw = localStorage.getItem(LANGUAGE_KEY);
    if (raw && (SUPPORTED_LANGUAGES as readonly string[]).includes(raw)) {
      return raw as SupportedLanguage;
    }
  } catch {
    // Ignore
  }
  return DEFAULT_LANGUAGE;
}

export const useLanguageStore = create<LanguageState>((set) => ({
  language: readPersistedLanguage(),
  setLanguage: (lang) => {
    try {
      localStorage.setItem(LANGUAGE_KEY, lang);
    } catch {
      // Ignore
    }
    void i18n.changeLanguage(lang);
    set({ language: lang });
  },
}));
