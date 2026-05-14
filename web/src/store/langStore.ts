import { create } from "zustand";
import { DEFAULT_LANG, type Lang } from "../i18n/messages";

const LANG_KEY = "app_lang";

function readPersistedLang(): Lang {
  try {
    const stored = localStorage.getItem(LANG_KEY);
    if (stored === "zh-TW" || stored === "en-US") return stored;
  } catch {
    // ignore storage failures
  }
  return navigator.language.startsWith("zh") ? "zh-TW" : DEFAULT_LANG;
}

interface LangState {
  lang: Lang;
  setLang: (lang: Lang) => void;
}

export const useLangStore = create<LangState>((set) => ({
  lang: readPersistedLang(),
  setLang: (lang) => {
    try {
      localStorage.setItem(LANG_KEY, lang);
    } catch {
      // ignore storage failures
    }
    set({ lang });
  },
}));
